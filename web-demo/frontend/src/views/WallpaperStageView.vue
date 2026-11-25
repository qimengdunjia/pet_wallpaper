<!-- 文件用途：在等比画布播放宠物壁纸，管理热区、模式按钮与宠物弹层。 -->
<script setup lang="ts">
import wallpaperDog from "@/assets/mastergo/wallpaper-dog.png";
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { hotzoneLabel, resolveHotzone } from "@/lib/hotzone";
import { getPlayableVideoUrl, preloadVideoBlob } from "@/lib/preload";
import { findPetById } from "@/stores/petStore";
import {
  completeActionPlayback,
  openPetSelector,
  playerState,
  resetLocalView,
  triggerHotzone,
} from "@/stores/playerStore";
import { guardParkedAction, setRoute, showToast, systemState } from "@/stores/systemStore";
import { useClock } from "@/stores/useClock";
import type { HotzoneSlot } from "@/types";
import PetConfirmModal from "@/components/PetConfirmModal.vue";
import PetEditModal from "@/components/PetEditModal.vue";
import PetSelectorPanel from "@/components/PetSelectorPanel.vue";
import SeatKeyControl from "@/components/SeatKeyControl.vue";
import SeamlessLoopVideo from "@/components/SeamlessLoopVideo.vue";

type VideoWithRVFC = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: (now: number, metadata: unknown) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

const clockText = useClock();
const canvasRef = ref<HTMLElement | null>(null);
const videoRefs = ref<Partial<Record<HotzoneSlot, HTMLVideoElement>>>({});
const readyActionSlot = ref<HotzoneSlot | null>(null);
const fadingActionSlot = ref<HotzoneSlot | null>(null);
const actionSrcs = ref<Record<HotzoneSlot, string>>({ left: "", center: "", right: "" });
let actionSafetyTimer: number | null = null;
let idleResumeFallbackTimer: number | null = null;
let actionStartSeq = 0;

const currentPet = computed(() => findPetById(playerState.currentPetId));
const assets = computed(() => playerState.currentAssets);

const cacheState = ref<"loading" | "ready" | "failed">("loading");
const imageState = ref<"loading" | "ready" | "failed">("loading");
const offlineState = computed(() => imageState.value === "ready" ? cacheState.value : imageState.value);
const idleSrc = ref("");
let cacheAttempt = 0;

const isPlaying = computed(() => playerState.playbackState === "playing");
const isSwitching = computed(() => playerState.playbackState === "switching");
const isDriving = computed(() => systemState.drivingMode === "driving");

const idleVideoPlaying = computed(() => {
  if (!assets.value?.idle_video) return false;
  if (playerState.selectorOpen) return false;
  if (playerState.playbackState === "switching") return false;
  // 等新触发的动作视频渲染出首帧后，再暂停待机视频，避免切换瞬间露底。
  if (playerState.playbackState === "playing" && readyActionSlot.value !== null) {
    return false;
  }
  return true;
});

function setVideoRef(slot: HotzoneSlot, el: unknown) {
  if (el instanceof HTMLVideoElement) {
    videoRefs.value[slot] = el;
  } else {
    delete videoRefs.value[slot];
  }
}

function clearActionTimer() {
  if (actionSafetyTimer !== null) {
    window.clearTimeout(actionSafetyTimer);
    actionSafetyTimer = null;
  }
}

function clearIdleResumeFallback() {
  if (idleResumeFallbackTimer !== null) {
    window.clearTimeout(idleResumeFallbackTimer);
    idleResumeFallbackTimer = null;
  }
}

function resetSlotVideo(slot: HotzoneSlot) {
  const el = videoRefs.value[slot];
  if (!el) return;
  el.pause();
  if (el.currentTime > 0.01) {
    try {
      el.currentTime = 0;
    } catch {
      // noop
    }
  }
}

function stopAllVideos() {
  actionStartSeq += 1;
  clearActionTimer();
  clearIdleResumeFallback();
  readyActionSlot.value = null;
  fadingActionSlot.value = null;
  for (const slot of ["left", "center", "right"] as const) {
    resetSlotVideo(slot);
  }
}

