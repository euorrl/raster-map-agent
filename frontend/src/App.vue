<template>
  <main class="page-shell">
    <section class="workspace">
      <header class="topbar">
        <div>
          <h1>Raster Map Agent</h1>
        </div>
        <a class="health-link" href="/api/health" target="_blank" rel="noreferrer">
          API Health
        </a>
      </header>

      <form class="query-panel" @submit.prevent="submit">
        <label for="query">自然语言请求</label>
        <textarea
          id="query"
          v-model="query"
          :disabled="isBusy"
          rows="4"
          placeholder="我想看看米兰的植被情况"
        />
        <div class="form-actions">
          <button class="primary-button" type="submit" :disabled="!canSubmit">
            <Send :size="18" aria-hidden="true" />
            {{ isBusy ? "任务运行中" : "生成地图" }}
          </button>
        </div>
      </form>

      <section v-if="jobId || status !== 'idle'" class="status-panel">
        <div class="status-heading">
          <div>
            <p class="section-label">任务状态</p>
            <h2>{{ statusTitle }}</h2>
          </div>
          <span class="status-pill" :class="status">{{ status }}</span>
        </div>

        <div v-if="isBusy" class="progress-line" aria-hidden="true">
          <span />
        </div>

        <dl class="job-meta">
          <div v-if="jobId" class="job-id">
            <dt>任务 ID</dt>
            <div class="job-id-row">
              <dd>{{ jobId }}</dd>
              <button
                class="icon-button"
                type="button"
                title="复制任务 ID"
                @click="copyJobId"
              >
                <Copy :size="18" aria-hidden="true" />
              </button>
            </div>
          </div>
          <div>
            <dt>已用时</dt>
            <dd>{{ elapsedText }}</dd>
          </div>
        </dl>

        <p class="status-message">{{ statusMessage }}</p>
        <p v-if="isBusy" class="muted">
          任务已在后端运行，刷新页面不会终止任务。
        </p>
        <p v-if="status === 'succeeded'" class="muted">
          结果默认保留约 30 分钟，请及时下载。
        </p>
      </section>

      <section v-if="status === 'succeeded' && jobId" class="result-layout">
        <div class="preview-panel">
          <div class="panel-title">
            <h2>预览图</h2>
            <a class="text-button" :href="previewUrl" download="preview.png">
              <Download :size="18" aria-hidden="true" />
              下载 PNG
            </a>
          </div>
          <img :src="previewUrl" alt="生成的栅格产品预览图" />
        </div>

        <aside class="download-panel">
          <h2>结果文件</h2>
          <a :href="previewUrl" download="preview.png">
            <ImageDown :size="18" aria-hidden="true" />
            preview.png
          </a>
          <a :href="metadataUrl" download="metadata.json">
            <FileJson :size="18" aria-hidden="true" />
            metadata.json
          </a>
          <a :href="resultUrl" download="result.tif">
            <FileDown :size="18" aria-hidden="true" />
            result.tif
          </a>
        </aside>
      </section>

      <section v-if="finalAnswer" class="answer-panel">
        <h2>最终回答</h2>
        <p>{{ finalAnswer }}</p>
      </section>

      <section v-if="status === 'failed'" class="error-panel">
        <h2>任务未能完成</h2>
        <p>{{ errorText }}</p>
        <ul>
          <li>尝试缩小区域范围。</li>
          <li>放宽时间范围或换一个月份。</li>
          <li>优先使用城市级别区域。</li>
        </ul>
      </section>
    </section>
  </main>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import {
  Copy,
  Download,
  FileDown,
  FileJson,
  ImageDown,
  Send,
} from "lucide-vue-next";
import {
  createJob,
  getJob,
  getMetadataUrl,
  getPreviewUrl,
  getResultUrl,
} from "./api";
import type { JobStatus } from "./types";

const query = ref("");
const jobId = ref(localStorage.getItem("raster-map-agent:last-job-id") || "");
const status = ref<JobStatus>(jobId.value ? "queued" : "idle");
const finalAnswer = ref("");
const errorText = ref("");
const startedAt = ref<number | null>(jobId.value ? Date.now() : null);
const elapsedSeconds = ref(0);
const submitError = ref("");

