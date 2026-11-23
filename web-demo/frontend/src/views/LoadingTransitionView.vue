<!-- 文件用途：播放生成过场，展示任务进度，并提供生成或素材加载失败后的操作。 -->
<script setup lang="ts">
import loadingDog from "@/assets/mastergo/loading-dog.png";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { createIdempotencyKey, submitGeneration } from "@/lib/api";
import {
  clearWaitingBatch,
  evaluateWaitingBatch,
  generationState,
  getWaitingJobs,
  markFirstRoundComplete,
  retryWaitingWallpaper,
  startWaitingBatch,
  trackJob,
} from "@/stores/generationStore";
import { findPetById, petState, upsertPet } from "@/stores/petStore";
import { guardParkedAction, setRoute, showToast, systemState } from "@/stores/systemStore";

const introRef = ref<HTMLVideoElement | null>(null);
const loopRef = ref<HTMLVideoElement | null>(null);

const phase = ref<"intro" | "loop">("intro");
const introPlayCount = ref(0);
const loopRound = ref(0);
const retrying = ref(false);

let introFallbackTimer: number | null = null;
let firstLoopTimer: number | null = null;
let lastLoopTime = 0;

const introUrl = computed(
  () => systemState.config?.transitions?.intro?.url || "/api/assets/transitions/intro-3s.mp4",
);
const loopUrl = computed(
  () => systemState.config?.transitions?.loop?.url || "/api/assets/transitions/chase-loop-7s.mp4",
);

const waitingJobs = computed(() => getWaitingJobs());
const waitingError = computed(() => generationState.waitingError);

function clearTimers() {
  if (introFallbackTimer !== null) {
    window.clearTimeout(introFallbackTimer);
    introFallbackTimer = null;
  }
  if (firstLoopTimer !== null) {
    window.clearTimeout(firstLoopTimer);
    firstLoopTimer = null;
  }
}

function enterChaseLoop() {
  if (phase.value === "loop" && loopRound.value >= 1) return;
  if (introFallbackTimer !== null) {
    window.clearTimeout(introFallbackTimer);
    introFallbackTimer = null;
  }
  phase.value = "loop";
  loopRound.value = 1;
  lastLoopTime = 0;

  if (introRef.value) {
    introRef.value.pause();
  }
  if (loopRef.value) {
    loopRef.value.currentTime = 0;
    loopRef.value.play().catch(() => undefined);
  }

  firstLoopTimer = window.setTimeout(() => {
    void onFirstLoopFinished();
  }, 7050);
}

async function onFirstLoopFinished() {
  if (firstLoopTimer !== null) {
    window.clearTimeout(firstLoopTimer);
    firstLoopTimer = null;
  }
  await markFirstRoundComplete();
}

function handleLoopTimeUpdate() {
  const el = loopRef.value;
  if (!el || phase.value !== "loop") return;
  const t = el.currentTime;
  if (lastLoopTime > 5.8 && t < 1.0) {
    loopRound.value += 1;
    void onFirstLoopFinished();
  }
  lastLoopTime = t;
}

function startIntroSequence() {
  clearTimers();
  phase.value = "intro";
  introPlayCount.value = 1;
  loopRound.value = 0;

  if (loopRef.value) {
    loopRef.value.pause();
    loopRef.value.currentTime = 0;
  }
  if (introRef.value) {
    introRef.value.currentTime = 0;
    introRef.value.play().catch(() => undefined);
  }

  introFallbackTimer = window.setTimeout(() => {
    enterChaseLoop();
  }, 3300);

  if (systemState.cutoutStrategy === "immediate") {
    void evaluateWaitingBatch();
  }
}

onMounted(() => {
  if (!waitingError.value) startIntroSequence();
});

watch(
  () => systemState.cutoutStrategy,
  (val) => {
    if (val === "immediate") {
      void evaluateWaitingBatch();
    }
  },
);

watch(() => systemState.alertVisible, (visible) => {
  if (!visible) void evaluateWaitingBatch();
});

watch(waitingError, (error) => {
  if (error) {
    clearTimers();
    introRef.value?.pause();
    loopRef.value?.pause();
  }
});

onBeforeUnmount(() => {
  clearTimers();
  introRef.value?.pause();
  loopRef.value?.pause();
});

