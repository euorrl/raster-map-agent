import json
import shutil
import threading
import time
from pathlib import Path

from redis import Redis
from redis.exceptions import RedisError

from app.utils import configure_logging, get_logger
from app.workflows.workflow import run_workflow
from backend.redis_client import (
    delete_job,
    get_job,
    get_job_running_timeout_seconds,
    get_job_ttl_seconds,
    get_redis,
    iter_job_ids,
    pop_job_id,
    update_job,
)

logger = get_logger(__name__)

OUTPUT_FILENAMES = ("metadata.json", "preview.png", "result.tif")
HEARTBEAT_INTERVAL_SECONDS = 30


def process_job(redis: Redis, job_id: str) -> None:
    job = get_job(redis, job_id)
    if job is None:
        logger.warning("Skipping missing job job_id=%s", job_id)
        return

    query = str(job.get("query", "")).strip()
    if not query:
        update_job(redis, job_id, status="failed", error="missing query")
        return

    update_job(
        redis,
        job_id,
        status="running",
        stage="workflow",
        message="任务正在运行，worker 会持续更新心跳。",
        updated_at=int(time.time()),
        error="",
        final_answer="",
        workspace_dir="",
    )

    stop_heartbeat = threading.Event()
    heartbeat_thread = threading.Thread(
        target=_heartbeat_job,
        args=(redis, job_id, stop_heartbeat),
        daemon=True,
    )
    heartbeat_thread.start()

    try:
        state = run_workflow(query)
    except Exception as error:
        logger.exception("Workflow failed job_id=%s", job_id)
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1)
        update_job(
            redis,
            job_id,
            status="failed",
            stage="failed",
            message="任务执行失败。",
            updated_at=int(time.time()),
            error=str(error),
        )
        return
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=1)

    workspace_dir = str(state.workspace.get("workspace_dir", ""))
    final_answer = state.final_answer or ""
    if state.status == "completed":
        update_job(
            redis,
            job_id,
            status="succeeded",
            stage="completed",
            message="任务已完成，结果文件可下载。",
            updated_at=int(time.time()),
            workspace_dir=workspace_dir,
            final_answer=final_answer,
            error="",
        )
        return

    error_text = "; ".join(state.errors) or final_answer or str(state.status)
    if _has_complete_output(workspace_dir):
        logger.warning(
            "Workflow ended as failed but complete artifacts exist job_id=%s "
            "workspace_dir=%s error=%s",
            job_id,
            workspace_dir,
            error_text,
        )
        update_job(
            redis,
            job_id,
            status="succeeded",
            stage="completed",
            message="结果文件已生成，final answer 使用兜底回答。",
            updated_at=int(time.time()),
            workspace_dir=workspace_dir,
            final_answer=_build_artifact_fallback_answer(workspace_dir, error_text),
            error="",
        )
        return

    update_job(
        redis,
        job_id,
        status="failed",
        stage="failed",
        message="任务执行失败。",
        updated_at=int(time.time()),
        workspace_dir=workspace_dir,
        final_answer=final_answer,
        error=error_text,
    )


def run_worker() -> None:
    configure_logging("INFO")
    redis = get_redis()
    ttl_seconds = get_job_ttl_seconds()
    running_timeout_seconds = get_job_running_timeout_seconds()
    logger.info("Worker started")
    while True:
        try:
            mark_stale_running_jobs(
                redis,
                running_timeout_seconds=running_timeout_seconds,
            )
            cleanup_expired_jobs(redis, ttl_seconds=ttl_seconds)
            job_id = pop_job_id(redis)
            if job_id is None:
                continue

            logger.info("Processing job job_id=%s", job_id)
            process_job(redis, job_id)
            mark_stale_running_jobs(
                redis,
                running_timeout_seconds=running_timeout_seconds,
            )
            cleanup_expired_jobs(redis, ttl_seconds=ttl_seconds)
        except RedisError as error:
            logger.warning("Redis unavailable; retrying in 5 seconds: %s", error)
            time.sleep(5)


def mark_stale_running_jobs(
    redis: Redis,
    running_timeout_seconds: int | None = None,
    now: int | None = None,
) -> None:
    running_timeout_seconds = (
        running_timeout_seconds or get_job_running_timeout_seconds()
    )
    now = now or int(time.time())

    for job_id in list(iter_job_ids(redis)):
        job = get_job(redis, job_id)
        if job is None or job.get("status") != "running":
            continue

        updated_at = _parse_timestamp(job.get("updated_at"))
        if updated_at is None:
            updated_at = _parse_timestamp(job.get("created_at"))

        if updated_at is None or now - updated_at < running_timeout_seconds:
            continue

        error_text = (
            "Worker heartbeat timed out. The worker may have stopped during "
            "workflow execution, or the task may be too large for current "
            "container resources."
        )
        update_job(
            redis,
            job_id,
            status="failed",
            stage="stale_running",
            message="任务长时间没有 worker 心跳，已自动标记为失败。",
            updated_at=now,
            error=error_text,
        )
        logger.warning("Marked stale running job as failed job_id=%s", job_id)


