<!-- 文件用途：删除宠物前的二次确认弹窗，提示关联素材清理与当前壁纸回退影响。 -->
<script setup lang="ts">
import { computed } from "vue";
import { playerState } from "@/stores/playerHelpers";
import type { PetProfile } from "@/types";

const props = defineProps<{
  pet: PetProfile | null;
  deleting?: boolean;
}>();

const emit = defineEmits<{
  cancel: [];
  confirm: [];
}>();

const description = computed(() => {
  const pet = props.pet;
  if (!pet) return "";
  if (pet.id === playerState.currentPetId) {
    return `确定要删除「${pet.name}」吗？删除后将清除该宠物的档案与壁纸素材，并自动切换至其他可用壁纸。`;
  }
  if (pet.latest_job?.status === "queued" || pet.latest_job?.status === "generating") {
    return `「${pet.name}」正在后台生成壁纸，确定要取消生成并删除该宠物档案吗？`;
  }
  return `确定要删除「${pet.name}」吗？删除后该宠物的档案与已生成壁纸素材将一并清除，且不可恢复。`;
});
</script>

<template>
  <div
    v-if="pet"
    class="modal-backdrop"
    data-testid="pet-delete-confirm-modal"
    @click.stop="!deleting && emit('cancel')"
  >
    <div class="glass-panel delete-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-pet-title" @click.stop>
      <h2 id="delete-pet-title">删除宠物档案</h2>
      <p>{{ description }}</p>

      <div class="dialog-actions">
        <button
          type="button"
          class="btn btn-soft dialog-btn"
          :disabled="deleting"
          data-testid="delete-pet-cancel-btn"
          @click="emit('cancel')"
        >
          取消
        </button>
        <button
          type="button"
          class="btn btn-danger-solid dialog-btn"
          :disabled="deleting"
          data-testid="delete-pet-confirm-btn"
          @click="emit('confirm')"
        >
          {{ deleting ? "删除中..." : "确认删除" }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.delete-dialog {
  width: min(420px, 90vw);
  border-radius: 28px;
  padding: 26px 28px 24px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  text-align: center;
}

.delete-dialog h2 {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: var(--text-primary);
}

.delete-dialog p {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.dialog-actions {
  margin-top: 10px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.dialog-btn {
  width: 100%;
  height: 44px;
}

.btn-danger-solid {
  background: #e24f4f;
  border-color: #e24f4f;
  color: #ffffff;
  box-shadow: 0 8px 20px rgba(226, 79, 79, 0.28);
}

.btn-danger-solid:hover:not(:disabled) {
  background: #c93b3b;
  border-color: #c93b3b;
}

.btn-danger-solid:disabled {
  background: #e98f8f;
  border-color: #e98f8f;
  box-shadow: none;
}
</style>
