<!-- 文件用途：按类型浏览已有宠物，并打开壁纸切换确认页。 -->
<script setup lang="ts">
import backChevron from "@/assets/mastergo/back-chevron.svg";
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import tabUnderline from "@/assets/mastergo/selector-tab-underline.svg";
import selectorChevron from "@/assets/mastergo/selector-chevron.svg";
import catIllustration from "@/assets/mastergo/cat.png";
import dogIllustration from "@/assets/mastergo/dog-happy.png";
import { createIdempotencyKey, submitGeneration } from "@/lib/api";
import { deletePetProfile, startWaitingBatch, trackJob } from "@/stores/generationStore";
import PetDeleteConfirmModal from "@/components/PetDeleteConfirmModal.vue";
import { getPetsBySpecies, upsertPet } from "@/stores/petStore";
import { closePetSelector, findPetByIdSafe, playerState } from "@/stores/playerHelpers";
import { guardParkedAction, setRoute, showToast, systemState } from "@/stores/systemStore";
import type { PetProfile, Species } from "@/types";

const activeTab = ref<Species>("dog");
const focusedIndex = ref(0);
const stripRef = ref<HTMLElement | null>(null);
const isOverflowing = ref(false);
const pendingDeletePet = ref<PetProfile | null>(null);
const deleting = ref(false);
let stripResizeObserver: ResizeObserver | null = null;

function updateOverflowState() {
  const strip = stripRef.value;
  isOverflowing.value = Boolean(strip && strip.scrollWidth > strip.clientWidth + 2);
}

onMounted(() => {
  if (typeof ResizeObserver !== "undefined") {
    stripResizeObserver = new ResizeObserver(() => updateOverflowState());
    if (stripRef.value) stripResizeObserver.observe(stripRef.value);
  }
});

onBeforeUnmount(() => {
  stripResizeObserver?.disconnect();
  stripResizeObserver = null;
});

watch(stripRef, (el, oldEl) => {
  if (oldEl) stripResizeObserver?.unobserve(oldEl);
  if (el) {
    stripResizeObserver?.observe(el);
    void nextTick().then(updateOverflowState);
  }
});

async function scrollFocusedCardIntoView(behavior: ScrollBehavior = "smooth") {
  await nextTick();
  updateOverflowState();
  const strip = stripRef.value;
  if (!strip) return;
  const card = strip.children[focusedIndex.value] as HTMLElement | undefined;
  if (!card) return;
  const targetLeft = card.offsetLeft - (strip.clientWidth - card.offsetWidth) / 2;
  const maxLeft = Math.max(0, strip.scrollWidth - strip.clientWidth);
  const clampedLeft = Math.max(0, Math.min(maxLeft, targetLeft));
  if (typeof strip.scrollTo === "function") {
    strip.scrollTo({ left: clampedLeft, behavior });
  } else {
    strip.scrollLeft = clampedLeft;
  }
}

watch(
  () => playerState.selectorOpen,
  (open) => {
    if (open) {
      const current = findPetByIdSafe(playerState.currentPetId);
      activeTab.value = current?.species || "dog";
      const list = getPetsBySpecies(activeTab.value);
      const idx = list.findIndex((p) => p.id === playerState.currentPetId);
      focusedIndex.value = idx >= 0 ? idx : 0;
      void scrollFocusedCardIntoView("auto");
    }
  },
);

watch(activeTab, (species) => {
  const list = getPetsBySpecies(species);
  const idx = list.findIndex((p) => p.id === playerState.currentPetId);
  focusedIndex.value = idx >= 0 ? idx : 0;
  void scrollFocusedCardIntoView("auto");
});

const filteredPets = computed(() => getPetsBySpecies(activeTab.value));
const catCount = computed(() => getPetsBySpecies("cat").length);
const dogCount = computed(() => getPetsBySpecies("dog").length);

watch(filteredPets, (list) => {
  if (focusedIndex.value >= list.length) {
    focusedIndex.value = Math.max(0, list.length - 1);
  }
});

watch(focusedIndex, () => {
  if (playerState.selectorOpen) {
    void scrollFocusedCardIntoView("smooth");
  }
});

const focusedPet = computed(() => filteredPets.value[focusedIndex.value] || null);

function statusInfo(pet: PetProfile): { text: string; tone: string; selectable: boolean } {
  if (pet.id === playerState.currentPetId) {
    return { text: "当前使用", tone: "success", selectable: true };
  }
  if (pet.is_default) {
    return { text: "默认壁纸", tone: "info", selectable: true };
  }
  const job = pet.latest_job;
  if (job && (job.status === "queued" || job.status === "generating")) {
    return { text: `生成中 ${job.progress}%`, tone: "info", selectable: false };
  }
  if (pet.active_assets && pet.active_version_id) {
    return { text: "已就绪", tone: "success", selectable: true };
  }
  if (job?.status === "failed") {
    return { text: "生成失败", tone: "danger", selectable: false };
  }
  return { text: "未生成", tone: "warning", selectable: false };
}

