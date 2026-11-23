<!-- 文件用途：使用 MasterGo 原始图层展示欢迎页，并进入宠物档案录入。 -->
<script setup lang="ts">
import welcomeDecoration from "@/assets/mastergo/welcome-decoration.svg";
import welcomeCat from "@/assets/mastergo/cat.png";
import welcomeDog from "@/assets/mastergo/dog-standing.png";
import welcomeClouds from "@/assets/mastergo/clouds.png";
import welcomeArrow from "@/assets/mastergo/welcome-next-arrow.svg";
import { guardParkedAction, setRoute, systemState } from "@/stores/systemStore";

function handleStart() {
  if (!guardParkedAction("创建宠物档案")) return;
  systemState.onboardingReturnRoute = "welcome";
  systemState.onboardingSpeciesMode = null;
  setRoute("onboarding-species");
}
</script>

<template>
  <section class="welcome-screen" data-testid="welcome-view">
    <div class="welcome-canvas">
      <div class="welcome-art" aria-hidden="true">
        <img :src="welcomeClouds" alt="" class="welcome-cloud welcome-cloud-left" />
        <img :src="welcomeClouds" alt="" class="welcome-cloud welcome-cloud-right" />
        <img :src="welcomeDecoration" alt="" class="welcome-decoration" />
        <img :src="welcomeCat" alt="" class="welcome-cat" />
        <img :src="welcomeDog" alt="" class="welcome-dog" />
      </div>

      <div class="welcome-content">
        <h1>让宠物陪伴每次出行</h1>
        <p>Let your pet accompany you on every trip</p>
        <button
          class="btn btn-black welcome-cta"
          data-testid="welcome-create-btn"
          @click="handleStart"
        >
          创建我的宠物档案
          <img :src="welcomeArrow" alt="" />
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.welcome-screen {
  flex: 1;
  display: grid;
  place-items: center;
  overflow: hidden;
  background: var(--bg-sky);
}

.welcome-canvas {
  /* 原稿以 2560 × 1440 排布。画板等比缩放，窄窗口中仍可操作。 */
  position: relative;
  width: min(100vw, calc(100vh * 16 / 9));
  aspect-ratio: 16 / 9;
  container-type: size;
}

.welcome-art {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}

.welcome-art img {
  position: absolute;
  display: block;
}

.welcome-cloud {
  width: 49%;
  opacity: 0.3;
}

.welcome-cloud-left {
  left: -16.84%;
  top: 62.22%;
  transform: scaleX(-1);
}

.welcome-cloud-right {
  left: 70.74%;
  top: 60.56%;
  transform: scaleX(-1);
}

.welcome-decoration {
  left: -10.4%;
  top: -27.25%;
  width: 119.03%;
}

.welcome-cat {
  left: 2.28%;
  top: 15.99%;
  width: 28.75%;
  transform: rotate(-10deg);
}

.welcome-dog {
  left: 71.19%;
  top: 16.49%;
  width: 24.79%;
  transform: rotate(10deg);
}

.welcome-content {
  position: absolute;
  inset: 37.6% 0 auto;
  display: grid;
  justify-items: center;
  text-align: center;
}

.welcome-content h1 {
  margin: 0;
  color: #2c2c2c;
  font-size: clamp(16px, 3.7cqw, 94px);
  line-height: 1.15;
}

.welcome-content p {
  margin: 1cqw 0 0;
  color: #666666;
  font-size: clamp(10px, 1.95cqw, 50px);
  line-height: 1.2;
}

.welcome-cta {
  min-height: 38px;
  height: 10.28cqh;
  margin-top: 2.7cqw;
  padding: 0 2.5cqw;
  font-size: clamp(12px, 1.75cqw, 45px);
  white-space: nowrap;
}

.welcome-cta img {
  width: 1.7cqw;
  height: 1.7cqw;
  min-width: 14px;
  min-height: 14px;
}
</style>
