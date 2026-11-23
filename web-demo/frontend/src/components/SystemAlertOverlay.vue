<script setup lang="ts">
import { dismissSafetyAlert, systemState } from "@/stores/systemStore";
</script>

<template>
  <div
    v-if="systemState.alertVisible"
    class="safety-overlay"
    data-testid="safety-alert-overlay"
    @click.stop
  >
    <div class="safety-dialog">
      <div class="safety-badge">行车优先提醒 · 系统级拦截</div>
      <h2>{{ systemState.alertTitle }}</h2>
      <p>{{ systemState.alertMessage }}</p>
      <div class="safety-actions">
        <button
          class="btn btn-black"
          data-testid="dismiss-safety-alert"
          @click="dismissSafetyAlert"
        >
          我已知晓，返回壁纸
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.safety-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  background: rgba(18, 28, 48, 0.46);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.safety-dialog {
  width: min(460px, 92vw);
  border-radius: 28px;
  padding: 30px 34px;
  background: #f5f8fd;
  color: #121628;
  border: 1.5px solid rgba(255, 255, 255, 0.95);
  box-shadow: 0 24px 60px rgba(15, 28, 56, 0.28);
  text-align: center;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.safety-badge {
  align-self: center;
  padding: 5px 14px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  background: #ebff9a;
  color: #121628;
}

.safety-dialog h2 {
  margin: 0;
  font-size: 22px;
}

.safety-dialog p {
  margin: 0;
  font-size: 14px;
  line-height: 1.6;
  color: var(--text-secondary);
}

.safety-actions {
  margin-top: 6px;
  display: flex;
  justify-content: center;
}
</style>
