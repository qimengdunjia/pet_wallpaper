<!-- 文件用途：在同一个视频元素中连续播放入场先导与等待循环。 -->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { readPreloadedVideoBytes } from "@/lib/preload";

const props = defineProps<{
  introUrl: string;
  loopUrl: string;
  mimeType: string; // MediaSource 使用的视频编码类型。
}>();

const emit = defineEmits<{
  round: [round: number]; // 先导为 0，播放到第一遍循环时为 1。
  failed: [];
}>();

const videoRef = ref<HTMLVideoElement | null>(null);
const controller = new AbortController();
let mediaUrl: string | undefined;
let buffer: SourceBuffer | undefined;
let loopBytes: ArrayBuffer | undefined;
let startupTimer: number | undefined;
let introEnd: number | undefined;
let loopDuration: number | undefined;
let started = false;
let currentRound = 0;

function clearStartupTimer() {
  window.clearTimeout(startupTimer);
  startupTimer = undefined;
}

function dispose() {
  controller.abort();
  clearStartupTimer();
  const video = videoRef.value;
  if (video && mediaUrl) {
    video.pause();
    video.removeAttribute("src");
    video.load();
  }
  if (mediaUrl) URL.revokeObjectURL(mediaUrl);
  mediaUrl = undefined;
  buffer = undefined;
  loopBytes = undefined;
}

function fail() {
  if (controller.signal.aborted) return;
  dispose();
  emit("failed");
}

function updatePlayback() {
  const video = videoRef.value;
  if (!video || !buffer || !loopBytes || buffer.updating || controller.signal.aborted) return;
  try {
    const ranges = buffer.buffered;
    if (ranges.length !== 1) throw new Error("过场视频缓冲不连续");
    const start = ranges.start(0);
    const end = ranges.end(0);
    if (introEnd === undefined) {
      introEnd = end;
    } else if (loopDuration === undefined) {
      loopDuration = end - introEnd;
      if (loopDuration <= 0) throw new Error("循环视频时长无效");
    }

    // 首屏准备好先导和两遍循环再播放，后续提前续入下一遍。
    if (!started && loopDuration !== undefined && end >= introEnd + 2 * loopDuration - 0.002) {
      started = true;
      void video.play().then(clearStartupTimer).catch(fail);
    }
    if (loopDuration !== undefined && video.currentTime - start > 28) {
      buffer.remove(start, video.currentTime - 8);
    } else if (!started || (loopDuration !== undefined && end - video.currentTime < loopDuration + 2)) {
      buffer.timestampOffset = end;
      buffer.appendBuffer(loopBytes);
    }
  } catch {
    fail();
  }
}

function handleTimeUpdate() {
  const time = videoRef.value?.currentTime;
  if (time !== undefined && introEnd !== undefined && loopDuration && time >= introEnd) {
    const round = Math.floor((time - introEnd) / loopDuration) + 1;
    if (round > currentRound) {
      currentRound = round;
      emit("round", round);
    }
  }
  updatePlayback();
}

async function initialize(source: MediaSource) {
  try {
    const [intro, loop] = await Promise.all([
      readPreloadedVideoBytes(props.introUrl),
      readPreloadedVideoBytes(props.loopUrl),
    ]);
    if (controller.signal.aborted) return;
    loopBytes = loop;
    buffer = source.addSourceBuffer(props.mimeType);
    buffer.mode = "sequence";
    buffer.addEventListener("updateend", updatePlayback, { signal: controller.signal });
    buffer.addEventListener("error", fail, { signal: controller.signal });
    buffer.appendBuffer(intro);
  } catch {
    fail();
  }
}

onMounted(() => {
  const video = videoRef.value;
  if (!video) return;
  try {
    const source = new MediaSource();
    source.addEventListener("sourceopen", () => void initialize(source), { once: true, signal: controller.signal });
    mediaUrl = URL.createObjectURL(source);
    startupTimer = window.setTimeout(fail, 5000);
    video.src = mediaUrl;
  } catch {
    fail();
  }
});

onBeforeUnmount(dispose);
</script>

<template>
  <video
    ref="videoRef"
    muted
    playsinline
    data-testid="continuous-transition-video"
    @timeupdate="handleTimeUpdate"
    @error="fail"
  />
</template>