def cleanup_expired_jobs(
    redis: Redis,
    ttl_seconds: int | None = None,
    now: int | None = None,
) -> None:
    ttl_seconds = ttl_seconds or get_job_ttl_seconds()
    now = now or int(time.time())

    for job_id in list(iter_job_ids(redis)):
        job = get_job(redis, job_id)
        if job is None:
            continue

        created_at = _parse_timestamp(job.get("created_at"))
        if created_at is None or now - created_at < ttl_seconds:
            continue

        if job.get("status") == "running":
            logger.info("Skipping running expired job job_id=%s", job_id)
            continue

        workspace_dir = str(job.get("workspace_dir", ""))
        _remove_workspace_dir(workspace_dir)
        delete_job(redis, job_id)
        logger.info(
            "Deleted expired job job_id=%s workspace_dir=%s",
            job_id,
            workspace_dir,
        )


def _has_complete_output(workspace_dir: str) -> bool:
    if not workspace_dir:
        return False

    output_dir = Path(workspace_dir) / "output"
    return all((output_dir / filename).is_file() for filename in OUTPUT_FILENAMES)


def _build_artifact_fallback_answer(workspace_dir: str, error_text: str) -> str:
    metadata = _read_metadata(workspace_dir)

    product_name = _nested_str(metadata, "product", "name")
    aoi_query = _nested_str(metadata, "area", "aoi_query")
    data_source = _nested_str(metadata, "source", "data_source")
    provider = _nested_str(metadata, "source", "provider")
    start_date = _nested_str(metadata, "time_range", "start_date")
    end_date = _nested_str(metadata, "time_range", "end_date")
    crs = _nested_str(metadata, "spatial", "crs")
    resolution = _nested_value(metadata, "spatial", "resolution_meters")
    coverage = _nested_value(metadata, "quality", "coverage_ratio")
    output_dir = Path(workspace_dir) / "output"

    lines = [
        "结果文件已生成，但最后的自然语言回答生成步骤没有完成。",
        "这通常是 final answer 的 LLM 请求超时，不代表 GeoTIFF、预览图或 metadata 生成失败。",
    ]

    details = []
    if product_name:
        details.append(f"产品: {product_name}")
    if aoi_query:
        details.append(f"区域: {aoi_query}")
    if start_date or end_date:
        details.append(
            f"时间范围: {start_date or 'unknown'} 到 {end_date or 'unknown'}"
        )
    if data_source or provider:
        source_text = data_source or "unknown"
        if provider:
            source_text = f"{source_text} / {provider}"
        details.append(f"数据源: {source_text}")
    if resolution:
        details.append(f"分辨率: {resolution} m")
    if crs:
        details.append(f"CRS: {crs}")
    if coverage is not None:
        details.append(f"覆盖率: {coverage}")

    if details:
        lines.append("")
        lines.extend(f"- {detail}" for detail in details)

    lines.extend(
        [
            "",
            f"输出目录: {output_dir}",
            "可用文件: metadata.json, preview.png, result.tif",
        ]
    )

    if error_text:
        lines.append(f"收尾步骤提示: {error_text}")

    return "\n".join(lines)


def _read_metadata(workspace_dir: str) -> dict:
    metadata_path = Path(workspace_dir) / "output" / "metadata.json"
    try:
        with metadata_path.open("r", encoding="utf-8") as file:
            metadata = json.load(file)
    except (OSError, json.JSONDecodeError):
        return {}

    return metadata if isinstance(metadata, dict) else {}


def _nested_value(data: dict, *keys: str):
    value = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _nested_str(data: dict, *keys: str) -> str:
    value = _nested_value(data, *keys)
    return value if isinstance(value, str) else ""


def _heartbeat_job(redis: Redis, job_id: str, stop_event: threading.Event) -> None:
    while not stop_event.wait(HEARTBEAT_INTERVAL_SECONDS):
        try:
            update_job(
                redis,
                job_id,
                updated_at=int(time.time()),
                stage="workflow",
                message="任务仍在运行，worker 心跳正常。",
            )
        except (KeyError, RedisError) as error:
            logger.warning(
                "Failed to update job heartbeat job_id=%s: %s",
                job_id,
                error,
            )


def _parse_timestamp(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _remove_workspace_dir(workspace_dir: str) -> None:
    if not workspace_dir:
        return

    workspace_path = Path(workspace_dir)
    if not _is_safe_workspace_path(workspace_path):
        logger.warning("Refusing to delete unsafe workspace_dir=%s", workspace_dir)
        return

    shutil.rmtree(workspace_path, ignore_errors=True)


def _is_safe_workspace_path(workspace_path: Path) -> bool:
    try:
        resolved_workspace = workspace_path.resolve()
        data_root = Path("data").resolve()
        return resolved_workspace != data_root and resolved_workspace.is_relative_to(
            data_root
        )
    except (OSError, RuntimeError):
        return False


if __name__ == "__main__":
    run_worker()