function stageLabel(stage: string): string {
  const map: Record<string, string> = {
    queued: "排队中",
    idle: "生成正面待机图",
    left: "生成左热区动作",
    center: "生成中热区动作",
    right: "生成右热区动作",
    validating: "校验成品规格",
    ready: "已就绪",
    failed: "生成失败",
  };
  return map[stage] || stage;
}

function petNameOf(petId: string): string {
  return findPetById(petId)?.name || "宠物";
}

/** 重试加载已生成的成品，或用已存档照片重新提交失败的生成任务。 */
async function handleRetry() {
  if (retrying.value) return;
  const needsGeneration = waitingError.value?.kind === "generation";
  if (needsGeneration && !guardParkedAction("重试生成")) return;
  const routeRevision = systemState.routeRevision;
  retrying.value = true;
  try {
    if (!needsGeneration) {
      await retryWaitingWallpaper();
      return;
    }
    const newJobIds: string[] = [];
    for (const oldJob of waitingJobs.value) {
      const res = await submitGeneration({
        petId: oldJob.pet_id,
        idempotencyKey: createIdempotencyKey("retry"),
        mockDelaySeconds: systemState.config?.mock_controls_enabled ? 1.8 : undefined,
      });
      if (res.pet) upsertPet(res.pet);
      trackJob(res.job);
      newJobIds.push(res.job.id);
      if (systemState.routeRevision !== routeRevision) return;
    }
    startWaitingBatch(newJobIds);
    startIntroSequence();
  } catch (err) {
    if (systemState.routeRevision === routeRevision) {
      showToast(err instanceof Error ? err.message : "重试失败，请稍后再试", "error");
    }
  } finally {
    retrying.value = false;
  }
}

function handleReupload() {
  clearWaitingBatch();
  setRoute("onboarding-species");
}

function handleReturnHome() {
  clearWaitingBatch();
  setRoute(petState.savedWallpaper ? "home" : "welcome");
}
</script>

<template>
  <section
    class="transition-viewport"
    data-testid="loading-transition-view"
    :data-phase="phase"
    :data-intro-plays="introPlayCount"
    :data-loop-round="loopRound"
  >
    <div class="transition-canvas-16x9 mastergo-cloud-sky" data-testid="transition-canvas">
      <video
        ref="introRef"
        :src="introUrl"
        class="transition-video"
        :class="{ visible: phase === 'intro' }"
        muted
        playsinline
        preload="auto"
        data-testid="transition-intro-video"
        @ended="enterChaseLoop"
      />
      <video
        ref="loopRef"
        :src="loopUrl"
        class="transition-video"
        :class="{ visible: phase === 'loop' }"
        muted
        loop
        playsinline
        preload="auto"
        data-testid="transition-loop-video"
        @timeupdate="handleLoopTimeUpdate"
      />

      <!-- 过场期间画布热区全部屏蔽 -->
      <div class="transition-shield" data-testid="transition-hotzone-shield" />

      <div v-if="phase === 'loop' && !waitingError" class="waiting-art" aria-hidden="true">
        <img :src="loadingDog" alt="" />
      </div>

      <div v-if="!waitingError" class="phase-pill" data-testid="transition-phase-badge">
        <span class="pulse-dot" />
        <span v-if="phase === 'intro'">入场先导 · 3 秒</span>
        <span v-else>追逐等待循环 · 第 {{ loopRound }} 轮（7 秒循环）</span>
      </div>

      <!-- 进度条位置、厚度和渐变取自 MasterGo 屏 08（3:2998、3:3001）。 -->
      <div v-if="!waitingError" class="jobs-hud" data-testid="transition-jobs-hud">
        <div v-for="job in waitingJobs" :key="job.id" class="job-progress-row">
          <div class="job-label-line">
            <strong>{{ petNameOf(job.pet_id) }}</strong>
            <span>{{ stageLabel(job.stage) }}</span>
          </div>
          <div class="bar-and-pct">
            <div class="progress-track">
              <div
                class="progress-fill"
                :class="{ failed: job.status === 'failed' }"
                :style="{ width: `${Math.max(4, job.progress)}%` }"
              />
            </div>
            <span class="pct-text">{{ job.progress }}%</span>
          </div>
        </div>
      </div>

      <div v-if="waitingError" class="first-fail-backdrop" data-testid="first-failure-panel">
        <div class="first-fail-card">
          <h2>{{ waitingError.kind === 'assets' ? '暂时无法加载壁纸' : '暂时未能完成壁纸生成' }}</h2>
          <p class="fail-reason">
            {{ waitingError.message }}
          </p>
          <div class="fail-actions">
            <button
              class="btn btn-black"
              :disabled="retrying"
              data-testid="first-fail-retry-btn"
              @click="handleRetry"
            >
              {{ retrying ? "重试中..." : waitingError.kind === 'assets' ? '重新加载' : '使用原照片重试' }}
            </button>
            <button
              v-if="waitingError.kind === 'generation'"
              class="btn btn-soft"
              data-testid="first-fail-reupload-btn"
              @click="handleReupload"
            >
              重新上传照片
            </button>
            <button
              class="btn btn-soft"
              data-testid="first-fail-home-btn"
              @click="handleReturnHome"
            >
              返回首页
            </button>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.transition-viewport {
  position: relative;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #05080d;
}