function stepFocus(delta: number) {
  const len = filteredPets.value.length;
  if (len <= 1) return;
  focusedIndex.value = (focusedIndex.value + delta + len) % len;
}

function focusPetAt(idx: number) {
  if (idx < 0 || idx >= filteredPets.value.length) return;
  focusedIndex.value = idx;
}

function handleStripWheel(event: WheelEvent) {
  const strip = stripRef.value;
  if (!strip || strip.scrollWidth <= strip.clientWidth) return;
  if (Math.abs(event.deltaY) > Math.abs(event.deltaX) && event.deltaY !== 0) {
    event.preventDefault();
    if (typeof strip.scrollBy === "function") {
      strip.scrollBy({ left: event.deltaY, behavior: "auto" });
    } else {
      strip.scrollLeft += event.deltaY;
    }
  }
}

function handleSelectPet(pet: PetProfile, idx: number) {
  focusedIndex.value = idx;
  const info = statusInfo(pet);
  if (!info.selectable) {
    if (pet.latest_job?.status === "queued" || pet.latest_job?.status === "generating") {
      showToast(`${pet.name} 正在后台生成中，完成后即可选择`, "info");
    }
    return;
  }
  playerState.confirmingPetId = pet.id;
}

function handleSetFocusedWallpaper() {
  if (!focusedPet.value) return;
  handleSelectPet(focusedPet.value, focusedIndex.value);
}

async function handleRetryPet(pet: PetProfile) {
  if (!guardParkedAction("重试生成")) return;
  try {
    const res = await submitGeneration({
      petId: pet.id,
      idempotencyKey: createIdempotencyKey("retry"),
      mockDelaySeconds: systemState.config?.mock_controls_enabled ? 1.8 : undefined,
    });
    if (res.pet) upsertPet(res.pet);
    trackJob(res.job);
    closePetSelector();
    startWaitingBatch([res.job.id]);
    setRoute("generating");
  } catch (err) {
    showToast(err instanceof Error ? err.message : "重试失败", "error");
  }
}

function handleAddFromSelector() {
  if (!guardParkedAction("添加宠物")) return;
  closePetSelector();
  systemState.onboardingReturnRoute = "wallpaper";
  systemState.onboardingSpeciesMode = null;
  setRoute("onboarding-species");
}

function requestDeletePet(pet: PetProfile) {
  if (pet.is_default || deleting.value) return;
  if (!guardParkedAction("删除宠物")) return;
  pendingDeletePet.value = pet;
}

async function confirmDeletePet() {
  if (!pendingDeletePet.value || deleting.value) return;
  deleting.value = true;
  try {
    const ok = await deletePetProfile(pendingDeletePet.value);
    if (ok) {
      pendingDeletePet.value = null;
    }
  } finally {
    deleting.value = false;
  }
}
</script>

