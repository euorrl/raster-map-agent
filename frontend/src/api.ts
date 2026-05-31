import type { JobCreateResponse, JobResponse } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL || "/api").replace(/\/$/, "");

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function createJob(query: string): Promise<JobCreateResponse> {
  const response = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ query }),
  });

  return readJson<JobCreateResponse>(response);
}

export async function getJob(jobId: string): Promise<JobResponse> {
  const response = await fetch(`${API_BASE}/jobs/${jobId}`);
  return readJson<JobResponse>(response);
}

export function getMetadataUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/metadata`;
}

export function getPreviewUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/preview`;
}

export function getResultUrl(jobId: string): string {
  return `${API_BASE}/jobs/${jobId}/result`;
}
