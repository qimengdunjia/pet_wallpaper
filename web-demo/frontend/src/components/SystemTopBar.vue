<!-- 文件用途：显示 MasterGo 车机状态图标、时钟与 Demo 系统操作。 -->
<script setup lang="ts">
import { computed } from "vue";
import avatarArt from "@/assets/mastergo/status-avatar.svg";
import bluetoothIcon from "@/assets/mastergo/status-bluetooth.svg";
import cameraIcon from "@/assets/mastergo/status-camera.svg";
import chargingIcon from "@/assets/mastergo/status-charging.svg";
import messageIcon from "@/assets/mastergo/status-message.svg";
import networkIcon from "@/assets/mastergo/status-5g.svg";
import signalIcon from "@/assets/mastergo/status-signal.svg";
import { hasActiveBackgroundJobs } from "@/stores/generationStore";
import { petState } from "@/stores/petStore";
import { interruptPlayback, playerState } from "@/stores/playerStore";
import {
  isWallpaperImmersive,
  setDrivingMode,
  setImmersiveMode,
  setRoute,
  systemState,
  triggerSafetyAlert,
} from "@/stores/systemStore";
import { useClock } from "@/stores/useClock";

const clockText = useClock();
const isImmersive = computed(() => isWallpaperImmersive());
const showReferenceStatus = computed(
  () => !systemState.drawerOpen && (systemState.route === "onboarding-upload" || playerState.selectorOpen),
);
const canEnterImmersive = computed(
  () => systemState.route === "wallpaper" && !playerState.selectorOpen,
);

const isDarkStage = computed(
  () =>
    (systemState.route === "wallpaper" && !playerState.selectorOpen) ||
    systemState.route === "generating",
);

const routeLabel = computed(() => {
  switch (systemState.route) {
    case "welcome":
      return "欢迎页";
    case "home":
      return "应用首页";
    case "onboarding-species":
      return "选择宠物类型";
    case "onboarding-upload":
      return "完善宠物信息";
    case "generating":
      return "生成过场";
    case "wallpaper":
      return "桌面壁纸";
    default:
      return "";
  }
});

const canGoHome = computed(() => systemState.route !== "welcome" && systemState.route !== "home");

const bgGeneratingCount = computed(
  () =>
    petState.pets.filter(
      (p) => p.latest_job?.status === "queued" || p.latest_job?.status === "generating",
    ).length,
);

function handleBackHome() {
  interruptPlayback();
  if (petState.savedWallpaper || petState.pets.some((p) => p.active_assets) || Boolean(petState.defaultWallpaper)) {
    setRoute("home");
  } else {
    setRoute("welcome");
  }
}

function toggleDriving() {
  const next = systemState.drivingMode === "parked" ? "driving" : "parked";
  setDrivingMode(next);
}

function handleTriggerAlert() {
  interruptPlayback("收到高优先级驾驶提醒，已暂停动作播放");
  triggerSafetyAlert(
    "行车安全优先提醒",
    "车机系统安全提醒具有最高优先级，已中断当前壁纸动作并锁定画布互动。",
  );
}

function enterImmersiveMode() {
  setImmersiveMode(true);
}

async function toggleFullscreen() {
  try {
    if (!document.fullscreenElement) {
      await document.documentElement.requestFullscreen();
    } else {
      await document.exitFullscreen();
    }
  } catch {
    // 部分受限浏览环境下忽略全屏异常
  }
}
</script>

<template>
  <header
    v-if="!isImmersive"
    class="system-topbar"
    :class="{ 'is-dark-stage': isDarkStage, 'upload-status': showReferenceStatus }"
    data-testid="system-topbar"
    @click.stop
  >
    <div v-if="showReferenceStatus" class="upload-status-icons">
      <button
        class="upload-status-avatar"
        aria-label="演示与规格"
        title="演示与规格"
        data-testid="toggle-demo-drawer"
        @click="systemState.drawerOpen = true"
      >
        <img :src="avatarArt" alt="" />
      </button>
      <img :src="networkIcon" class="upload-status-network" alt="5G" />
      <img :src="bluetoothIcon" class="upload-status-bluetooth" alt="" />
      <span class="upload-status-indicator message-indicator"><img :src="messageIcon" alt="" /></span>
      <span class="upload-status-indicator camera-indicator"><img :src="cameraIcon" alt="" /></span>
      <img :src="chargingIcon" alt="" />
    </div>

    <div v-else class="topbar-left">
      <div class="avatar-dot" title="演示驾驶员">
        <img :src="avatarArt" alt="" />
      </div>
      <img class="status-svg" :src="signalIcon" alt="" />
      <img class="status-svg" :src="networkIcon" alt="5G" />
      <img class="status-svg" :src="cameraIcon" alt="" />
      <img class="status-svg status-charging" :src="chargingIcon" alt="" />

      <span class="route-pill" data-testid="topbar-route-label">{{ routeLabel }}</span>

      <button
        v-if="canGoHome"
        class="top-ctrl-btn"
        data-testid="topbar-back-home"
        @click="handleBackHome"
      >
        返回首页
      </button>

      <span
        v-if="bgGeneratingCount > 0 || hasActiveBackgroundJobs()"
        class="bg-job-pill"
        data-testid="topbar-bg-jobs"
      >
        后台生成中 ({{ bgGeneratingCount }})
      </span>
    </div>

    <div v-if="!showReferenceStatus" class="topbar-right">
      <button
        class="top-ctrl-btn driving-btn"
        :class="systemState.drivingMode === 'parked' ? 'is-parked' : 'is-driving'"
        data-testid="driving-mode-toggle"
        @click="toggleDriving"
      >
        <span class="gear-badge">{{ systemState.drivingMode === "parked" ? "P" : "D" }}</span>
        <span>{{ systemState.drivingMode === "parked" ? "演示停车" : "车辆行驶中" }}</span>
      </button>

      <button
        class="top-ctrl-btn"
        data-testid="trigger-safety-alert"
        @click="handleTriggerAlert"
      >
        模拟驾驶提醒
      </button>

      <button
        class="top-ctrl-btn"
        data-testid="toggle-demo-drawer"
        @click="systemState.drawerOpen = !systemState.drawerOpen"
      >
        {{ systemState.drawerOpen ? "收起验收设置" : "演示与规格" }}
      </button>

      <button
        v-if="canEnterImmersive"
        class="top-ctrl-btn"
        data-testid="toggle-immersive"
        @click="enterImmersiveMode"
      >
        沉浸模式
      </button>

      <button
        class="top-ctrl-btn"
        data-testid="toggle-fullscreen"
        @click="toggleFullscreen"
      >
        {{ systemState.isFullscreen ? "退出全屏" : "全屏" }}
      </button>

      <span class="clock-text">{{ clockText }}</span>
    </div>
    <span v-else class="upload-status-clock">{{ clockText }}</span>
  </header>
