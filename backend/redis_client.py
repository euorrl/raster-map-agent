import json
import os
import time
from typing import Any

from dotenv import load_dotenv
from redis import Redis

JOB_KEY_PREFIX = "job:"
DEFAULT_REDIS_URL = "redis://localhost:6379/0"
DEFAULT_QUEUE_NAME = "raster_jobs"
DEFAULT_JOB_TTL_SECONDS = 1800
DEFAULT_JOB_RUNNING_TIMEOUT_SECONDS = 180


def get_redis_url() -> str:
    load_dotenv()
    return os.getenv("REDIS_URL", DEFAULT_REDIS_URL)


def get_queue_name() -> str:
    load_dotenv()
    return os.getenv("RASTER_JOB_QUEUE", DEFAULT_QUEUE_NAME)


def get_job_ttl_seconds() -> int:
    load_dotenv()
    raw_value = os.getenv("JOB_TTL_SECONDS", str(DEFAULT_JOB_TTL_SECONDS))
    try:
        ttl_seconds = int(raw_value)
    except ValueError:
        return DEFAULT_JOB_TTL_SECONDS

    return ttl_seconds if ttl_seconds > 0 else DEFAULT_JOB_TTL_SECONDS


def get_job_running_timeout_seconds() -> int:
    load_dotenv()
    raw_value = os.getenv(
        "JOB_RUNNING_TIMEOUT_SECONDS",
        str(DEFAULT_JOB_RUNNING_TIMEOUT_SECONDS),
    )
    try:
        timeout_seconds = int(raw_value)
    except ValueError:
        return DEFAULT_JOB_RUNNING_TIMEOUT_SECONDS

    if timeout_seconds > 0:
        return timeout_seconds
    return DEFAULT_JOB_RUNNING_TIMEOUT_SECONDS


def get_redis() -> Redis:
    return Redis.from_url(get_redis_url(), decode_responses=True)


def job_key(job_id: str) -> str:
    return f"{JOB_KEY_PREFIX}{job_id}"


def create_job(redis: Redis, job_id: str, query: str) -> None:
    now = int(time.time())
    job = {
        "status": "queued",
        "query": query,
        "created_at": now,
        "updated_at": now,
        "stage": "queued",
        "message": "任务已进入队列，等待 worker 处理。",
        "workspace_dir": "",
        "final_answer": "",
        "error": "",
    }
    redis.set(job_key(job_id), json.dumps(job, ensure_ascii=False))
    redis.rpush(get_queue_name(), job_id)


def get_job(redis: Redis, job_id: str) -> dict[str, Any] | None:
    raw_job = redis.get(job_key(job_id))
    if raw_job is None:
        return None
    job = json.loads(raw_job)
    if not isinstance(job, dict):
        return None
    return job


def update_job(redis: Redis, job_id: str, **fields: Any) -> dict[str, Any]:
    job = get_job(redis, job_id)
    if job is None:
        raise KeyError(job_id)

    job.update({key: "" if value is None else value for key, value in fields.items()})
    redis.set(job_key(job_id), json.dumps(job, ensure_ascii=False))
    return job


def delete_job(redis: Redis, job_id: str) -> None:
    redis.delete(job_key(job_id))
    redis.lrem(get_queue_name(), 0, job_id)


def iter_job_ids(redis: Redis):
    for key in redis.scan_iter(f"{JOB_KEY_PREFIX}*"):
        yield str(key).removeprefix(JOB_KEY_PREFIX)


def pop_job_id(redis: Redis, timeout: int = 5) -> str | None:
    result = redis.blpop(get_queue_name(), timeout=timeout)
    if result is None:
        return None

    _, job_id = result
    return str(job_id)
