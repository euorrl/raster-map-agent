from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend.redis_client import create_job, get_job, get_redis

router = APIRouter()


class JobCreateRequest(BaseModel):
    query: str = Field(min_length=1)


class JobCreateResponse(BaseModel):
    job_id: str
    status: str


class JobResponse(BaseModel):
    job_id: str
    status: str
    stage: str = ""
    message: str = ""
    final_answer: str = ""
    error: str = ""


@router.post("/jobs", response_model=JobCreateResponse)
def submit_job(request: JobCreateRequest) -> JobCreateResponse:
    job_id = uuid4().hex
    create_job(get_redis(), job_id, request.query.strip())
    return JobCreateResponse(job_id=job_id, status="queued")


@router.get("/jobs/{job_id}", response_model=JobResponse)
def read_job(job_id: str) -> JobResponse:
    job = _require_job(job_id)
    return JobResponse(
        job_id=job_id,
        status=str(job.get("status", "")),
        stage=str(job.get("stage", "")),
        message=str(job.get("message", "")),
        final_answer=str(job.get("final_answer", "")),
        error=str(job.get("error", "")),
    )


@router.get("/jobs/{job_id}/metadata")
def read_metadata(job_id: str) -> FileResponse:
    return _artifact_response(job_id, "metadata.json", "application/json")


@router.get("/jobs/{job_id}/preview")
def read_preview(job_id: str) -> FileResponse:
    return _artifact_response(job_id, "preview.png", "image/png")


@router.get("/jobs/{job_id}/result")
def read_result(job_id: str) -> FileResponse:
    return _artifact_response(job_id, "result.tif", "image/tiff")


def _artifact_response(job_id: str, filename: str, media_type: str) -> FileResponse:
    job = _require_job(job_id)
    if job.get("status") != "succeeded":
        raise HTTPException(status_code=409, detail="job is not succeeded")

    workspace_dir = str(job.get("workspace_dir", ""))
    if not workspace_dir:
        raise HTTPException(status_code=404, detail="job has no workspace output")

    path = Path(workspace_dir) / "output" / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail=f"missing artifact: {filename}")

    return FileResponse(path, media_type=media_type, filename=filename)


def _require_job(job_id: str) -> dict:
    job = get_job(get_redis(), job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job