<template>
  <div
    v-if="playerState.selectorOpen && !playerState.confirmingPetId && !playerState.editingPetId"
    class="sky-full-overlay selector-screen mastergo-cloud-sky"
    data-testid="pet-selector-modal"
    @click.stop
  >
    <!-- 顶部栏：左上返回钮 + 居中标题 + 右上添加宠物 -->
    <header class="selector-header">
      <button
        class="circle-back-btn"
        aria-label="返回壁纸"
        data-testid="selector-cancel-btn"
        @click="closePetSelector"
      >
        <img :src="backChevron" alt="" />
      </button>

      <h1>选择一只宠物</h1>

      <button
        class="btn btn-ghost btn-sm"
        data-testid="selector-add-pet-btn"
        @click="handleAddFromSelector"
      >
        + 添加宠物
      </button>
    </header>

    <!-- 当前分类使用 MasterGo 原始下划线。 -->
    <div class="species-tabs-row">
      <button
        class="species-tab"
        :class="{ active: activeTab === 'dog' }"
        data-testid="selector-tab-dog"
        @click="activeTab = 'dog'"
      >
        <span>狗狗 ({{ dogCount }})</span>
        <img v-if="activeTab === 'dog'" :src="tabUnderline" alt="" class="green-squiggle" />
      </button>

      <button
        class="species-tab"
        :class="{ active: activeTab === 'cat' }"
        data-testid="selector-tab-cat"
        @click="activeTab = 'cat'"
      >
        <span>猫咪 ({{ catCount }})</span>
        <img v-if="activeTab === 'cat'" :src="tabUnderline" alt="" class="green-squiggle" />
      </button>
    </div>

    <!-- 中央聚焦式轮播卡片区 -->
    <div v-if="filteredPets.length > 0" class="carousel-stage">
      <button
        v-if="filteredPets.length > 1"
        class="circle-back-btn arrow-nav"
        aria-label="上一只"
        data-testid="selector-prev-btn"
        @click="stepFocus(-1)"
      >
        <img :src="selectorChevron" alt="" class="arrow-prev" />
      </button>

      <div
        ref="stripRef"
        class="pet-cards-strip"
        :class="{ 'is-overflowing': isOverflowing }"
        @wheel="handleStripWheel"
      >
        <div
          v-for="(pet, idx) in filteredPets"
          :key="pet.id"
          class="pet-carousel-card"
          :class="{
            focused: idx === focusedIndex,
            active: pet.id === playerState.currentPetId,
            disabled: !statusInfo(pet).selectable,
          }"
          :data-testid="`selector-pet-card-${pet.id}`"
          :data-pet-name="pet.name"
          @click="handleSelectPet(pet, idx)"
        >
          <div class="card-blue-frame">
            <button
              v-if="!pet.is_default"
              type="button"
              class="card-delete-btn"
              :aria-label="`删除 ${pet.name}`"
              :data-testid="`selector-delete-pet-btn-${pet.id}`"
              @click.stop="requestDeletePet(pet)"
            >
              <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                <path
                  d="M4 4l8 8M12 4l-8 8"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                />
              </svg>
            </button>
            <img
              :src="pet.active_assets?.idle_image.url || pet.original_photo_url || (pet.species === 'dog' ? dogIllustration : catIllustration)"
              :alt="pet.name"
              class="pet-thumb"
              :class="{ 'pet-thumb-placeholder': !pet.active_assets?.idle_image.url && !pet.original_photo_url }"
            />
            <span class="pill-tag status-badge" :class="statusInfo(pet).tone">
              {{ statusInfo(pet).text }}
            </span>

            <div class="card-name-ribbon">
              <strong>{{ pet.name }}</strong>
              <span>{{ pet.breed || (pet.species === "cat" ? "猫咪" : "狗狗") }} · {{ pet.gender }}</span>
            </div>
          </div>

          <button
            v-if="pet.latest_job?.status === 'failed' && !pet.active_assets"
            class="btn btn-black btn-sm retry-mini"
            @click.stop="handleRetryPet(pet)"
          >
            重新生成
          </button>
        </div>
      </div>

      <button
        v-if="filteredPets.length > 1"
        class="circle-back-btn arrow-nav"
        aria-label="下一只"
        data-testid="selector-next-btn"
        @click="stepFocus(1)"
      >
        <img :src="selectorChevron" alt="" />
      </button>
    </div>

    <div v-else class="empty-pets">
      <p>该分类暂无宠物档案，可点击右上角「+ 添加宠物」上传照片生成。</p>
    </div>

    <div v-if="filteredPets.length > 1" class="carousel-dots" role="tablist" aria-label="宠物分页指示">
      <button
        v-for="(pet, idx) in filteredPets"
        :key="pet.id"
        type="button"
        class="carousel-dot"
        :class="{ active: idx === focusedIndex }"
        :aria-label="`定位到 ${pet.name}`"
        :aria-selected="idx === focusedIndex"
        :data-testid="`selector-dot-${idx}`"
        @click="focusPetAt(idx)"
      />
    </div>

    <div class="selector-footer">
      <button
        class="btn btn-black set-btn"
        :disabled="!focusedPet || !statusInfo(focusedPet).selectable"
        @click="handleSetFocusedWallpaper"
      >
        设为壁纸
      </button>
    </div>

    <PetDeleteConfirmModal
      :pet="pendingDeletePet"
      :deleting="deleting"
      @cancel="pendingDeletePet = null"
      @confirm="confirmDeletePet"
    />
  </div>
</template>

<style scoped>
.selector-screen {
  justify-content: space-between;
  gap: 12px;
  padding-top: max(50px, 10.625vh);
  padding-bottom: max(48px, 13.33vh);
}

.selector-header {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  gap: 8px;
}

.selector-header > :first-child {
  justify-self: start;
}

.selector-header > :last-child {
  justify-self: end;
}

.selector-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: #121628;
}

.species-tabs-row {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: 36px;
}

.species-tab {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  font-size: 16px;
  font-weight: 500;
  color: #536478;
  padding: 4px 10px;
}

.species-tab.active {
  font-size: 18px;
  font-weight: 700;
  color: #121628;
}

.green-squiggle {
  width: clamp(45px, 5.234vw, 134px);
  height: auto;
}

.carousel-stage {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
  min-height: 0;
}

