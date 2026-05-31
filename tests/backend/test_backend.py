import json
import os
from pathlib import Path

from fastapi.testclient import TestClient

from app.schemas import AgentState
from backend.main import app
from backend.redis_client import create_job, get_job, job_key, update_job
import backend.jobs as jobs_module
import backend.worker as worker_module


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.queues = {}

    def set(self, key, value):
        self.values[key] = value

    def get(self, key):
        return self.values.get(key)

    def rpush(self, queue_name, value):
        self.queues.setdefault(queue_name, []).append(value)

    def blpop(self, queue_name):
        value = self.queues.setdefault(queue_name, []).pop(0)
        return queue_name, value

    def delete(self, key):
        self.values.pop(key, None)

    def lrem(self, queue_name, _count, value):
        queue = self.queues.setdefault(queue_name, [])
        self.queues[queue_name] = [item for item in queue if item != value]

    def scan_iter(self, pattern):
        prefix = pattern.rstrip("*")
        return (key for key in list(self.values) if key.startswith(prefix))


def test_submit_job_writes_minimal_job_and_enqueue(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(jobs_module, "get_redis", lambda: redis)

    response = TestClient(app).post("/jobs", json={"query": "Generate Chengdu NDVI"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "queued"
    job_id = payload["job_id"]
    assert redis.queues["raster_jobs"] == [job_id]
    job = json.loads(redis.values[job_key(job_id)])
    created_at = job.pop("created_at")
    assert isinstance(created_at, int)
    assert job == {
        "status": "queued",
        "query": "Generate Chengdu NDVI",
        "workspace_dir": "",
        "final_answer": "",
        "error": "",
    }


def test_read_job_returns_public_minimal_fields(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(jobs_module, "get_redis", lambda: redis)
    create_job(redis, "job-1", "query")
    update_job(redis, "job-1", status="succeeded", final_answer="done")

    response = TestClient(app).get("/jobs/job-1")

    assert response.status_code == 200
    assert response.json() == {
        "job_id": "job-1",
        "status": "succeeded",
        "final_answer": "done",
        "error": "",
    }


def test_artifact_requires_succeeded_job(monkeypatch):
    redis = FakeRedis()
    monkeypatch.setattr(jobs_module, "get_redis", lambda: redis)
    create_job(redis, "job-1", "query")

    response = TestClient(app).get("/jobs/job-1/metadata")

    assert response.status_code == 409


def test_artifact_returns_workspace_output_file(monkeypatch, tmp_path):
    redis = FakeRedis()
    monkeypatch.setattr(jobs_module, "get_redis", lambda: redis)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text('{"ok": true}', encoding="utf-8")
    create_job(redis, "job-1", "query")
    update_job(
        redis,
        "job-1",
        status="succeeded",
        workspace_dir=str(tmp_path),
    )

    response = TestClient(app).get("/jobs/job-1/metadata")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_worker_process_job_success(monkeypatch, tmp_path):
    redis = FakeRedis()
    create_job(redis, "job-1", "query")

    def fake_run_workflow(query):
        assert query == "query"
        return AgentState(
            user_query=query,
            workspace={"workspace_dir": str(tmp_path)},
            final_answer="done",
            status="completed",
        )

    monkeypatch.setattr(worker_module, "run_workflow", fake_run_workflow)

    worker_module.process_job(redis, "job-1")

    job = get_job(redis, "job-1")
    assert job is not None
    created_at = job.pop("created_at")
    assert isinstance(created_at, int)
    assert job == {
        "status": "succeeded",
        "query": "query",
        "workspace_dir": str(tmp_path),
        "final_answer": "done",
        "error": "",
    }


def test_worker_process_job_failure(monkeypatch):
    redis = FakeRedis()
    create_job(redis, "job-1", "query")

    def fake_run_workflow(query):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker_module, "run_workflow", fake_run_workflow)

    worker_module.process_job(redis, "job-1")

    job = get_job(redis, "job-1")
    assert job["status"] == "failed"
    assert job["error"] == "boom"


def test_worker_treats_complete_artifacts_as_succeeded(monkeypatch, tmp_path):
    redis = FakeRedis()
    create_job(redis, "job-1", "query")

    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "metadata.json").write_text(
        json.dumps(
            {
                "area": {"aoi_query": "Milan, Italy"},
                "product": {"name": "NDWI"},
                "source": {"data_source": "sentinel2"},
            }
        ),
        encoding="utf-8",
    )
    (output_dir / "preview.png").write_bytes(b"png")
    (output_dir / "result.tif").write_bytes(b"tif")

    def fake_run_workflow(query):
        assert query == "query"
        return AgentState(
            user_query=query,
            workspace={"workspace_dir": str(tmp_path)},
            final_answer="failed final answer",
            status="failed",
            errors=["Tool execution failed: The read operation timed out"],
        )

    monkeypatch.setattr(worker_module, "run_workflow", fake_run_workflow)

    worker_module.process_job(redis, "job-1")

    job = get_job(redis, "job-1")
    assert job["status"] == "succeeded"
    assert job["workspace_dir"] == str(tmp_path)
    assert job["error"] == ""
    assert "metadata.json" in job["final_answer"]
    assert "preview.png" in job["final_answer"]
    assert "result.tif" in job["final_answer"]


def test_cleanup_expired_jobs_deletes_job_and_workspace(tmp_path):
    redis = FakeRedis()
    create_job(redis, "job-1", "query")

    workspace_dir = tmp_path / "data" / "run-1"
    output_dir = workspace_dir / "output"
    output_dir.mkdir(parents=True)
    (output_dir / "metadata.json").write_text("{}", encoding="utf-8")

    update_job(
        redis,
        "job-1",
        created_at=0,
        status="succeeded",
        workspace_dir=str(workspace_dir),
    )

    old_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        worker_module.cleanup_expired_jobs(redis, ttl_seconds=1800, now=1801)
    finally:
        os.chdir(old_cwd)

    assert get_job(redis, "job-1") is None
    assert not workspace_dir.exists()
