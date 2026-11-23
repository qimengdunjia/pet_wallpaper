<!-- 文件用途：预览待切换壁纸、进入档案编辑或确认切换。 -->
<script setup lang="ts">
import backChevron from "@/assets/mastergo/back-chevron.svg";
import catIllustration from "@/assets/mastergo/cat.png";
import wallpaperScene from "@/assets/mastergo/wallpaper-scene.png";
import { computed, ref } from "vue";
import { findPetById } from "@/stores/petStore";
import { activatePetWallpaper, closePetSelector, playerState } from "@/stores/playerStore";
import { guardParkedAction, showToast } from "@/stores/systemStore";

const switching = ref(false);
const targetPet = computed(() => findPetById(playerState.confirmingPetId));
const petPreview = computed(
  () => targetPet.value?.active_assets?.idle_image.url || targetPet.value?.original_photo_url,
);

function handleBackToList() {
  playerState.confirmingPetId = null;
}

function handleOpenEdit() {
  if (!targetPet.value) return;
  if (!guardParkedAction("编辑宠物信息")) return;
  playerState.editingPetId = targetPet.value.id;
}

async function handleConfirmUse() {
  if (!targetPet.value || switching.value) return;
  if (!guardParkedAction("切换宠物壁纸")) return;
  switching.value = true;
  try {
    const res = await activatePetWallpaper(targetPet.value, { persist: true });
    if (res.ok) {
      showToast(`已切换至 ${targetPet.value.name}`, "success", 2400);
      closePetSelector();
    } else {
      showToast(res.reason || "切换失败，已保留原壁纸", "error", 4200);
      closePetSelector();
    }
  } finally {
    switching.value = false;
  }
}
</script>

<template>
  <div
    v-if="playerState.selectorOpen && targetPet && !playerState.editingPetId"
    class="sky-full-overlay confirm-screen mastergo-cloud-sky"
    data-testid="pet-confirm-modal"
    @click.stop
  >
    <header class="confirm-header">
      <button
        class="circle-back-btn"
        aria-label="返回宠物列表"
        data-testid="confirm-back-list-btn"
        @click="handleBackToList"
      >
        <img :src="backChevron" alt="" />
      </button>
      <h1>选择一只宠物</h1>
      <span class="header-spacer" />
    </header>

    <div class="confirm-body">
      <div class="confirm-preview-box">
        <div class="confirm-img-frame">
          <img
            :src="petPreview || (targetPet.species === 'cat' ? catIllustration : wallpaperScene)"
            :class="{ 'confirm-art-placeholder': !petPreview && targetPet.species === 'cat' }"
            :alt="petPreview ? targetPet.name : '宠物壁纸示例'"
          />
        </div>
      </div>

      <div class="confirm-right-col">
        <h2 class="pet-hero-name sky-gradient-title">{{ targetPet.name }}</h2>

        <div class="meta-line">
          <span>{{ targetPet.breed || (targetPet.species === "cat" ? "猫咪" : "狗狗") }}</span>
          <span class="gender-badge">
            {{ targetPet.gender === "弟弟" ? "♂ 弟弟" : targetPet.gender === "妹妹" ? "♀ 妹妹" : "未设置" }}
          </span>
        </div>

        <div class="confirm-actions-stack">
          <button
            v-if="!targetPet.is_default"
            class="btn btn-soft stack-btn"
            data-testid="confirm-edit-info-btn"
            @click="handleOpenEdit"
          >
            编辑信息
          </button>
          <button
            class="btn btn-black stack-btn"
            :disabled="switching"
            data-testid="confirm-use-pet-btn"
            @click="handleConfirmUse"
          >
            {{ switching ? "加载验证中..." : "设为壁纸" }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.confirm-screen {
  justify-content: space-between;
  padding-top: max(50px, 10.625vh);
}

.confirm-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.confirm-header h1 {
  margin: 0;
  font-size: 24px;
  font-weight: 600;
  color: #121628;
}

.header-spacer {
  width: 42px;
}

.confirm-body {
  flex: 1;
  width: min(82.62vw, 146.875vh);
  margin: 0 auto;
  display: grid;
  grid-template-columns: minmax(0, 1323fr) minmax(0, 600fr);
  gap: 9.08%;
  align-items: center;
}

.confirm-preview-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.confirm-img-frame {
  width: 100%;
  aspect-ratio: 1323 / 799;
  border-radius: clamp(14px, calc(50.49 * var(--mastergo-unit)), 51px);
  padding: clamp(7px, 2.46vw, 63px);
  background: rgba(255, 255, 255, 0.4);
}

.confirm-img-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 22px;
  background: var(--surface-frame-blue);
}

.confirm-img-frame .confirm-art-placeholder {
  object-fit: contain;
}

.confirm-right-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}

.pet-hero-name {
  margin: 0;
  font-size: clamp(24px, 4.1vw, 105px);
  font-weight: 800;
  line-height: 1.08;
  text-align: center;
  word-break: break-word;
}

.meta-line {
  display: flex;
  align-items: center;
  gap: 28px;
  font-size: 16px;
  font-weight: 600;
  color: #121628;
}

.gender-badge {
  color: #2563eb;
}

.confirm-actions-stack {
  margin-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  width: 100%;
}

.stack-btn {
  width: 100%;
  height: clamp(35px, 8.33vh, 120px);
  font-size: clamp(13px, 1.45vw, 37px);
}

@media (max-height: 500px) {
  .confirm-screen {
    padding-inline: 18px;
  }

  .confirm-right-col,
  .confirm-actions-stack {
    gap: 8px;
  }

  .confirm-actions-stack {
    margin-top: 0;
  }

  .meta-line {
    gap: 8px;
    font-size: 12px;
  }
}
</style>
