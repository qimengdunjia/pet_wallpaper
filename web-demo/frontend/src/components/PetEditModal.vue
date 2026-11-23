<!-- 文件用途：展示已选宠物的证件卡并保存可编辑的档案字段。 -->
<script setup lang="ts">
import backChevron from "@/assets/mastergo/back-chevron.svg";
import profileCardArt from "@/assets/mastergo/edit-card-frame.svg";
import profileCardForeground from "@/assets/mastergo/edit-card-foreground.svg";
import profileCardWordmark from "@/assets/mastergo/edit-card-wordmark.svg";
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
    class="sky-full-overlay edit-screen mastergo-cloud-sky"
    data-testid="pet-edit-modal"
    @click.stop
  >
    <img :src="profileCardArt" alt="" class="profile-card-art" />
    <img :src="profileCardForeground" alt="" class="profile-card-foreground" />

    <header class="edit-top">
      <button
        class="circle-back-btn"
        aria-label="返回"
        data-testid="edit-pet-cancel-btn"
        @click="handleCancel"
      >
        <img :src="backChevron" alt="" />
      </button>
      <h1>编辑宠物信息</h1>
    </header>

    <div class="house-wrapper">
      <div class="house-body">
        <img :src="profileCardWordmark" alt="" class="id-card-watermark" />

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
  background: var(--bg-profile-sky);
}

.edit-top {
  position: absolute;
  top: calc(50% - 559 * var(--mastergo-unit));
  left: calc(50% - 1196 * var(--mastergo-unit));
  display: flex;
  align-items: center;
  gap: calc(48 * var(--mastergo-unit));
  z-index: 3;
}

.edit-top h1 {
  margin: 0;
  font-size: clamp(16px, calc(48 * var(--mastergo-unit)), 48px);
  font-weight: 500;
  color: #2c2c2c;
}

.edit-top .circle-back-btn {
  width: calc(100 * var(--mastergo-unit));
  height: calc(100 * var(--mastergo-unit));
}

.edit-top .circle-back-btn img {
  width: calc(15 * var(--mastergo-unit));
  height: calc(25 * var(--mastergo-unit));
}

.house-wrapper {
  position: absolute;
  top: 34.444vh;
  width: min(64.53125vw, 114.7222vh);
  z-index: 2;
}

.house-body {
  position: relative;
  padding: 0 4.84%;
}

.id-card-watermark {
  position: absolute;
  right: calc(109 * var(--mastergo-unit));
  top: calc(-90 * var(--mastergo-unit));
  width: calc(320 * var(--mastergo-unit));
  pointer-events: none;
}

.edit-grid {
  display: grid;
  grid-template-columns: minmax(0, 480fr) minmax(0, 952fr);
  gap: 4.02%;
  align-items: center;
}

.edit-photo-frame {
  width: 100%;
  height: min(23.4375vw, 41.6667vh);
  border-radius: clamp(12px, 1.875vw, 48px);
  overflow: hidden;
  background: var(--surface-frame-blue);
}

.edit-photo-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.edit-form {
  height: min(23.4375vw, 41.6667vh);
  padding: calc(48 * var(--mastergo-unit)) calc(80 * var(--mastergo-unit)) 0;
  display: flex;
  flex-direction: column;
  gap: calc(48 * var(--mastergo-unit));
  border-radius: clamp(12px, 1.875vw, 48px);
  background: #fff;
}

.form-section-title {
  text-align: center;
  height: calc(48 * var(--mastergo-unit));
  line-height: calc(48 * var(--mastergo-unit));
  font-size: clamp(12px, calc(36 * var(--mastergo-unit)), 36px);
  font-weight: 500;
  color: #2c2c2c;
}

.form-row {
  display: grid;
  grid-template-columns: calc(160 * var(--mastergo-unit)) minmax(0, 1fr);
  align-items: center;
  gap: calc(32 * var(--mastergo-unit));
}

.row-label {
  font-size: clamp(11px, calc(32 * var(--mastergo-unit)), 32px);
  font-weight: 400;
  color: #666;
  white-space: nowrap;
}

.gender-pair {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: calc(32 * var(--mastergo-unit));
}

.edit-form :is(.input-field, .gender-btn) {
  height: calc(100 * var(--mastergo-unit));
  min-height: 0;
  border: 0;
  border-radius: calc(24 * var(--mastergo-unit));
  background: rgba(79, 108, 164, 0.08);
  color: #121628;
  font-size: clamp(11px, calc(32 * var(--mastergo-unit)), 32px);
  font-weight: 400;
}

.edit-form .input-field {
  padding: 0 calc(34 * var(--mastergo-unit));
}

.edit-form .gender-btn.active {
  background: #ddfd66;
}

.save-cta-btn {
  position: absolute;
  left: 50%;
  top: calc(100% + 3.89vh);
  transform: translateX(-50%);
  min-width: max(105px, 16.406vw);
  height: max(36px, 8.333vh);
  font-size: 16px;
  z-index: 5;
}

.save-cta-btn:active:not(:disabled) {
  transform: translateX(-50%) scale(0.97);
}

@media (max-height: 440px) {
  .house-wrapper {
    top: 31vh;
  }

  .edit-form {
    gap: 8px;
    padding-top: 7px;
  }

  .edit-form :is(.input-field, .gender-btn) {
    min-height: 24px;
    height: 25px;
    padding-block: 0;
  }

  .form-row {
    grid-template-columns: 65px minmax(0, 1fr);
    gap: 4px;
  }
}
</style>
