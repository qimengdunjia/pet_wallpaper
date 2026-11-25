<!-- 文件用途：在壁纸所在的浏览器连接实体按键，并提示单网卡电脑何时可以切换热点。 -->
<script setup lang="ts">
import { onBeforeUnmount, ref } from "vue";
import { createSeatKeyDecoder } from "@/lib/seatKey";
import type { HotzoneSlot } from "@/types";

const props = defineProps<{
  url: string;
  offlineState: "loading" | "ready" | "failed";
}>();
const emit = defineEmits<{ action: [slot: HotzoneSlot]; retryMedia: [] }>();
const open = ref(false);
const state = ref<"idle" | "connecting" | "connected" | "failed">("idle");
let socket: WebSocket | null = null; // 仅当前连接可触发播放，重连时重新建立计数基线。
let timer: number | undefined;

/** 关闭本页的设备连接和超时计时器，无返回值。 */
function disconnect() {
  const previous = socket;
  socket = null;
  window.clearTimeout(timer);
  previous?.close();
  state.value = "idle";
}

/** 按用户操作连接指定设备，每次完整按键或滑动向播放器发出一次动作。 */
function connect() {
  disconnect();
  state.value = "connecting";
  try {
    const current = new WebSocket(props.url);
    socket = current;
    const decode = createSeatKeyDecoder();
    const failed = () => {
      if (socket !== current) return;
      disconnect();
      state.value = "failed";
      open.value = true;
    };
    current.onopen = () => {
      if (socket !== current) return;
      window.clearTimeout(timer);
      state.value = "connected";
    };
    current.onmessage = (event) => {
      if (socket !== current || typeof event.data !== "string") return;
      const action = decode(event.data);
      if (action && !document.hidden) emit("action", action);
    };
    current.onerror = failed;
    current.onclose = failed;
    timer = window.setTimeout(failed, 20000);
  } catch {
    state.value = "failed";
  }
}

onBeforeUnmount(disconnect);
</script>

<template>
  <div class="seat-key-control" @click.stop>
    <button class="btn seat-key-toggle" :aria-expanded="open" @click="open = !open">
      {{ state === "connected" ? "按键已连接" : "实体按键" }}
    </button>
    <section v-if="open" class="seat-key-panel" aria-label="实体按键连接">
      <p v-if="offlineState === 'ready'">壁纸已就绪，可切换到 Agent-IMU 热点。请保留此页面。</p>
      <p v-else-if="offlineState === 'loading'">正在加载壁纸，单 Wi-Fi 电脑请稍后切换热点。</p>
      <p v-else>壁纸未完整加载，切换热点前请先联网重试。
        <button class="retry" @click="emit('retryMedia')">重试加载</button>
      </p>
      <p v-if="state === 'failed'" role="alert">连接已中断或未成功。请确认已连 Agent-IMU，使用新版 Chrome 或 Edge，并允许网站访问本地网络。</p>
      <p v-if="state === 'connected'">在按键的宠物界面短按或轻点触屏触发中区，左右滑动触发对应热区。</p>
      <button v-if="state === 'connecting' || state === 'connected'" class="btn btn-soft btn-sm" @click="disconnect">
        {{ state === "connecting" ? "取消连接" : "断开按键" }}
      </button>
      <button v-else class="btn btn-black btn-sm" @click="connect">
        {{ state === "failed" ? "重新连接" : "连接按键" }}
      </button>
    </section>
  </div>
</template>

<style scoped>
.seat-key-control { position: relative; pointer-events: auto; }
.seat-key-toggle {
  width: max(84px, 16.406cqw);
  height: max(36px, 4.688cqw);
  padding: 0 4px;
  font-size: clamp(11px, 1.45cqw, 36px);
  color: #121628;
  background: rgba(255, 255, 255, 0.65);
  backdrop-filter: blur(16px);
}
.seat-key-panel {
  position: absolute;
  bottom: calc(100% + 8px);
  left: 50%;
  transform: translateX(-50%);
  width: min(300px, 72vw);
  max-height: 55vh;
  overflow: auto;
  border-radius: 14px;
  background: #f7faff;
  padding: 14px;
  color: #121628;
  box-shadow: 0 4px 20px #12162833;
  font-size: 13px;
  line-height: 1.5;
}
.seat-key-panel p { margin: 0 0 10px; }
.retry { color: #2158b1; background: transparent; border: 0; text-decoration: underline; cursor: pointer; }
</style>
