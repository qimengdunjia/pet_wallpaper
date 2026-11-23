<!-- 文件用途：展示宠物类型与 MasterGo 原始素材，并将选择传给照片录入页。 -->
<script setup lang="ts">
import backChevron from "@/assets/mastergo/back-chevron.svg";
import { ref, watch } from "vue";
import catArtwork from "@/assets/mastergo/cat.png";
import dogArtwork from "@/assets/mastergo/dog-happy.png";
import multiDogArtwork from "@/assets/mastergo/dog-standing.png";
import selectionHeart from "@/assets/mastergo/species-selection-heart.svg";
import { guardParkedAction, setRoute, systemState } from "@/stores/systemStore";

type SpeciesChoice = "cat" | "dog" | "both";
const selected = ref<SpeciesChoice | null>(systemState.onboardingSpeciesMode);

watch(
  () => systemState.onboardingSpeciesMode,
  (value) => {
    selected.value = value;
  },
);

// 卡片顺序和造型对应 MasterGo 屏 04（3:3621）。
const options: Array<{ id: SpeciesChoice; title: string; artwork: string }> = [
  { id: "dog", title: "狗狗", artwork: dogArtwork },
  { id: "cat", title: "猫咪", artwork: catArtwork },
  { id: "both", title: "多宠", artwork: multiDogArtwork },
];

function handleBack() {
  setRoute(systemState.onboardingReturnRoute || "welcome");
}

function handleNext() {
  if (!selected.value) return;
  if (!guardParkedAction("继续录入宠物")) return;
  systemState.onboardingSpeciesMode = selected.value;
  setRoute("onboarding-upload");
}
</script>

<template>
  <section class="species-screen mastergo-cloud-sky" data-testid="onboarding-species-view">
    <header class="screen-header">
      <button
        class="circle-back-btn"
        aria-label="返回"
        data-testid="species-back-btn"
        @click="handleBack"
      >
        <img :src="backChevron" alt="" />
      </button>
      <h1 class="screen-title">选择希望录入的宠物类型</h1>
    </header>

    <div class="cards-row">
      <button
        v-for="opt in options"
        :key="opt.id"
        class="species-card"
        :class="{ active: selected === opt.id }"
        :data-testid="'species-card-' + opt.id"
        :aria-pressed="selected === opt.id"
        @click="selected = opt.id"
      >
        <img
          v-if="selected === opt.id"
          class="selected-heart-doodle"
          :src="selectionHeart"
          alt=""
        />
        <div class="card-art-box" aria-hidden="true">
          <img :src="opt.artwork" :class="'art-' + opt.id" alt="" />
          <img v-if="opt.id === 'both'" :src="catArtwork" class="art-both-cat" alt="" />
        </div>
        <strong class="card-label">{{ opt.title }}</strong>
      </button>
    </div>

    <button
      class="btn btn-black next-btn"
      :disabled="!selected"
      data-testid="species-next-btn"
      @click="handleNext"
    >
      下一步
    </button>
  </section>
</template>

<style scoped>
.species-screen {
  position: relative;
  flex: 1;
  width: 100%;
  min-height: 0;
  padding: clamp(48px, 10.8vh, 156px) 3.3vw clamp(46px, 13vh, 188px);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-sky);
  overflow: hidden;
}

.screen-header {
  position: relative;
  width: 100%;
  min-height: 36px;
  display: grid;
  place-items: center;
}

.screen-header .circle-back-btn {
  position: absolute;
  left: 0;
}

.screen-title {
  margin: 0 48px;
  text-align: center;
  font-size: clamp(17px, 2vw, 48px);
  font-weight: 600;
  color: #2c2c2c;
}

.cards-row {
  width: min(79.6875vw, calc(79.6875vh * 16 / 9));
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: min(7.03125vw, 12.5vh);
}

.species-card {
  position: relative;
  aspect-ratio: 5 / 6;
  border-radius: clamp(12px, 2.4vw, 58px);
  padding: 0;
  background: linear-gradient(160deg, #eff7ff, #d1e6ff);
  border: 2px solid rgba(255, 255, 255, 0.92);
  box-shadow: 0 12px 32px rgba(42, 85, 148, 0.13);
}

.species-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 16px 36px rgba(42, 85, 148, 0.19);
}

.species-card.active {
  background: linear-gradient(160deg, #f7fbff, #dceaff);
  border-color: #ffffff;
  box-shadow: 0 16px 40px rgba(42, 85, 148, 0.22);
}

.selected-heart-doodle {
  position: absolute;
  right: -16%;
  top: -11.5%;
  width: 37.5%;
  z-index: 1;
  pointer-events: none;
}

.card-art-box {
  position: absolute;
  inset: 0 0 12%;
  overflow: hidden;
  border-radius: inherit;
  pointer-events: none;
}

.card-art-box img {
  position: absolute;
  height: auto;
}

.art-dog {
  width: 82%;
  left: 9%;
  top: -21.5%;
}

.art-cat {
  width: 115%;
  left: -7.5%;
  top: -3%;
}

.art-both {
  width: 65%;
  left: -1%;
  top: -7%;
}

.art-both-cat {
  width: 87%;
  right: -15%;
  top: 18%;
}

.card-label {
  position: absolute;
  inset: auto 0 7%;
  font-size: clamp(14px, 1.7vw, 43px);
  font-weight: 700;
  color: #2c2c2c;
}

.next-btn {
  width: max(112px, 16.4vw);
  height: clamp(36px, 8.33vh, 120px);
  padding-inline: 6px;
  flex-shrink: 0;
  font-size: clamp(14px, 1.45vw, 36px);
}
</style>