/** 将当前壁纸的视频完整读入内存；retry 表示重新装载先前失败的媒体元素。 */
async function syncActionSources(retry = false) {
  const attempt = ++cacheAttempt;
  const current = assets.value;
  cacheState.value = "loading";
  if (!current) return;
  const idleUrl = current.idle_video?.url;
  if (!retry) idleSrc.value = idleUrl || "";
  const prepareAction = async (slot: HotzoneSlot) => {
    const url = current.actions[slot].url;
    if (!retry) actionSrcs.value[slot] = getPlayableVideoUrl(url);
    const src = await preloadVideoBlob(url);
    if (!src.startsWith("blob:")) throw new Error("浏览器无法缓存互动视频");
    if (attempt === cacheAttempt && playerState.activeAction !== slot && fadingActionSlot.value !== slot) {
      actionSrcs.value[slot] = src;
    }
  };
  try {
    const [idle] = await Promise.all([
      idleUrl ? preloadVideoBlob(idleUrl) : Promise.resolve(""),
      prepareAction("left"), prepareAction("center"), prepareAction("right"),
    ]);
    if (attempt !== cacheAttempt) return;
    if (idleUrl && !idle.startsWith("blob:")) throw new Error("浏览器无法缓存待机视频");
    if (retry && idle) idleSrc.value = idle;
    cacheState.value = "ready";
  } catch {
    if (attempt === cacheAttempt) cacheState.value = "failed";
  }
}

const imageAttempt = ref(0);
function retryMedia() {
  if (imageState.value === "failed") {
    imageState.value = "loading";
    imageAttempt.value++;
  }
  void syncActionSources(true);
}

function waitForVideoFirstFrame(videoEl: HTMLVideoElement, timeoutMs = 120): Promise<void> {
  return new Promise((resolve) => {
    const v = videoEl as VideoWithRVFC;
    let settled = false;
    let rvfcId: number | null = null;
    let rafId: number | null = null;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      v.removeEventListener("playing", onPlaying);
      if (rvfcId !== null && typeof v.cancelVideoFrameCallback === "function") {
        v.cancelVideoFrameCallback(rvfcId);
      }
      if (rafId !== null) {
        window.cancelAnimationFrame(rafId);
      }
      resolve();
    };
    const onPlaying = () => {
      rafId = window.requestAnimationFrame(finish);
    };
    const timer = window.setTimeout(finish, timeoutMs);

    if (typeof v.requestVideoFrameCallback === "function") {
      rvfcId = v.requestVideoFrameCallback(finish);
    } else if (!v.paused && v.readyState >= 2) {
      rafId = window.requestAnimationFrame(finish);
    } else {
      v.addEventListener("playing", onPlaying, { once: true });
    }
  });
}

function finalizeFadingAction() {
  clearIdleResumeFallback();
  const prevSlot = fadingActionSlot.value;
  if (!prevSlot) return;
  fadingActionSlot.value = null;
  resetSlotVideo(prevSlot);
  const rawUrl = assets.value?.actions[prevSlot]?.url;
  if (rawUrl) {
    const cached = getPlayableVideoUrl(rawUrl);
    if (cached.startsWith("blob:")) {
      actionSrcs.value[prevSlot] = cached;
    }
  }
}

function handleIdleFirstFrame() {
  if (fadingActionSlot.value !== null) {
    finalizeFadingAction();
  }
}

watch(
  () => playerState.playbackState,
  (state) => {
    if (state === "idle") {
      // 如果不是正常播完自然过渡（例如安全提醒打断），立刻停止所有动作视频
      if (fadingActionSlot.value === null) {
        stopAllVideos();
      }
    } else if (state === "switching") {
      stopAllVideos();
    }
  },
);

watch(
  [() => assets.value?.version_id, () => assets.value?.idle_video?.url],
  () => {
    stopAllVideos();
    imageState.value = "loading";
    void syncActionSources();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  cacheAttempt++;
  stopAllVideos();
});

function handleCanvasClick(event: MouseEvent) {
  const el = canvasRef.value;
  if (!el) return;
  const rect = el.getBoundingClientRect();
  const hit = resolveHotzone(event.clientX, event.clientY, rect);
  if (hit) playAction(hit.slot, hit.ratioX);
}