.arrow-nav {
  background: rgba(38, 74, 135, 0.24);
}

.arrow-nav img {
  width: 10px;
  height: 19px;
}

.arrow-prev {
  transform: scaleX(-1);
}

.pet-cards-strip {
  position: relative;
  flex: 0 1 auto;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 24px;
  max-width: min(1560px, 100%);
  overflow-x: auto;
  scroll-behavior: smooth;
  scroll-snap-type: x proximity;
  scrollbar-width: none;
  -ms-overflow-style: none;
  padding: clamp(12px, 1.8vh, 22px) 28px;
}

.pet-cards-strip.is-overflowing {
  -webkit-mask-image: linear-gradient(to right, transparent 0, #000 32px, #000 calc(100% - 32px), transparent 100%);
  mask-image: linear-gradient(to right, transparent 0, #000 32px, #000 calc(100% - 32px), transparent 100%);
}

.pet-cards-strip::-webkit-scrollbar {
  display: none;
}

.pet-cards-strip > :first-child {
  margin-left: auto;
}

.pet-cards-strip > :last-child {
  margin-right: auto;
}

.pet-carousel-card {
  flex: 0 0 clamp(94px, 17.1875vw, 440px);
  scroll-snap-align: center;
  padding: clamp(5px, 1.15vw, 30px);
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.72);
  border: 2px solid rgba(255, 255, 255, 0.9);
  box-shadow: 0 12px 30px rgba(42, 85, 148, 0.12);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  gap: 8px;
  transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}

.pet-carousel-card.focused {
  flex: 0 0 clamp(114px, 21.5625vw, 552px);
  background: #ffffff;
  transform: translateY(-4px);
  box-shadow: 0 20px 44px rgba(42, 85, 148, 0.2);
}

.pet-carousel-card.active {
  border-color: #4981f2;
}

.pet-carousel-card.disabled {
  cursor: not-allowed;
}

.card-blue-frame {
  position: relative;
  width: 100%;
  height: clamp(95px, 35.4167vh, 510px);
  border-radius: 22px;
  overflow: hidden;
  background: linear-gradient(180deg, #49a1ff 0%, #beddff 100%);
}

.focused .card-blue-frame {
  height: clamp(105px, 40.6944vh, 586px);
}

.pet-thumb {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.pet-thumb-placeholder {
  object-fit: contain;
}

.status-badge {
  position: absolute;
  top: 10px;
  right: 10px;
}

.card-delete-btn {
  position: absolute;
  top: 10px;
  left: 10px;
  z-index: 2;
  width: 28px;
  height: 28px;
  padding: 0;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid rgba(255, 255, 255, 0.92);
  color: #536478;
  box-shadow: 0 2px 8px rgba(18, 28, 79, 0.14);
  transition: background-color 0.15s ease, color 0.15s ease, border-color 0.15s ease, transform 0.12s ease;
}

.card-delete-btn:hover {
  background: #e24f4f;
  border-color: #e24f4f;
  color: #ffffff;
}

.card-name-ribbon {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  padding: 12px 14px;
  background: rgba(114, 160, 218, 0.76);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  color: #ffffff;
  display: flex;
  flex-direction: column;
  gap: 2px;
  text-align: center;
}

.card-name-ribbon strong {
  font-size: 16px;
}

.card-name-ribbon span {
  font-size: 11.5px;
  opacity: 0.92;
}

.retry-mini {
  align-self: center;
}

.empty-pets {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 28px;
  background: rgba(255, 255, 255, 0.56);
  color: #536478;
  font-size: 15px;
}

.carousel-dots {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 14px;
}

.carousel-dot {
  width: 8px;
  height: 8px;
  padding: 0;
  border-radius: 999px;
  background: rgba(38, 74, 135, 0.22);
  transition: width 0.22s ease, background-color 0.22s ease, opacity 0.22s ease;
}

.carousel-dot:hover {
  background: rgba(38, 74, 135, 0.42);
}

.carousel-dot.active {
  width: 24px;
  background: #4981f2;
}

.selector-footer {
  display: flex;
  justify-content: center;
}

.set-btn {
  min-width: max(112px, 16.40625vw);
  height: clamp(35px, 8.333vh, 120px);
  font-size: clamp(13px, 1.45vw, 37px);
}

@media (max-height: 500px) {
  .selector-screen {
    gap: 4px;
    padding-inline: 12px;
  }

  .selector-header h1 {
    font-size: 18px;
  }

  .pet-cards-strip {
    padding: 10px 8px;
  }

  .carousel-dots {
    height: 10px;
    gap: 6px;
  }

  .card-blue-frame {
    height: 25vh;
  }

  .focused .card-blue-frame {
    height: 29vh;
  }
}
</style>
