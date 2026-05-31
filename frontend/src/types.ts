export type JobStatus = "idle" | "queued" | "running" | "succeeded" | "failed";

export interface JobCreateResponse {
  job_id: string;
  status: JobStatus;
}

export interface JobResponse {
  job_id: string;
  status: JobStatus;
  final_answer: string;
  error: string;
}
