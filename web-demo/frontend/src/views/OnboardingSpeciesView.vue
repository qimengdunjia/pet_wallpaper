<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { guardParkedAction, setRoute, systemState } from "@/stores/systemStore";

const dogSampleUrl = computed(
  () => systemState.config?.sample_uploads?.dog || "/api/assets/samples/dog/upload",
);
const catSampleUrl = computed(
  () => systemState.config?.sample_uploads?.cat || "/api/assets/samples/cat/upload",
);

type SpeciesChoice = "cat" | "dog" | "both";
const selected = ref<SpeciesChoice | null>(systemState.onboardingSpeciesMode);

watch(
  () => systemState.onboardingSpeciesMode,
  (val) => {
    selected.value = val;
  },
);

// 顺序严格对齐 MasterGo 屏 04（3:3621）：狗狗、猫咪、多宠
const options: Array<{ id: SpeciesChoice; title: string; subtitle: string }> = [
  { id: "dog", title: "狗狗", subtitle: "正面近景待机与左/中/右鼻尖轻触" },
  { id: "cat", title: "猫咪", subtitle: "正面近景待机与左/中/右伸爪互动" },
  { id: "both", title: "多宠", subtitle: "同时录入狗狗与猫咪，先就绪先展示" },
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
  <section class="species-screen" data-testid="onboarding-species-view">
    <header class="screen-header">
      <button
        class="circle-back-btn"
        aria-label="返回"
        data-testid="species-back-btn"
        @click="handleBack"
      >
        <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12.5 5 7.5 10l5 5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <h1 class="screen-title">选择希望录入的宠物类型</h1>
      <span class="header-spacer" />
    </header>

    <div class="cards-row">
      <button
        v-for="opt in options"
        :key="opt.id"
        class="species-card"
        :class="{ active: selected === opt.id }"
        :data-testid="`species-card-${opt.id}`"
        @click="selected = opt.id"
      >
        <!-- MasterGo 屏 04 同款选中态紫色手绘爱心与放射短线 -->
        <svg
          v-if="selected === opt.id"
          class="selected-heart-doodle"
          viewBox="0 0 110 110"
          fill="none"
          aria-hidden="true"
        >
          <path
            d="M28,68 C16,52 14,38 24,33 C32,29 39,38 40,46 C46,35 56,31 62,38 C69,46 58,64 38,76 C33,73 30,71 28,68 Z"
            stroke="#8D6BFF"
            stroke-width="4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
          <path
            d="M72,22 L78,10 M86,32 L98,25 M90,48 L104,48 M84,64 L96,72"
            stroke="#8D6BFF"
            stroke-width="3.6"
            stroke-linecap="round"
          />
        </svg>

        <div class="card-art-box">
          <img
            v-if="opt.id === 'dog'"
            :src="dogSampleUrl"
            alt="狗狗"
            class="art-single"
          />
          <img
            v-else-if="opt.id === 'cat'"
            :src="catSampleUrl"
            alt="猫咪"
            class="art-single"
          />
          <div v-else class="art-dual">
            <img :src="catSampleUrl" alt="猫咪" class="art-dual-cat" />
            <img :src="dogSampleUrl" alt="狗狗" class="art-dual-dog" />
          </div>
        </div>

        <strong class="card-label">{{ opt.title }}</strong>
        <span class="card-sub">{{ opt.subtitle }}</span>
      </button>
    </div>

    <div class="bottom-cta">
      <button
        class="btn btn-black next-btn"
        :disabled="!selected"
        data-testid="species-next-btn"
        @click="handleNext"
      >
        下一步
      </button>
    </div>
  </section>
</template>

<style scoped>
.species-screen {
  position: relative;
  flex: 1;
  width: 100%;
  height: 100%;
  padding: 54px 56px 52px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-sky);
  overflow: hidden;
}

.screen-header {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.screen-title {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: #121628;
}

.header-spacer {
  width: 42px;
}

.cards-row {
  width: min(1040px, 94vw);
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 32px;
  align-items: center;
}

.species-card {
  position: relative;
  border-radius: 30px;
  padding: 20px 20px 22px;
  background: rgba(255, 255, 255, 0.88);
  border: 2px solid rgba(255, 255, 255, 0.96);
  box-shadow: 0 16px 38px rgba(42, 85, 148, 0.13);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.species-card:hover {
  transform: translateY(-3px);
  box-shadow: 0 20px 44px rgba(42, 85, 148, 0.19);
}

.species-card.active {
  background: #ffffff;
  border-color: #66b2ff;
  box-shadow: 0 0 0 4px rgba(102, 178, 255, 0.28), 0 22px 48px rgba(42, 85, 148, 0.2);
}

.selected-heart-doodle {
  position: absolute;
  right: -18px;
  top: 44%;
  width: 78px;
  height: 78px;
  z-index: 4;
  pointer-events: none;
  filter: drop-shadow(0 4px 10px rgba(141, 107, 255, 0.25));
}

.card-art-box {
  width: 100%;
  aspect-ratio: 1 / 0.92;
  border-radius: 22px;
  background: linear-gradient(180deg, #b8daff 0%, #dceeff 100%);
  overflow: hidden;
  position: relative;
}

.art-single {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.art-dual {
  width: 100%;
  height: 100%;
  position: relative;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 3px;
}

.art-dual-cat,
.art-dual-dog {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.card-label {
  font-size: 20px;
  font-weight: 700;
  color: #121628;
}

.card-sub {
  font-size: 12px;
  color: #536478;
}

.bottom-cta {
  display: flex;
  justify-content: center;
}

.next-btn {
  min-width: 210px;
  height: 48px;
  font-size: 16px;
}
</style>
