<script setup lang="ts">
import { computed } from "vue";
import { hasActiveBackgroundJobs } from "@/stores/generationStore";
import { petState } from "@/stores/petStore";
import { interruptPlayback, playerState } from "@/stores/playerStore";
import {
  setDrivingMode,
  setRoute,
  systemState,
  triggerSafetyAlert,
} from "@/stores/systemStore";
import { useClock } from "@/stores/useClock";

const clockText = useClock();

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
  if (petState.savedWallpaper || petState.pets.some((p) => p.active_assets)) {
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
    class="system-topbar"
    :class="{ 'is-dark-stage': isDarkStage }"
    data-testid="system-topbar"
    @click.stop
  >
    <div class="topbar-left">
      <div class="avatar-dot" title="演示驾驶员">
        <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor">
          <path d="M12 12a4.2 4.2 0 1 0 0-8.4 4.2 4.2 0 0 0 0 8.4Zm0 2.1c-4.1 0-7.5 2.1-7.5 4.7v1.1h15v-1.1c0-2.6-3.4-4.7-7.5-4.7Z" />
        </svg>
      </div>
      <span class="signal-text">5G</span>
      <svg class="status-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8">
        <path d="M3 15v-2M7 15v-4M11 15V9M15 15V6" stroke-linecap="round" />
      </svg>
      <svg class="status-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7">
        <rect x="3" y="4.5" width="14" height="10" rx="2.5" />
        <path d="M6.5 9.5h7" stroke-linecap="round" />
      </svg>
      <svg class="status-svg" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.7">
        <rect x="2.5" y="6" width="13" height="8" rx="2" />
        <path d="M17.5 8.5v3" stroke-linecap="round" />
        <rect x="4.5" y="8" width="7" height="4" rx="1" fill="#21AA4C" stroke="none" />
      </svg>

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

    <div class="topbar-right">
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
        class="top-ctrl-btn"
        data-testid="toggle-fullscreen"
        @click="toggleFullscreen"
      >
        {{ systemState.isFullscreen ? "退出全屏" : "全屏" }}
      </button>

      <span class="clock-text">{{ clockText }}</span>
    </div>
  </header>
</template>

<style scoped>
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

.signal-text {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.02em;
}

.status-svg {
  width: 17px;
  height: 17px;
  opacity: 0.85;
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