/** 播放 slot 对应的互动视频，用 ratioX 记录触发位置；播放器忙时忽略。 */
function playAction(slot: HotzoneSlot, ratioX: number) {
  const accepted = triggerHotzone(slot, ratioX);
  if (!accepted) return;

  finalizeFadingAction();
  const videoEl = videoRefs.value[slot];
  if (!videoEl) {
    completeActionPlayback();
    return;
  }

  // 当前段播放期间才下载完成的缓存，在下次启动这一段时再切换。
  const url = assets.value?.actions[slot].url;
  const cached = url && getPlayableVideoUrl(url);
  if (cached?.startsWith("blob:") && videoEl.src !== cached) {
    actionSrcs.value[slot] = cached;
    videoEl.src = cached;
  }
  const seq = ++actionStartSeq;
  clearActionTimer();
  readyActionSlot.value = null;
  if (videoEl.currentTime > 0.01) {
    try {
      videoEl.currentTime = 0;
    } catch {
      // noop
    }
  }
  const playPromise = videoEl.play();
  if (playPromise && typeof playPromise.then === "function") {
    playPromise
      .then(() => waitForVideoFirstFrame(videoEl, 120))
      .then(() => {
        if (seq === actionStartSeq && playerState.playbackState === "playing" && playerState.activeAction === slot) {
          readyActionSlot.value = slot;
        }
      })
      .catch(() => {
        if (seq === actionStartSeq) {
          completeActionPlayback();
        }
      });
  } else {
    readyActionSlot.value = slot;
  }

  const durationSec = assets.value?.actions[slot]?.duration ?? 4.5;
  const safetyMs = Math.max(6500, Math.ceil((durationSec + 2.5) * 1000));
  actionSafetyTimer = window.setTimeout(() => {
    finalizeFadingAction();
    completeActionPlayback();
  }, safetyMs);
}

/** 将设备手势映射到对应热区的中点；弹窗或抽屉打开时忽略输入。 */
function handleSeatKey(slot: HotzoneSlot) {
  if (!systemState.drawerOpen) playAction(slot, { left: 0.17, center: 0.5, right: 0.83 }[slot]);
}

function handleVideoEnded(slot: HotzoneSlot) {
  if (playerState.activeAction !== slot) return;
  clearActionTimer();
  readyActionSlot.value = null;

  if (assets.value?.idle_video) {
    // 保留动作末帧短暂遮罩，待机循环唤醒首帧绘制完成后立即无缝退场
    fadingActionSlot.value = slot;
    completeActionPlayback();
    clearIdleResumeFallback();
    idleResumeFallbackTimer = window.setTimeout(() => {
      finalizeFadingAction();
    }, 180);
  } else {
    resetSlotVideo(slot);
    completeActionPlayback();
  }
}

function handleBlackBarClick() {
  // 留黑区不触发任何画布动作
}

function handleOpenSelector() {
  if (!guardParkedAction("切换宠物")) return;
  openPetSelector();
}

function handleAddPet() {
  if (isPlaying.value) {
    showToast("动作播放期间暂停新增宠物，请稍候", "warning", 2200);
    return;
  }
  if (!guardParkedAction("新增宠物")) return;
  systemState.onboardingReturnRoute = "wallpaper";
  systemState.onboardingSpeciesMode = null;
  setRoute("onboarding-species");
}

function handleExitWallpaper() {
  resetLocalView();
  setRoute("home");
}
</script>

