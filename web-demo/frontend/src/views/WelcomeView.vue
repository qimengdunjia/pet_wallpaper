<script setup lang="ts">
import { computed } from "vue";
import { guardParkedAction, setRoute, systemState } from "@/stores/systemStore";

const dogSampleUrl = computed(
  () => systemState.config?.sample_uploads?.dog || "/api/assets/samples/dog/upload",
);
const catSampleUrl = computed(
  () => systemState.config?.sample_uploads?.cat || "/api/assets/samples/cat/upload",
);

function handleStart() {
  if (!guardParkedAction("创建宠物档案")) return;
  systemState.onboardingReturnRoute = "welcome";
  systemState.onboardingSpeciesMode = null;
  setRoute("onboarding-species");
}
</script>

<template>
  <section class="welcome-screen" data-testid="welcome-view">
    <!-- 左侧 MasterGo 荧光黄绿大花瓣装饰 (#F2FA66) -->
    <svg class="welcome-petal-bg" viewBox="0 0 900 720" fill="none" aria-hidden="true">
      <path
        d="M-60,20 C120,-60 360,-30 410,95 C445,180 390,260 340,295 C460,290 585,365 565,485 C548,595 415,645 315,610 C385,685 385,780 315,820 L-60,820 Z"
        fill="#F2FA66"
      />
    </svg>

    <!-- 右侧萌宠近景视觉图融于晴空背景 -->
    <div class="welcome-hero-media" aria-hidden="true">
      <div class="hero-circle-card">
        <img :src="dogSampleUrl" alt="" class="hero-pet-img" />
      </div>
      <div class="hero-cat-inset">
        <img :src="catSampleUrl" alt="" class="hero-pet-img" />
      </div>
    </div>

    <!-- 左侧偏中主文案与黑色胶囊按钮 -->
    <div class="welcome-content">
      <h1 class="welcome-title">让宠物陪伴每次出行</h1>
      <p class="welcome-en">Let your pet accompany you on every trip</p>
      <div class="welcome-cta-wrap">
        <button
          class="btn btn-black welcome-cta"
          data-testid="welcome-create-btn"
          @click="handleStart"
        >
          <span>创建我的宠物档案</span>
          <svg viewBox="0 0 20 20" width="17" height="17" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M5 10h10M11 6l4 4-4 4" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.welcome-screen {
  position: relative;
  flex: 1;
  width: 100%;
  height: 100%;
  padding: 54px 64px 52px;
  display: flex;
  align-items: center;
  overflow: hidden;
  background: var(--bg-sky);
}

.welcome-petal-bg {
  position: absolute;
  left: 0;
  top: 0;
  height: 100%;
  width: 68%;
  pointer-events: none;
  z-index: 1;
}

.welcome-content {
  position: relative;
  z-index: 3;
  max-width: 560px;
  margin-left: 24px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.welcome-title {
  margin: 0;
  font-size: 46px;
  font-weight: 700;
  letter-spacing: 0.01em;
  color: #121628;
  line-height: 1.18;
}

.welcome-en {
  margin: 0;
  font-size: 19px;
  font-weight: 400;
  color: #536478;
}

.welcome-cta-wrap {
  margin-top: 22px;
}

.welcome-cta {
  height: 54px;
  padding: 0 32px;
  font-size: 17px;
  font-weight: 600;
  border-radius: 999px;
}

.welcome-hero-media {
  position: absolute;
  right: 76px;
  top: 50%;
  transform: translateY(-50%);
  width: 440px;
  height: 410px;
  z-index: 2;
  pointer-events: none;
}

.hero-circle-card {
  position: absolute;
  right: 0;
  top: 16px;
  width: 356px;
  height: 356px;
  border-radius: 56px;
  overflow: hidden;
  border: 6px solid rgba(255, 255, 255, 0.78);
  box-shadow: 0 24px 54px rgba(32, 74, 135, 0.22);
  background: var(--surface-frame-blue);
}

.hero-cat-inset {
  position: absolute;
  left: 0;
  bottom: 12px;
  width: 174px;
  height: 174px;
  border-radius: 36px;
  overflow: hidden;
  border: 5px solid rgba(255, 255, 255, 0.9);
  box-shadow: 0 18px 40px rgba(32, 74, 135, 0.24);
  background: #dbeafe;
}

.hero-pet-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