let pollTimer: number | undefined;
let clockTimer: number | undefined;

const isBusy = computed(() => status.value === "queued" || status.value === "running");
const canSubmit = computed(() => query.value.trim().length > 0 && !isBusy.value);
const previewUrl = computed(() => (jobId.value ? getPreviewUrl(jobId.value) : ""));
const metadataUrl = computed(() => (jobId.value ? getMetadataUrl(jobId.value) : ""));
const resultUrl = computed(() => (jobId.value ? getResultUrl(jobId.value) : ""));

const statusTitle = computed(() => {
  if (status.value === "queued") return "任务已提交";
  if (status.value === "running") return "正在生成遥感产品";
  if (status.value === "succeeded") return "生成完成";
  if (status.value === "failed") return "任务失败";
  return "等待输入";
});

const elapsedText = computed(() => {
  const minutes = Math.floor(elapsedSeconds.value / 60).toString().padStart(2, "0");
  const seconds = (elapsedSeconds.value % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
});

const statusMessage = computed(() => {
  if (submitError.value) return submitError.value;
  if (status.value === "queued") {
    return "请求已进入队列，正在等待空闲 worker。";
  }
  if (status.value === "running") {
    if (elapsedSeconds.value < 30) return "系统正在解析请求并查询可用 Sentinel-2 影像。";
    if (elapsedSeconds.value < 120) return "系统正在下载影像、裁剪 AOI 并准备指数计算。";
    if (elapsedSeconds.value < 240) return "系统正在处理栅格数据和渲染预览图，请继续等待。";
    return "任务仍在运行。较大的区域需要更长时间。";
  }
  if (status.value === "succeeded") {
    return "预览图和结果文件已可下载。";
  }
  if (status.value === "failed") {
    return "后端返回失败状态，请查看下方错误信息和调整建议。";
  }
  return "输入一个地点、时间和指数产品，开始生成地图。";
});

async function submit() {
  if (!canSubmit.value) return;

  resetCurrentJob();
  status.value = "queued";
  startedAt.value = Date.now();
  startClock();

  try {
    const response = await createJob(query.value.trim());
    jobId.value = response.job_id;
    status.value = response.status;
    localStorage.setItem("raster-map-agent:last-job-id", response.job_id);
    startPolling();
  } catch (error) {
    status.value = "failed";
    submitError.value = error instanceof Error ? error.message : "创建任务失败。";
    errorText.value = submitError.value;
    stopClock();
  }
}

function startPolling() {
  stopPolling();
  void pollJob();
  pollTimer = window.setInterval(() => {
    void pollJob();
  }, 5000);
}

async function pollJob() {
  if (!jobId.value) return;

  try {
    const job = await getJob(jobId.value);
    status.value = job.status;
    finalAnswer.value = job.final_answer || "";
    errorText.value = job.error || "";

    if (job.status === "succeeded" || job.status === "failed") {
      stopPolling();
      stopClock();
    }
  } catch (error) {
    status.value = "failed";
    errorText.value = error instanceof Error ? error.message : "查询任务失败。";
    stopPolling();
    stopClock();
  }
}

async function copyJobId() {
  if (!jobId.value) return;
  await navigator.clipboard.writeText(jobId.value);
}

function resetCurrentJob() {
  stopPolling();
  stopClock();
  jobId.value = "";
  finalAnswer.value = "";
  errorText.value = "";
  submitError.value = "";
  elapsedSeconds.value = 0;
}

function startClock() {
  stopClock();
  clockTimer = window.setInterval(() => {
    if (!startedAt.value) return;
    elapsedSeconds.value = Math.floor((Date.now() - startedAt.value) / 1000);
  }, 1000);
}

function stopPolling() {
  if (pollTimer !== undefined) window.clearInterval(pollTimer);
  pollTimer = undefined;
}

function stopClock() {
  if (clockTimer !== undefined) window.clearInterval(clockTimer);
  clockTimer = undefined;
}

if (jobId.value) {
  startClock();
  startPolling();
}

onBeforeUnmount(() => {
  stopPolling();
  stopClock();
});
</script>
