<script setup lang="ts">
import { computed, ref } from "vue";
import { findPetById } from "@/stores/petStore";
import { activatePetWallpaper, closePetSelector, playerState } from "@/stores/playerStore";
import { guardParkedAction, showToast } from "@/stores/systemStore";

const switching = ref(false);
const targetPet = computed(() => findPetById(playerState.confirmingPetId));

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
    class="sky-full-overlay confirm-screen"
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
        <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12.5 5 7.5 10l5 5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <h1>选择一只宠物</h1>
      <span class="header-spacer" />
    </header>

    <div class="confirm-body">
      <div class="confirm-preview-box">
        <div class="confirm-img-frame">
          <img
            :src="targetPet.active_assets?.idle_image.url || targetPet.original_photo_url || ''"
            :alt="targetPet.name"
          />
        </div>
        <p class="preview-caption">加载已生成形象与互动动画，不再重新生成 AI 资源</p>
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
  width: min(1060px, 94vw);
  margin: 0 auto;
  display: grid;
  grid-template-columns: 1.45fr 1fr;
  gap: 54px;
  align-items: center;
}

.confirm-preview-box {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.confirm-img-frame {
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: 30px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.72);
  border: 2px solid rgba(255, 255, 255, 0.94);
  box-shadow: 0 20px 46px rgba(42, 85, 148, 0.16);
}

.confirm-img-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: 22px;
  background: var(--surface-frame-blue);
}

.preview-caption {
  margin: 0;
  text-align: center;
  font-size: 12.5px;
  color: #536478;
}

.confirm-right-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 18px;
}

.pet-hero-name {
  margin: 0;
  font-size: 56px;
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
  width: 230px;
}

.stack-btn {
  width: 100%;
  height: 48px;
  font-size: 15px;
}
</style>
