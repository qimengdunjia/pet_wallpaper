<!-- 文件用途：显示车机底栏，使用 MasterGo 原图标并承接系统按钮。 -->
<script setup lang="ts">
import { computed } from "vue";
import homeIcon from "@/assets/mastergo/dock-home.svg";
import fanIcon from "@/assets/mastergo/dock-fan.svg";
import navigationIcon from "@/assets/mastergo/dock-navigation.svg";
import settingsIcon from "@/assets/mastergo/dock-settings.svg";
import appsIcon from "@/assets/mastergo/dock-apps.svg";
import defrostIcon from "@/assets/mastergo/dock-defrost.svg";
import circulationIcon from "@/assets/mastergo/dock-circulation.svg";
import volumeIcon from "@/assets/mastergo/dock-volume.svg";
import camera360Icon from "@/assets/mastergo/dock-camera-360.svg";
import climatePanelIcon from "@/assets/mastergo/dock-climate-panel.svg";
import musicIcon from "@/assets/mastergo/dock-music.svg";
import { petState } from "@/stores/petStore";
import { interruptPlayback, playerState } from "@/stores/playerStore";
import { setRoute, showToast, systemState } from "@/stores/systemStore";

const isDarkStage = computed(
  () =>
    (systemState.route === "wallpaper" && !playerState.selectorOpen) ||
    systemState.route === "generating",
);

// MasterGo 底栏从左到右为设置、全景影像、导航、音乐和应用中心。
const dockApps = [
  { label: "车辆设置", icon: settingsIcon },
  { label: "全景影像", icon: camera360Icon },
  { label: "导航", icon: navigationIcon },
  { label: "音乐", icon: musicIcon },
  { label: "应用中心", icon: appsIcon },
];

function handleHomeClick() {
  interruptPlayback();
  if (petState.savedWallpaper || petState.pets.some((p) => p.active_assets) || Boolean(petState.defaultWallpaper)) {
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
    class="car-bottom-dock mastergo-dock"
    :class="{ 'is-dark-stage': isDarkStage }"
    data-testid="car-bottom-dock"
    @click.stop
  >
    <div class="dock-left">
      <button class="dock-icon-btn" title="回到首页" @click="handleHomeClick">
        <img :src="homeIcon" alt="" />
      </button>
      <span class="temp-text">21.5°</span>
      <button class="dock-icon-btn" title="空调风量" @click="handleDockHint('空调风量')">
        <img :src="fanIcon" alt="" />
      </button>
      <button class="dock-icon-btn" title="空调设置" @click="handleDockHint('空调设置')">
        <img :src="climatePanelIcon" alt="" />
      </button>
    </div>

    <div class="dock-center">
      <button
        v-for="app in dockApps"
        :key="app.label"
        class="dock-app-tile"
        :class="{ 'music-tile': app.label === '音乐' }"
        :title="app.label"
        @click="handleDockHint(app.label)"
      >
        <img :src="app.icon" alt="" />
      </button>
    </div>
    <div class="dock-right">
      <button class="dock-icon-btn" title="除雾" @click="handleDockHint('前挡除雾')">
        <img :src="defrostIcon" alt="" />
      </button>
      <button class="dock-icon-btn" title="循环模式" @click="handleDockHint('空气循环')">
        <img :src="circulationIcon" alt="" />
      </button>
      <span class="temp-text">21.5°</span>
      <button class="dock-icon-btn" title="音量" @click="handleDockHint('音量')">
        <img :src="volumeIcon" alt="" />
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

.dock-center {
  position: absolute;
  left: 50%;
  gap: clamp(8px, 2.1875vw, 56px);
  transform: translateX(-50%);
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

.dock-icon-btn img {
  width: 22px;
  height: 22px;
  object-fit: contain;
}

.is-dark-stage .dock-icon-btn img {
  filter: brightness(0) invert(1);
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
  width: clamp(24px, 2.8125vw, 72px);
  height: clamp(24px, 2.8125vw, 72px);
  padding: 0;
  border-radius: 7px;
  background: #121628;
  color: #ffffff;
  display: inline-flex;
  align-items: center;
  justify-content: center;
}

.dock-app-tile img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.car-bottom-dock .dock-app-tile:has(img) {
  background: transparent;
}

/* 底栏控件使用 MasterGo 画板的相对位置。 */
.car-bottom-dock.mastergo-dock {
  height: calc(128 * var(--mastergo-unit));
  padding: 0;
}

.mastergo-dock .dock-left,
.mastergo-dock .dock-right {
  position: absolute;
  display: grid;
  justify-items: center;
  gap: 0;
}

.mastergo-dock .dock-left {
  left: calc(50vw - 1200 * var(--mastergo-unit));
  grid-template-columns: calc(48 * var(--mastergo-unit)) calc(228 * var(--mastergo-unit))
    calc(48 * var(--mastergo-unit)) calc(48 * var(--mastergo-unit));
  column-gap: calc(80 * var(--mastergo-unit));
}

.mastergo-dock .dock-right {
  right: calc(50vw - 1200 * var(--mastergo-unit));
  grid-template-columns:
    calc(48 * var(--mastergo-unit)) calc(92 * var(--mastergo-unit))
    calc(60 * var(--mastergo-unit)) calc(64 * var(--mastergo-unit))
    calc(228 * var(--mastergo-unit)) calc(80 * var(--mastergo-unit))
    calc(48 * var(--mastergo-unit));
}

.mastergo-dock .dock-right > :nth-child(2) { grid-column: 3; }
.mastergo-dock .dock-right > :nth-child(3) { grid-column: 5; }
.mastergo-dock .dock-right > :nth-child(4) { grid-column: 7; }

.mastergo-dock .dock-icon-btn {
  width: 100%;
  height: calc(68 * var(--mastergo-unit));
  padding: 0;
  opacity: 1;
}

.mastergo-dock .dock-icon-btn img {
  width: calc(42 * var(--mastergo-unit));
  height: calc(42 * var(--mastergo-unit));
}

.mastergo-dock .dock-right > :nth-child(2) img {
  width: calc(60 * var(--mastergo-unit));
}

.mastergo-dock .temp-text {
  display: grid;
  place-items: center;
  width: 100%;
  background: url("../assets/mastergo/dock-temperature-arrows.svg") center / 100% auto no-repeat;
  font-size: calc(56 * var(--mastergo-unit));
  font-weight: 400;
  white-space: nowrap;
}

.mastergo-dock .dock-center {
  gap: calc(56 * var(--mastergo-unit));
}

.mastergo-dock .dock-app-tile {
  width: calc(72 * var(--mastergo-unit));
  height: calc(72 * var(--mastergo-unit));
}

.car-bottom-dock.mastergo-dock .music-tile {
  background: linear-gradient(180deg, #fff, #ededed);
  border-radius: calc(16 * var(--mastergo-unit));
}

.mastergo-dock .music-tile img {
  width: calc(32.4 * var(--mastergo-unit));
  height: calc(47.15 * var(--mastergo-unit));
}
</style>
