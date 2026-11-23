<script setup lang="ts">
import { computed } from "vue";
import { petState } from "@/stores/petStore";
import { interruptPlayback, playerState } from "@/stores/playerStore";
import { setRoute, showToast, systemState } from "@/stores/systemStore";

const isDarkStage = computed(
  () =>
    (systemState.route === "wallpaper" && !playerState.selectorOpen) ||
    systemState.route === "generating",
);

function handleHomeClick() {
  interruptPlayback();
  if (petState.savedWallpaper || petState.pets.some((p) => p.active_assets)) {
    setRoute("home");
  } else {
    setRoute("welcome");
  }
}

function handleDockHint(label: string) {
  showToast(`车机系统控件：${label}（高优先级控件层，不透传壁纸点击）`, "info", 2000);
}
</script>

<template>
  <footer
    class="car-bottom-dock"
    :class="{ 'is-dark-stage': isDarkStage }"
    data-testid="car-bottom-dock"
    @click.stop
  >
    <div class="dock-left">
      <button class="dock-icon-btn" title="回到首页" @click="handleHomeClick">
        <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.9">
          <path d="M4 10.5 12 4l8 6.5V19a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 19v-8.5Z" />
          <path d="M9.5 16.5h5" stroke-linecap="round" />
        </svg>
      </button>
      <span class="temp-text">21.5°</span>
      <button class="dock-icon-btn" title="空调风量" @click="handleDockHint('空调风量')">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8">
          <circle cx="12" cy="12" r="2.2" />
          <path d="M12 9.8c0-3 2.8-5 4.8-3.8 1.4.8 1.2 3-.6 4.1M14.2 12c3 0 5 2.8 3.8 4.8-.8 1.4-3 1.2-4.1-.6M12 14.2c0 3-2.8 5-4.8 3.8-1.4-.8-1.2-3 .6-4.1M9.8 12c-3 0-5-2.8-3.8-4.8.8-1.4 3-1.2 4.1.6" />
        </svg>
      </button>
    </div>

    <div class="dock-center">
      <button class="dock-app-tile" title="导航" @click="handleDockHint('导航')">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
          <polygon points="12 3 19 20 12 16.5 5 20 12 3" />
        </svg>
      </button>
      <button class="dock-app-tile" title="音乐" @click="handleDockHint('媒体')">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M9 17V6l10-2v11" />
          <circle cx="6.5" cy="17.5" r="2.5" />
          <circle cx="16.5" cy="15.5" r="2.5" />
        </svg>
      </button>
      <button class="dock-app-tile is-active" title="AI 宠物壁纸" @click="handleHomeClick">
        <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
          <circle cx="7.5" cy="9" r="1.8" />
          <circle cx="12" cy="7.2" r="1.8" />
          <circle cx="16.5" cy="9" r="1.8" />
          <path d="M12 11.2c-3 0-5.2 2.2-5.2 4.4 0 1.4 1.1 2.4 2.6 2.4 1 0 1.7-.4 2.6-.4s1.6.4 2.6.4c1.5 0 2.6-1 2.6-2.4 0-2.2-2.2-4.4-5.2-4.4Z" />
        </svg>
      </button>
      <button class="dock-app-tile" title="车辆设置" @click="handleDockHint('车辆控制')">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3v3M12 18v3M3 12h3M18 12h3" stroke-linecap="round" />
        </svg>
      </button>
      <button class="dock-app-tile" title="应用中心" @click="handleDockHint('应用中心')">
        <svg viewBox="0 0 24 24" width="15" height="15" fill="currentColor">
          <rect x="4" y="4" width="6.5" height="6.5" rx="1.8" />
          <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8" />
          <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8" />
          <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8" />
        </svg>
      </button>
    </div>

    <div class="dock-right">
      <button class="dock-icon-btn" title="除雾" @click="handleDockHint('前挡除雾')">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M5 14c1-4 3-7 7-7s6 3 7 7H5Z" />
          <path d="M9 17v2M12 17v2M15 17v2" stroke-linecap="round" />
        </svg>
      </button>
      <button class="dock-icon-btn" title="循环模式" @click="handleDockHint('空气循环')">
        <svg viewBox="0 0 24 24" width="19" height="19" fill="none" stroke="currentColor" stroke-width="1.8">
          <path d="M4 13h16l-1.8-4H7.2L4 13Z" />
          <circle cx="7.5" cy="15.5" r="1.5" />
          <circle cx="16.5" cy="15.5" r="1.5" />
        </svg>
      </button>
      <span class="temp-text">21.5°</span>
      <button class="dock-icon-btn" title="音量" @click="handleDockHint('音量')">
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.9">
          <path d="M5 10v4h3.5l4.5 3.5V6.5L8.5 10H5Z" />
          <path d="M16.5 9a4.5 4.5 0 0 1 0 6" stroke-linecap="round" />
        </svg>
      </button>
    </div>
  </footer>
</template>

<style scoped>
.car-bottom-dock {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  height: 44px;
  z-index: 40;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  color: #121628;
  background: transparent;
}

.car-bottom-dock.is-dark-stage {
  color: #f4f7fb;
  background: linear-gradient(0deg, rgba(6, 9, 14, 0.78) 0%, rgba(6, 9, 14, 0.25) 100%);
}

.dock-left,
.dock-center,
.dock-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.dock-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: inherit;
  opacity: 0.85;
}

.dock-icon-btn:hover {
  opacity: 1;
  background: rgba(18, 22, 40, 0.08);
}

.is-dark-stage .dock-icon-btn:hover {
  background: rgba(255, 255, 255, 0.14);
}

.temp-text {
  font-size: 16px;
  font-weight: 500;
  font-variant-numeric: tabular-nums;
}

.dock-app-tile {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  background: #121628;
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.dock-app-tile.is-active {
  background: #4981f2;
  color: #ffffff;
  box-shadow: 0 3px 10px rgba(73, 129, 242, 0.45);
}

.is-dark-stage .dock-app-tile {
  background: rgba(255, 255, 255, 0.2);
  color: #ffffff;
}

.is-dark-stage .dock-app-tile.is-active {
  background: #66b2ff;
  color: #121628;
}
</style>
