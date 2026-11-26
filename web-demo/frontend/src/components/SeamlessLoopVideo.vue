<!-- 文件用途：双缓冲交替循环视频组件，利用预解码备播层消除原生 loop 回跳卡顿。 -->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { getPlayableVideoUrl, preloadVideoBlob } from "@/lib/preload";

type VideoWithRVFC = HTMLVideoElement & {
  requestVideoFrameCallback?: (callback: (now: number, metadata: unknown) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

const props = withDefaults(
  defineProps<{
    src: string;
    poster?: string;
    playing?: boolean;
    resetOnPause?: boolean;
    usePreparedFrame?: boolean; // 等待过场在段尾直接露出已解码的下一段首帧。
    testId?: string;
  }>(),
  {
    poster: undefined,
    playing: true,
    resetOnPause: true,
    usePreparedFrame: false,
    testId: undefined,
  },
);

const emit = defineEmits<{
  loopRound: [];
  firstFrame: [];
}>();

const activeIdx = ref<0 | 1>(0);
const bufferSrcs = ref<[string, string]>([getPlayableVideoUrl(props.src), getPlayableVideoUrl(props.src)]);

const bufferRefs: [VideoWithRVFC | null, VideoWithRVFC | null] = [null, null];

let disposed = false;
let playbackSeq = 0;
let handoffInFlight = false;
let monitorHandle: { kind: "rvfc" | "raf"; id: number; el: VideoWithRVFC } | null = null;
let latestBlobSrc: string | null = bufferSrcs.value[0].startsWith("blob:") ? bufferSrcs.value[0] : null;

function setBufferRef(idx: 0 | 1, el: unknown) {
  bufferRefs[idx] = el instanceof HTMLVideoElement ? (el as VideoWithRVFC) : null;
}

function clearMonitor() {
  if (!monitorHandle) return;
  if (monitorHandle.kind === "rvfc" && typeof monitorHandle.el.cancelVideoFrameCallback === "function") {
    monitorHandle.el.cancelVideoFrameCallback(monitorHandle.id);
  } else if (monitorHandle.kind === "raf") {
    window.cancelAnimationFrame(monitorHandle.id);
  }
  monitorHandle = null;
}

function waitForNextPaintedFrame(el: VideoWithRVFC, timeoutMs = 120): Promise<void> {
  return new Promise((resolve) => {
    let settled = false;
    let rvfcId: number | null = null;
    let rafId: number | null = null;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      el.removeEventListener("playing", onPlaying);
      if (rvfcId !== null && typeof el.cancelVideoFrameCallback === "function") {
        el.cancelVideoFrameCallback(rvfcId);
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

    if (typeof el.requestVideoFrameCallback === "function") {
      rvfcId = el.requestVideoFrameCallback(finish);
    } else if (!el.paused && el.readyState >= 2) {
      rafId = window.requestAnimationFrame(finish);
    } else {
      el.addEventListener("playing", onPlaying, { once: true });
    }
  });
}

function resetStandbyBuffer(idx: 0 | 1) {
  const el = bufferRefs[idx];
  if (!el) return;
  el.pause();
  if (el.currentTime > 0.01) {
    try {
      el.currentTime = 0;
    } catch {
      // 忽略尚未完成元数据解析时的寻道异常
    }
  }
  if (latestBlobSrc && bufferSrcs.value[idx] !== latestBlobSrc) {
    bufferSrcs.value[idx] = latestBlobSrc;
  }
}

function hasPreparedFirstFrame(el: HTMLVideoElement | null): el is HTMLVideoElement {
  return Boolean(el && el.readyState >= 2 && !el.seeking && el.currentTime < 0.02);
}

function scheduleMonitor() {
  clearMonitor();
  if (disposed || !props.playing || handoffInFlight) return;
  const el = bufferRefs[activeIdx.value];
  if (!el) return;

  const checkFrame = () => {
    monitorHandle = null;
    if (disposed || !props.playing || handoffInFlight) return;
    if (bufferRefs[activeIdx.value] !== el) return;

    const dur = el.duration;
    const standby = bufferRefs[activeIdx.value === 0 ? 1 : 0];
    const remaining = dur - el.currentTime;
    const handoff = props.usePreparedFrame
      ? remaining <= 0.018 && hasPreparedFirstFrame(standby)
      : remaining <= 0.055;
    if (Number.isFinite(dur) && dur > 0.2 && handoff) {
      void performHandoff();
      return;
    }
    scheduleMonitor();
  };

  // 显示刷新能覆盖最后一帧的在屏时间，媒体帧回调只在新帧出现时触发。
  if (!props.usePreparedFrame && typeof el.requestVideoFrameCallback === "function") {
    const id = el.requestVideoFrameCallback(checkFrame);
    monitorHandle = { kind: "rvfc", id, el };
  } else {
    const id = window.requestAnimationFrame(checkFrame);
    monitorHandle = { kind: "raf", id, el };
  }
}

async function performHandoff() {
  if (disposed || !props.playing || handoffInFlight) return;
  handoffInFlight = true;
  clearMonitor();
  const seq = playbackSeq;

  const prevIdx = activeIdx.value;
  const nextIdx: 0 | 1 = prevIdx === 0 ? 1 : 0;
  const prevEl = bufferRefs[prevIdx];
  const nextEl = bufferRefs[nextIdx];

  if (!nextEl || nextEl.readyState < 2) {
    // 备播层尚未就绪时退化为单层原地重播
    if (prevEl) {
      try {
        prevEl.currentTime = 0;
      } catch {
        // noop
      }
      void prevEl.play().catch(() => undefined);
    }
    handoffInFlight = false;
    if (!disposed && seq === playbackSeq) {
      emit("loopRound");
      scheduleMonitor();
    }
    return;
  }

  if (nextEl.currentTime > 0.02) {
    try {
      nextEl.currentTime = 0;
    } catch {
      // noop
    }
  }

  const showPreparedFrame = props.usePreparedFrame && hasPreparedFirstFrame(nextEl);
  if (!showPreparedFrame) {
    await nextEl.play().catch(() => undefined);
    await waitForNextPaintedFrame(nextEl, 100);
  }
  if (disposed || seq !== playbackSeq || !props.playing) return;

  activeIdx.value = nextIdx;
  if (showPreparedFrame) {
    void nextEl.play().catch(() => undefined);
  }
  if (prevEl) {
    resetStandbyBuffer(prevIdx);
  }
  handoffInFlight = false;
  emit("loopRound");
  scheduleMonitor();
}

async function startPlayback() {
  const seq = ++playbackSeq;
  handoffInFlight = false;
  clearMonitor();

  const el = bufferRefs[activeIdx.value];
  const standbyIdx: 0 | 1 = activeIdx.value === 0 ? 1 : 0;
  resetStandbyBuffer(standbyIdx);

  if (!el) return;
  if (latestBlobSrc && bufferSrcs.value[activeIdx.value] !== latestBlobSrc && el.paused) {
    bufferSrcs.value[activeIdx.value] = latestBlobSrc;
    await nextTick();
  }
  if (disposed || seq !== playbackSeq || !props.playing) return;

  // 首帧已解码时直接显示，避免等待下一个绘制回调跳过这帧。
  if (props.usePreparedFrame && hasPreparedFirstFrame(el)) {
    emit("firstFrame");
    void el.play().catch(() => undefined);
    scheduleMonitor();
    return;
  }
  await el.play().catch(() => undefined);
  await waitForNextPaintedFrame(el, 120);
  if (disposed || seq !== playbackSeq || !props.playing) return;
  emit("firstFrame");
  scheduleMonitor();
}

function stopPlayback() {
  playbackSeq += 1;
  handoffInFlight = false;
  clearMonitor();
  for (const idx of [0, 1] as const) {
    const el = bufferRefs[idx];
    if (!el) continue;
    el.pause();
    if (props.resetOnPause && el.currentTime > 0.01) {
      try {
        el.currentTime = 0;
      } catch {
        // noop
      }
    }
  }
  if (latestBlobSrc) {
    bufferSrcs.value = [latestBlobSrc, latestBlobSrc];
  }
}

function handleLoadedData(idx: 0 | 1) {
  if (disposed) return;
  if (idx !== activeIdx.value || !props.playing) {
    resetStandbyBuffer(idx);
  }
}

function handleEnded(idx: 0 | 1) {
  if (disposed || !props.playing) return;
  if (idx === activeIdx.value && !handoffInFlight) {
    void performHandoff();
  }
}

function warmBlobSrc(url: string) {
  const initial = getPlayableVideoUrl(url);
  latestBlobSrc = initial.startsWith("blob:") ? initial : null;
  bufferSrcs.value = [initial, initial];
  if (latestBlobSrc) return;

  const targetUrl = url;
  void preloadVideoBlob(targetUrl)
    .then((blobUrl) => {
      if (disposed || props.src !== targetUrl || !blobUrl.startsWith("blob:")) return;
      latestBlobSrc = blobUrl;
      const standbyIdx: 0 | 1 = activeIdx.value === 0 ? 1 : 0;
      bufferSrcs.value[standbyIdx] = blobUrl;
      if (!props.playing) {
        bufferSrcs.value[activeIdx.value] = blobUrl;
      }
    })
    .catch(() => undefined);
}

watch(
  () => props.src,
  (newSrc) => {
    stopPlayback();
    activeIdx.value = 0;
    warmBlobSrc(newSrc);
    if (props.playing) {
      void startPlayback();
    }
  },
);

watch(
  () => props.playing,
  (playing) => {
    if (playing) {
      void startPlayback();
    } else {
      stopPlayback();
    }
  },
);

onMounted(() => {
  warmBlobSrc(props.src);
  if (props.playing) {
    void startPlayback();
  } else {
    stopPlayback();
  }
});

onBeforeUnmount(() => {
  disposed = true;
  stopPlayback();
});
</script>

<template>
  <div class="seamless-loop-root" :data-testid="testId">
    <video
      v-for="idx in ([0, 1] as const)"
      :key="idx"
      :ref="(el) => setBufferRef(idx, el)"
      :src="bufferSrcs[idx]"
      :poster="idx === 0 ? poster : undefined"
      class="seamless-loop-video"
      :class="{ active: activeIdx === idx }"
      muted
      playsinline
      preload="auto"
      :data-buffer-index="idx"
      @loadeddata="handleLoadedData(idx)"
      @ended="handleEnded(idx)"
    />
  </div>
</template>

<style scoped>
:where(.seamless-loop-root) {
  position: relative;
  width: 100%;
  height: 100%;
  overflow: hidden;
}

.seamless-loop-video {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
  pointer-events: none;
  opacity: 0;
  z-index: 1;
}

.seamless-loop-video.active {
  opacity: 1;
  z-index: 2;
}
</style>