.transition-canvas-16x9 {
  position: relative;
  width: min(100vw, calc(100vh * 16 / 9));
  aspect-ratio: 16 / 9;
  container-type: inline-size;
  background: var(--bg-sky);
  overflow: hidden;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.65);
}

.transition-video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  pointer-events: none;
  transition: opacity 0.14s linear;
}

.transition-video.visible {
  opacity: 1;
}

.transition-shield {
  position: absolute;
  inset: 0;
  z-index: 4;
}

.waiting-art {
  position: absolute;
  inset: 0;
  z-index: 5;
  background: rgb(0 0 0 / 60%);
  pointer-events: none;
}

/* MasterGo 屏 08 的位图填充使用了垂直翻转。 */
.waiting-art img {
  position: absolute;
  left: 50%;
  top: 21.6%;
  width: 11.5625%;
  transform: translateX(-50%) scaleY(-1);
}

.phase-pill {
  position: absolute;
  top: max(54px, 9%);
  left: 18px;
  z-index: 6;
  padding: 6px 14px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  color: #121628;
  background: rgba(255, 255, 255, 0.84);
  backdrop-filter: blur(12px);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  box-shadow: 0 6px 18px rgba(18, 28, 79, 0.15);
}

.pulse-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #38d115;
  box-shadow: 0 0 8px #38d115;
  animation: pulse 1.3s ease-in-out infinite;
}

@keyframes pulse {
  0%,
  100% {
    transform: scale(0.85);
    opacity: 0.7;
  }
  50% {
    transform: scale(1.2);
    opacity: 1;
  }
}

.jobs-hud {
  position: absolute;
  top: calc(53% - 1.7em);
  left: 50%;
  transform: translateX(-50%);
  z-index: 6;
  width: min(86%, max(212px, calc(19.531cqw + 52px)));
  color: #ffffff;
  filter: drop-shadow(0 1px 2px rgb(5 12 21 / 80%));
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.job-progress-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.job-label-line {
  display: flex;
  justify-content: space-between;
  font-size: 12.5px;
}

.job-label-line span {
  color: rgba(255, 255, 255, 0.82);
}

.bar-and-pct {
  display: flex;
  align-items: center;
  gap: 12px;
}

.progress-track {
  flex: 1;
  height: max(8px, 1.406cqw);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.2);
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 999px;
  background: linear-gradient(90deg, #38d115 0%, #d8fd68 80%);
  box-shadow: 0 0 12px rgba(216, 253, 104, 0.65);
  transition: width 0.28s ease;
}

.progress-fill.failed {
  background: #e24f4f;
  box-shadow: none;
}

.pct-text {
  min-width: 40px;
  text-align: right;
  font-size: 14px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.first-fail-backdrop {
  position: absolute;
  inset: 0;
  z-index: 12;
  background: rgba(18, 28, 48, 0.52);
  backdrop-filter: blur(8px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.first-fail-card {
  width: min(500px, 92%);
  border-radius: 28px;
  padding: 28px 32px;
  background: #f5f8fd;
  color: #121628;
  box-shadow: 0 24px 56px rgba(15, 28, 56, 0.28);
  text-align: center;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

.first-fail-card h2 {
  margin: 0;
  font-size: 22px;
}

.fail-reason {
  margin: 0;
  font-size: 14px;
  color: #536478;
  line-height: 1.6;
}

.fail-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
  margin-top: 6px;
}
</style>
