from fastapi import FastAPI

from backend.jobs import router as jobs_router

app = FastAPI(title="Raster Map Agent Backend")
app.include_router(jobs_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
