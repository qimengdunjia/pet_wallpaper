<!-- 文件用途：播放生成过场，展示任务进度，并提供生成或素材加载失败后的操作。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { createIdempotencyKey, submitGeneration } from "@/lib/api";
import { getPlayableVideoUrl, preloadVideoBlob } from "@/lib/preload";
import SeamlessLoopVideo from "@/components/SeamlessLoopVideo.vue";
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

type VideoWithRVFC = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: (now: number, metadata: unknown) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

const introRef = ref<HTMLVideoElement | null>(null);
const introSrc = ref("");

const phase = ref<"intro" | "loop">("intro");
const loopPlaying = ref(false);
const introPlayCount = ref(0);
const loopRound = ref(0);
const retrying = ref(false);

let introFallbackTimer: number | null = null;
let firstLoopTimer: number | null = null;
let introRevealFallbackTimer: number | null = null;
let introMonitor: { kind: "rvfc" | "raf"; id: number; el: VideoWithRVFC } | null = null;
let enteringLoop = false;

const introUrl = computed(
  () => systemState.config?.transitions?.intro?.url || "/api/assets/transitions/intro-3s.mp4",
);
const loopUrl = computed(
  () => systemState.config?.transitions?.loop?.url || "/api/assets/transitions/chase-loop-7s.mp4",
);

const waitingJobs = computed(() => getWaitingJobs());
const waitingError = computed(() => generationState.waitingError);

function clearIntroMonitor() {
  if (!introMonitor) return;
  if (introMonitor.kind === "rvfc" && typeof introMonitor.el.cancelVideoFrameCallback === "function") {
    introMonitor.el.cancelVideoFrameCallback(introMonitor.id);
  } else if (introMonitor.kind === "raf") {
    window.cancelAnimationFrame(introMonitor.id);
  }
  introMonitor = null;
}

function clearTimers() {
  clearIntroMonitor();
  if (introFallbackTimer !== null) {
    window.clearTimeout(introFallbackTimer);
    introFallbackTimer = null;
  }
  if (firstLoopTimer !== null) {
    window.clearTimeout(firstLoopTimer);
    firstLoopTimer = null;
  }
  if (introRevealFallbackTimer !== null) {
    window.clearTimeout(introRevealFallbackTimer);
    introRevealFallbackTimer = null;
  }
}

function finishIntroReveal() {
  if (introRevealFallbackTimer !== null) {
    window.clearTimeout(introRevealFallbackTimer);
    introRevealFallbackTimer = null;
  }
  if (phase.value === "loop") return;
  phase.value = "loop";
  if (introRef.value) {
    introRef.value.pause();
  }
}

function scheduleIntroMonitor() {
  clearIntroMonitor();
  const el = introRef.value as VideoWithRVFC | null;
  if (!el || phase.value !== "intro" || enteringLoop) return;

  const checkFrame = () => {
    introMonitor = null;
    if (phase.value !== "intro" || enteringLoop) return;
    const dur = el.duration;
    if (Number.isFinite(dur) && dur > 0.2 && dur - el.currentTime <= 0.055) {
      enterChaseLoop();
      return;
    }
    scheduleIntroMonitor();
  };

  if (typeof el.requestVideoFrameCallback === "function") {
    const id = el.requestVideoFrameCallback(checkFrame);
    introMonitor = { kind: "rvfc", id, el };
  } else {
    const id = window.requestAnimationFrame(checkFrame);
    introMonitor = { kind: "raf", id, el };
  }
}

function enterChaseLoop() {
  if ((phase.value === "loop" && loopRound.value >= 1) || enteringLoop) return;
  enteringLoop = true;
  clearIntroMonitor();
  if (introFallbackTimer !== null) {
    window.clearTimeout(introFallbackTimer);
    introFallbackTimer = null;
  }
  loopRound.value = 1;
  loopPlaying.value = true;

  // 等追逐循环层首帧渲染完成再隐藏先导视频，避免切换瞬间露底或闪烁
  introRevealFallbackTimer = window.setTimeout(() => {
    finishIntroReveal();
  }, 150);

  firstLoopTimer = window.setTimeout(() => {
    void onFirstLoopFinished();
  }, 7300);
}

async function onFirstLoopFinished() {
  if (firstLoopTimer !== null) {
    window.clearTimeout(firstLoopTimer);
    firstLoopTimer = null;
  }
  await markFirstRoundComplete();
}

function handleLoopFirstFrame() {
  if (enteringLoop) {
    finishIntroReveal();
  }
}

function handleLoopRound() {
  if (phase.value !== "loop" && !enteringLoop) return;
  loopRound.value += 1;
  void onFirstLoopFinished();
}

function startIntroSequence() {
  clearTimers();
  enteringLoop = false;
  phase.value = "intro";
  loopPlaying.value = false;
  introPlayCount.value = 1;
  loopRound.value = 0;

  introSrc.value = getPlayableVideoUrl(introUrl.value);
  void preloadVideoBlob(loopUrl.value).catch(() => undefined);
  if (!introSrc.value.startsWith("blob:")) {
    void preloadVideoBlob(introUrl.value).catch(() => undefined);
  }

  if (introRef.value) {
    introRef.value.currentTime = 0;
    introRef.value.play().catch(() => undefined);
    scheduleIntroMonitor();
  }

  introFallbackTimer = window.setTimeout(() => {
    enterChaseLoop();
  }, 3500);

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
    loopPlaying.value = false;
    introRef.value?.pause();
  }
});

onBeforeUnmount(() => {
  clearTimers();
  loopPlaying.value = false;
  introRef.value?.pause();
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
        :src="introSrc || introUrl"
        class="transition-video"
        :class="{ visible: phase === 'intro' }"
        muted
        playsinline
        preload="auto"
        data-testid="transition-intro-video"
        @ended="enterChaseLoop"
      />
      <SeamlessLoopVideo
        :src="loopUrl"
        :playing="loopPlaying"
        class="transition-video"
        :class="{ visible: phase === 'loop' }"
        test-id="transition-loop-video"
        @first-frame="handleLoopFirstFrame"
        @loop-round="handleLoopRound"
      />

      <!-- 过场期间画布热区全部屏蔽 -->
      <div class="transition-shield" data-testid="transition-hotzone-shield" />

      <div v-if="!waitingError" class="phase-pill" data-testid="transition-phase-badge">
        <span class="pulse-dot" />
        <span v-if="phase === 'intro'">入场先导 · 3 秒</span>
        <span v-else>追逐等待循环 · 第 {{ loopRound }} 轮（7 秒循环）</span>
      </div>

      <!-- 底部悬浮进度卡片：避免遮挡画布中央的猫狗奔跑动画 -->
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
  z-index: 1;
  width: 100%;
  height: 100%;
  object-fit: cover;
  opacity: 0;
  pointer-events: none;
}

.transition-video.visible {
  z-index: 2;
  opacity: 1;
}

.transition-shield {
  position: absolute;
  inset: 0;
  z-index: 4;
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
  bottom: max(56px, 10%);
  left: 50%;
  transform: translateX(-50%);
  z-index: 6;
  width: min(500px, 86%);
  padding: 12px 20px;
  border-radius: 22px;
  background: rgba(18, 26, 44, 0.56);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.25);
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