<template>
  <section
    class="wallpaper-viewport"
    data-testid="wallpaper-stage-view"
    @click="handleBlackBarClick"
  >
    <div
      ref="canvasRef"
      class="wallpaper-canvas-16x9 mastergo-cloud-sky"
      :data-playback-state="playerState.playbackState"
      :data-active-action="playerState.activeAction || ''"
      data-testid="wallpaper-canvas"
      @click.stop="handleCanvasClick"
    >
      <template v-if="assets">
        <img
          :key="assets.version_id + '-' + imageAttempt"
          :src="assets.idle_image.url"
          @load="imageState = 'ready'"
          @error="imageState = 'failed'"
          :alt="currentPet?.name || '宠物壁纸'"
          class="stage-media stage-idle"
          data-testid="wallpaper-idle-image"
        />

        <SeamlessLoopVideo
          v-if="assets.idle_video"
          :key="`${assets.version_id}-idle-video`"
          :src="idleSrc"
          :poster="assets.idle_image.url"
          :playing="idleVideoPlaying"
          class="stage-media stage-idle-video"
          test-id="wallpaper-idle-video"
          @first-frame="handleIdleFirstFrame"
        />

        <video
          v-for="slot in (['left', 'center', 'right'] as const)"
          :key="`${assets.version_id}-${slot}`"
          :ref="(el) => setVideoRef(slot, el)"
          :src="actionSrcs[slot]"
          class="stage-media stage-video"
          :class="{
            active:
              (isPlaying && playerState.activeAction === slot && readyActionSlot === slot) ||
              fadingActionSlot === slot,
          }"
          muted
          playsinline
          preload="auto"
          :data-testid="`wallpaper-video-${slot}`"
          @ended="handleVideoEnded(slot)"
        />
      </template>
      <div v-else class="wallpaper-placeholder" aria-hidden="true">
        <img :src="wallpaperDog" alt="" />
      </div>

      <!-- 悬浮时钟与宠物状态不拦截画布点击。 -->
      <div class="floating-stage-info">
        <div class="floating-clock" :class="{ dimmed: isPlaying }">{{ clockText }}</div>
        <div class="pet-pill-badge">
          <strong data-testid="current-pet-name">{{ currentPet?.name || "未命名宠物" }}</strong>
          <span class="species-chip">
            {{ currentPet?.species === "dog" ? "狗狗模式" : "猫咪模式" }}
          </span>
          <span v-if="isDriving" class="state-chip warning" data-testid="driving-status-pill">
            行驶中 · 互动锁定
          </span>
          <span
            v-else-if="isPlaying && playerState.activeAction"
            class="state-chip success"
            data-testid="playing-status-pill"
          >
            播放中：{{ hotzoneLabel(playerState.activeAction) }}
          </span>
          <span v-else class="state-chip" data-testid="idle-status-pill">
            待机中 · 点击画面互动
          </span>
        </div>
      </div>

      <!-- 可选热区辅助边界线 -->
      <div v-if="systemState.showHotzoneGuides" class="hotzone-guides" data-testid="hotzone-guides">
        <div class="zone-box zone-left">
          <span>左热区 (0–34%)</span>
        </div>
        <div class="zone-box zone-center">
          <span>中热区 (34–66%)</span>
        </div>
        <div class="zone-box zone-right">
          <span>右热区 (66–100%)</span>
        </div>
      </div>

      <div v-if="isSwitching" class="switching-banner" data-testid="switching-banner">
        正在校验并切换壁纸...
      </div>

      <!-- 按钮尺寸和间距取自 MasterGo 屏 09（3:2720、3:2729、3:2730）。 -->
      <div class="mode-controls-bar" data-testid="mode-controls-bar" @click.stop>
        <div class="mode-left-group">
          <button
            class="btn mode-glass-btn"
            :disabled="isPlaying || isSwitching || isDriving"
            data-testid="switch-pet-btn"
            @click="handleOpenSelector"
          >
            <span>切换宠物</span>
          </button>
          <button
            class="btn mode-glass-btn"
            :disabled="isPlaying || isSwitching || isDriving"
            data-testid="add-pet-btn"
            @click="handleAddPet"
          >
            <span>新增宠物</span>
          </button>
          <SeatKeyControl
            v-if="systemState.config?.seat_key_url"
            :url="systemState.config.seat_key_url"
            :offline-state="offlineState"
            @retry-media="retryMedia"
            @action="handleSeatKey"
          />
        </div>

        <button
          class="btn btn-black mode-exit-btn"
          data-testid="exit-wallpaper-btn"
          @click="handleExitWallpaper"
        >
          退出壁纸
        </button>
      </div>
    </div>

    <PetSelectorPanel />
    <PetConfirmModal />
    <PetEditModal />
  </section>
</template>