</template>

<style scoped>
.system-topbar.upload-status {
  height: calc(120 * var(--mastergo-unit));
  padding-inline:
    calc(50vw - 1248 * var(--mastergo-unit))
    calc(50vw - 1208 * var(--mastergo-unit));
}

.upload-status-icons {
  display: grid;
  grid-template-columns: repeat(6, calc(120 * var(--mastergo-unit)));
  place-items: center;
}

.upload-status-avatar {
  width: calc(56 * var(--mastergo-unit));
  height: calc(56 * var(--mastergo-unit));
  padding: 0;
  border-radius: 50%;
  border: 1px solid rgb(255 255 255 / 25%);
  background: linear-gradient(135deg, rgb(255 255 255 / 12%), transparent 49%, rgb(255 255 255 / 8%));
  translate: calc(16 * var(--mastergo-unit)) 0;
}

.upload-status-icons img {
  display: block;
  width: calc(35 * var(--mastergo-unit));
  height: auto;
}

.upload-status-avatar img,
.avatar-dot img {
  display: block;
  width: 100%;
  height: 100%;
  border-radius: 50%;
}

.upload-status-icons .upload-status-network {
  width: calc(19 * var(--mastergo-unit));
  transform: translateY(calc(-12 * var(--mastergo-unit)));
}

.upload-status-icons .upload-status-bluetooth {
  width: calc(24 * var(--mastergo-unit));
}

.upload-status-indicator {
  position: relative;
}

.upload-status-indicator::after {
  content: "";
  position: absolute;
  width: calc(8 * var(--mastergo-unit));
  height: calc(8 * var(--mastergo-unit));
  border-radius: 50%;
  background: #e24f4f;
}

.message-indicator::after {
  top: 0;
  right: 0;
}

.camera-indicator::after {
  top: 36%;
  left: 26%;
}

.upload-status-clock {
  color: #121628;
  font-size: clamp(14px, calc(40 * var(--mastergo-unit)), 40px);
  font-variant-numeric: tabular-nums;
}

.system-topbar {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  height: 46px;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  color: #121628;
  background: transparent;
}

.system-topbar.is-dark-stage {
  color: #f4f7fb;
  background: linear-gradient(180deg, rgba(6, 9, 14, 0.72) 0%, rgba(6, 9, 14, 0.28) 100%);
}

.topbar-left,
.topbar-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.avatar-dot {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.75);
  color: #4981f2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 6px rgba(18, 28, 79, 0.12);
}

.status-svg {
  width: 17px;
  height: 17px;
  object-fit: contain;
  opacity: 0.85;
}

.is-dark-stage .status-svg:not(.status-charging) {
  filter: brightness(0) invert(1);
}

.is-dark-stage .status-charging {
  filter: drop-shadow(0 0 1px #fff);
}

.route-pill {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.48);
  border: 1px solid rgba(255, 255, 255, 0.72);
  color: #121628;
}

.is-dark-stage .route-pill {
  background: rgba(255, 255, 255, 0.16);
  border-color: rgba(255, 255, 255, 0.24);
  color: #f4f7fb;
}

.top-ctrl-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.56);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255, 255, 255, 0.78);
  color: #121628;
}

.top-ctrl-btn:hover {
  background: rgba(255, 255, 255, 0.88);
}

.is-dark-stage .top-ctrl-btn {
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.28);
  color: #f8fafc;
}

.is-dark-stage .top-ctrl-btn:hover {
  background: rgba(255, 255, 255, 0.3);
}

.driving-btn.is-parked {
  background: rgba(221, 253, 102, 0.72);
  border-color: rgba(167, 212, 42, 0.65);
  color: #121628;
}

.driving-btn.is-driving {
  background: #f59e0b;
  border-color: #d97706;
  color: #121628;
}

.gear-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 17px;
  height: 17px;
  border-radius: 5px;
  font-size: 11px;
  font-weight: 800;
  background: rgba(18, 22, 40, 0.14);
}

.bg-job-pill {
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 999px;
  background: rgba(73, 129, 242, 0.2);
  color: #1d4ed8;
  border: 1px solid rgba(73, 129, 242, 0.35);
}

.is-dark-stage .bg-job-pill {
  background: rgba(102, 178, 255, 0.24);
  color: #dbeafe;
  border-color: rgba(102, 178, 255, 0.45);
}

.clock-text {
  font-size: 14px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  margin-left: 4px;
}
</style>
