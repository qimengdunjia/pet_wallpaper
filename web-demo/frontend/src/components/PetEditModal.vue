<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { updatePet } from "@/lib/api";
import { findPetById, upsertPet } from "@/stores/petStore";
import { playerState } from "@/stores/playerStore";
import { guardParkedAction, showToast } from "@/stores/systemStore";
import type { Gender } from "@/types";

const targetPet = computed(() => findPetById(playerState.editingPetId));
const name = ref("");
const gender = ref<Gender>("未设置");
const breed = ref("");
const saving = ref(false);

watch(
  targetPet,
  (pet) => {
    if (pet) {
      name.value = pet.name;
      gender.value = pet.gender;
      breed.value = pet.breed;
    }
  },
  { immediate: true },
);

function toggleGender(val: "弟弟" | "妹妹") {
  gender.value = gender.value === val ? "未设置" : val;
}

function handleCancel() {
  playerState.editingPetId = null;
}

async function handleSave() {
  if (!targetPet.value || saving.value) return;
  if (!guardParkedAction("保存宠物资料")) return;
  const trimmedName = name.value.trim();
  if (!trimmedName) {
    showToast("请输入宠物爱称", "warning");
    return;
  }
  saving.value = true;
  try {
    const updated = await updatePet(targetPet.value.id, {
      name: trimmedName,
      gender: gender.value,
      breed: breed.value.trim(),
    });
    upsertPet(updated);
    showToast("宠物信息已保存", "success", 2200);
    playerState.editingPetId = null;
  } catch (err) {
    showToast(err instanceof Error ? err.message : "保存失败", "error");
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div
    v-if="playerState.editingPetId && targetPet"
    class="sky-full-overlay edit-screen"
    data-testid="pet-edit-modal"
    @click.stop
  >
    <svg class="deco-burst" viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <path
        d="M60,8 L72,34 L98,20 L86,46 L114,56 L88,68 L104,94 L74,84 L62,112 L48,84 L18,94 L32,68 L6,56 L34,46 L22,20 L48,34 Z"
        fill="#6DA3FF"
        opacity="0.72"
      />
    </svg>

    <header class="edit-top">
      <button
        class="circle-back-btn"
        aria-label="返回"
        data-testid="edit-pet-cancel-btn"
        @click="handleCancel"
      >
        <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12.5 5 7.5 10l5 5" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
      </button>
      <h1>编辑宠物信息</h1>
    </header>

    <div class="house-wrapper">
      <svg class="ribbon-deco" viewBox="0 0 120 120" fill="none" aria-hidden="true">
        <path
          d="M20,90 C28,42 54,18 92,22"
          stroke="#276ADE"
          stroke-width="22"
          stroke-linecap="round"
        />
      </svg>

      <svg class="house-roof" viewBox="0 0 1000 90" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0,90 L0,76 L486,6 Q500,2 514,6 L1000,76 L1000,90 Z" fill="#FFFFFF" />
      </svg>

      <div class="house-body">
        <div class="id-card-watermark" aria-hidden="true">ID CARD</div>

        <div class="edit-grid">
          <div class="edit-photo-frame">
            <img
              :src="targetPet.active_assets?.idle_image.url || targetPet.original_photo_url || ''"
              :alt="targetPet.name"
            />
          </div>

          <div class="edit-form">
            <div class="form-section-title">宠物信息</div>

            <div class="form-row">
              <span class="row-label">宠物爱称：</span>
              <input
                v-model="name"
                type="text"
                maxlength="40"
                class="input-field"
                data-testid="edit-pet-name-input"
              />
            </div>

            <div class="form-row">
              <span class="row-label">宠物性别：</span>
              <div class="gender-pair">
                <button
                  v-for="g in (['弟弟', '妹妹'] as const)"
                  :key="g"
                  type="button"
                  class="gender-btn"
                  :class="{ active: gender === g }"
                  :data-testid="`edit-pet-gender-${g}`"
                  @click="toggleGender(g)"
                >
                  {{ g }}
                </button>
              </div>
            </div>

            <div class="form-row">
              <span class="row-label">宠物品种：</span>
              <input
                v-model="breed"
                type="text"
                maxlength="40"
                class="input-field"
                data-testid="edit-pet-breed-input"
              />
            </div>
          </div>
        </div>
      </div>

      <button
        class="btn btn-black save-cta-btn"
        :disabled="saving"
        data-testid="edit-pet-save-btn"
        @click="handleSave"
      >
        {{ saving ? "保存中..." : "保存" }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.edit-screen {
  align-items: center;
  justify-content: space-between;
  padding: 50px 44px 54px;
}

.deco-burst {
  position: absolute;
  right: -12px;
  bottom: 92px;
  width: 112px;
  height: 112px;
  pointer-events: none;
  z-index: 1;
}

.edit-top {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 14px;
}

.edit-top h1 {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: #121628;
}

.house-wrapper {
  position: relative;
  width: min(900px, 90vw);
  margin-bottom: 16px;
  filter: drop-shadow(0 20px 48px rgba(42, 85, 148, 0.16));
}

.ribbon-deco {
  position: absolute;
  left: 52%;
  top: -36px;
  width: 62px;
  height: 62px;
  pointer-events: none;
  z-index: 1;
}

.house-roof {
  display: block;
  width: 100%;
  height: 54px;
  margin-bottom: -2px;
  position: relative;
  z-index: 2;
}

.house-body {
  position: relative;
  z-index: 2;
  background: #ffffff;
  border-radius: 0 0 36px 36px;
  padding: 16px 42px 48px;
}

.id-card-watermark {
  position: absolute;
  right: 36px;
  top: -12px;
  font-size: 28px;
  font-weight: 800;
  letter-spacing: 0.04em;
  color: #8fc4ff;
  pointer-events: none;
}

.edit-grid {
  display: grid;
  grid-template-columns: 270px 1fr;
  gap: 32px;
  align-items: center;
}

.edit-photo-frame {
  width: 100%;
  height: 244px;
  border-radius: 26px;
  overflow: hidden;
  background: var(--surface-frame-blue);
}

.edit-photo-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.edit-form {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.form-section-title {
  text-align: center;
  font-size: 16px;
  font-weight: 700;
  color: #121628;
}

.form-row {
  display: grid;
  grid-template-columns: 78px 1fr;
  align-items: center;
  gap: 10px;
}

.row-label {
  font-size: 13px;
  font-weight: 600;
  color: #536478;
}

.gender-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.gender-btn {
  height: 40px;
  border-radius: 13px;
  background: #eff2f7;
  color: #121628;
  font-size: 14px;
  font-weight: 600;
}

.gender-btn.active {
  background: #ddfd66;
  color: #121628;
}

.save-cta-btn {
  position: absolute;
  left: 50%;
  bottom: -24px;
  transform: translateX(-50%);
  min-width: 210px;
  height: 48px;
  font-size: 16px;
  z-index: 5;
}

.save-cta-btn:active:not(:disabled) {
  transform: translateX(-50%) scale(0.97);
}
</style>