<style scoped>
.wallpaper-viewport {
  position: relative;
  width: 100vw;
  height: 100vh;
  background: #04060a;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}

.wallpaper-canvas-16x9 {
  position: relative;
  width: min(100vw, calc(100vh * 16 / 9));
  aspect-ratio: 16 / 9;
  container-type: inline-size;
  background: var(--bg-sky);
  overflow: hidden;
  cursor: pointer;
  box-shadow: 0 22px 72px rgba(0, 0, 0, 0.78);
}

.wallpaper-placeholder {
  position: absolute;
  inset: 74.861% 0 0;
  background: var(--bg-meadow-floor);
  pointer-events: none;
}

.wallpaper-placeholder img {
  position: absolute;
  left: 42.89%;
  bottom: 0;
  width: 35.625%;
}

.stage-media {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;
}

.stage-idle {
  z-index: 1;
}

.stage-idle-video {
  z-index: 2;
}

.stage-video {
  z-index: 3;
  opacity: 0;
}

.stage-video.active {
  opacity: 1;
}

.floating-stage-info {
  position: absolute;
  top: max(58px, 10%);
  left: 28px;
  z-index: 7;
  pointer-events: none;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.floating-clock {
  font-size: 56px;
  font-weight: 700;
  line-height: 1;
  letter-spacing: -0.02em;
  background: linear-gradient(180deg, rgba(162, 206, 255, 0.92) 10%, rgba(102, 178, 255, 0.42) 100%);
  -webkit-background-clip: text;
  background-clip: text;
  color: transparent;
  filter: drop-shadow(0 6px 18px rgba(0, 0, 0, 0.25));
  transition: opacity 0.22s ease;
}

.floating-clock.dimmed {
  opacity: 0.35;
}

.pet-pill-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 14px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(14px);
  -webkit-backdrop-filter: blur(14px);
  border: 1px solid rgba(255, 255, 255, 0.9);
  color: #121628;
  font-size: 13px;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.18);
}

.species-chip {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(73, 129, 242, 0.14);
  color: #2563eb;
}

.state-chip {
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(18, 22, 40, 0.08);
  color: #536478;
}

.state-chip.success {
  background: #ddfd66;
  color: #121628;
}

.state-chip.warning {
  background: #f59e0b;
  color: #121628;
}

.hotzone-guides {
  position: absolute;
  inset: 0;
  z-index: 8;
  display: flex;
  pointer-events: none;
}

.zone-box {
  height: 100%;
  border-right: 1.5px dashed rgba(255, 255, 255, 0.6);
  background: rgba(102, 178, 255, 0.1);
  display: flex;
  align-items: flex-start;
  justify-content: center;
  padding-top: 56px;
}

.zone-box:last-child {
  border-right: none;
}

.zone-left {
  width: 34%;
}

.zone-center {
  width: 32%;
  background: rgba(221, 253, 102, 0.12);
}

.zone-right {
  width: 34%;
}

.zone-box span {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.88);
  color: #121628;
}

.switching-banner {
  position: absolute;
  top: 56px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 14;
  padding: 8px 18px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.9);
  color: #121628;
}

.mode-controls-bar {
  position: absolute;
  bottom: max(48px, 12.222%);
  inset-inline: 5.078%;
  z-index: 25;
  display: flex;
  align-items: center;
  justify-content: space-between;
  pointer-events: none;
  cursor: default;
}

.mode-left-group {
  display: flex;
  align-items: center;
  gap: 2.344cqw;
}

.mode-controls-bar button {
  width: max(84px, 16.406cqw);
  height: max(36px, 4.688cqw);
  padding: 0 4px;
  pointer-events: auto;
  font-size: clamp(11px, 1.45cqw, 36px);
  white-space: nowrap;
}

.mode-glass-btn {
  background: rgba(255, 255, 255, 0.4);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: none;
  color: #121628;
  box-shadow: inset -2px -2px 10px rgba(255, 255, 255, 0.3),
    inset 2px 0 10px rgba(255, 255, 255, 0.3);
}

.mode-glass-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.95);
}

.mode-glass-btn:disabled {
  opacity: 0.45;
}

</style>
