<!-- 文件用途：通过密码解锁网页 Demo 设置，编辑生成服务、分辨率和宠物动作提示词。 -->
<script setup lang="ts">
import { computed, nextTick, ref } from "vue";
import backIcon from "@/assets/mastergo/back-chevron.svg";
import { ApiError, saveGenerationSettings, unlockGenerationSettings } from "@/lib/api";
import { setRoute, showToast, systemState } from "@/stores/systemStore";
import type { ActionSlot, GenerationSettings, Species } from "@/types";

const pets = [{ id: "cat", label: "猫咪" }, { id: "dog", label: "狗狗" }] as const;
const actions = [
  { id: "idle", label: "待机" }, { id: "left", label: "左侧交互" },
  { id: "center", label: "中央交互" }, { id: "right", label: "右侧交互" },
] as const;
const sizes = [
  { label: "生图分辨率", width: "image_width", height: "image_height", step: 32 },
  { label: "视频成片分辨率", width: "video_width", height: "video_height", step: 2 },
] as const;

const password = ref("");
const passwordInput = ref<HTMLInputElement>();
const settings = ref<GenerationSettings>();
const species = ref<Species>("cat");
const action = ref<ActionSlot>("idle");
const busy = ref(false);
const error = ref("");
let token = ""; // 离开设置页即释放本次解锁令牌。
const actionLabel = computed(() => actions.find(({ id }) => id === action.value)?.label);

/** 用输入的密码请求服务端解锁，并加载配置。 */
async function unlock() {
  busy.value = true;
  error.value = "";
  try {
    const result = await unlockGenerationSettings(password.value);
    token = result.token;
    settings.value = result.settings;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "无法打开设置";
  } finally {
    password.value = "";
    busy.value = false;
    await nextTick();
    passwordInput.value?.focus();
  }
}

/** 校验当前输入并保存全部配置，更新网页所用的生成服务。 */
async function save() {
  if (!settings.value || busy.value) return;
  if (Object.values(settings.value.prompts).some((prompts) => Object.values(prompts).some((prompt) => !prompt.trim()))) {
    error.value = "请填写猫咪和狗狗的全部提示词";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    const result = await saveGenerationSettings(token, settings.value);
    settings.value = result.settings;
    if (systemState.config) {
      systemState.config.provider = result.settings.provider;
      systemState.config.mock_controls_enabled = result.mock_controls_enabled;
    }
    showToast("生成设置已保存", "success");
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      token = "";
      settings.value = undefined;
    }
    error.value = err instanceof Error ? err.message : "保存设置失败";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="settings-stage" aria-labelledby="settings-title">
    <div class="settings-frame" :class="{ 'is-locked': !settings }">
      <header class="settings-header">
        <button class="circle-back-btn settings-back" type="button" aria-label="返回" @click="setRoute(systemState.settingsReturnRoute)">
          <img :src="backIcon" alt="" />
        </button>
        <h1 id="settings-title">生成设置</h1>
      </header>

      <form v-if="!settings" class="settings-lock" @submit.prevent="unlock">
        <label for="settings-password">设置密码</label>
        <input
          id="settings-password"
          ref="passwordInput"
          v-model="password"
          class="input-field"
          type="password"
          autocomplete="current-password"
          required
          :disabled="busy"
        />
        <p v-if="error" class="settings-error" role="alert">{{ error }}</p>
        <button class="btn btn-primary" :disabled="busy">{{ busy ? "正在验证…" : "解锁" }}</button>
      </form>

      <form v-else class="settings-form" @submit.prevent="save">
        <fieldset class="settings-controls" :disabled="busy">
          <label class="settings-provider">
            <span>生成服务</span>
            <select v-model="settings.provider" class="input-field">
              <option value="mock">Mock 模拟</option>
              <option value="comfyui">ComfyUI</option>
              <option value="kling">可灵 API</option>
            </select>
          </label>
          <div v-if="settings.provider === 'comfyui'" class="settings-dimensions">
            <div v-for="size in sizes" :key="size.width" class="size-control">
              <span>{{ size.label }}</span>
              <div class="size-inputs">
                <input v-model.number="settings[size.width]" class="input-field" type="number" required
                  min="128" max="4096" :step="size.step" :aria-label="`${size.label}宽度`" />
                <span aria-hidden="true">×</span>
                <input v-model.number="settings[size.height]" class="input-field" type="number" required
                  min="128" max="4096" :step="size.step" :aria-label="`${size.label}高度`" />
              </div>
            </div>
          </div>
        </fieldset>

        <fieldset class="prompt-controls" :disabled="busy">
          <legend>动作提示词</legend>
          <div class="prompt-layout">
            <div class="prompt-navigation">
              <div class="pet-switch" aria-label="宠物种类" role="group">
                <button v-for="pet in pets" :key="pet.id" type="button" :aria-pressed="species === pet.id"
                  @click="species = pet.id">{{ pet.label }}</button>
              </div>
              <div class="action-switch" aria-label="动作" role="group">
                <button v-for="item in actions" :key="item.id" type="button" :aria-pressed="action === item.id"
                  @click="action = item.id">{{ item.label }}</button>
              </div>
            </div>
            <div class="prompt-fields">
              <label v-if="action === 'idle'">
                <span>待机图提示词</span>
                <textarea v-model="settings.prompts[species].image" class="input-field" rows="3" maxlength="2500" required />
              </label>
              <label>
                <span>{{ actionLabel }}视频提示词</span>
                <textarea v-model="settings.prompts[species][action]" class="input-field" :rows="action === 'idle' ? 3 : 7"
                  maxlength="2500" required />
              </label>
            </div>
          </div>
        </fieldset>

        <footer class="settings-footer">
          <p v-if="error" class="settings-error" role="alert">{{ error }}</p>
          <button class="btn btn-primary" :disabled="busy">{{ busy ? "正在保存…" : "保存设置" }}</button>
        </footer>
      </form>
    </div>
  </section>
</template>

<style scoped>
.settings-stage {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: clamp(44px, 7vh, 100px) 24px max(58px, calc(146 * var(--mastergo-unit)));
}

.settings-frame {
  width: min(100%, 1050px);
  margin: 0 auto;
  padding: clamp(18px, 3vw, 38px);
  border: 1px solid var(--border-white);
  border-radius: var(--radius-xl);
  background: #f9fbff;
  box-shadow: var(--shadow-card);
}

.settings-frame.is-locked {
  width: min(100%, 420px);
  margin-top: clamp(8px, 10vh, 110px);
}

.settings-header { display: flex; align-items: center; gap: 14px; margin-bottom: 24px; }
.settings-header h1 { margin: 0; font-size: clamp(24px, 2.5vw, 38px); }
.settings-back { width: 36px; height: 36px; }
.settings-back img { width: 18px; height: 18px; }
.settings-form, .settings-lock { display: grid; gap: 20px; }
.settings-lock { gap: 12px; }
.settings-lock .btn { margin-top: 6px; }
.settings-controls, .prompt-controls { min-width: 0; margin: 0; border: 0; padding: 0; }
.settings-controls { display: flex; gap: 24px; flex-wrap: wrap; }
.settings-provider { display: grid; gap: 8px; min-width: 170px; }
.settings-dimensions { display: flex; flex-wrap: wrap; gap: 14px 24px; }
.size-control { display: grid; gap: 8px; }
.size-inputs { display: flex; align-items: center; gap: 8px; }
.size-inputs input { width: 84px; }
.prompt-controls legend { margin-bottom: 12px; padding: 0; font-size: 19px; font-weight: 650; }
.prompt-layout { display: grid; grid-template-columns: 162px minmax(0, 1fr); gap: 20px; }
.prompt-navigation { display: grid; align-content: start; gap: 12px; }
.pet-switch, .action-switch { display: grid; gap: 5px; }
.pet-switch { grid-template-columns: repeat(2, 1fr); padding: 4px; background: var(--surface-input); border-radius: 12px; }
.prompt-navigation button { min-height: 38px; border-radius: 9px; font-weight: 600; }
.pet-switch button[aria-pressed="true"] { background: white; box-shadow: 0 2px 5px #12162816; }
.action-switch button { text-align: left; padding: 0 12px; }
.action-switch button[aria-pressed="true"] { background: #e6efff; color: #204f9c; }
.prompt-fields { display: grid; align-content: start; gap: 12px; }
.prompt-fields label { display: grid; gap: 7px; font-weight: 600; }
.prompt-fields textarea { min-height: 90px; max-height: 45vh; resize: vertical; font: inherit; font-weight: 400; line-height: 1.5; }
.settings-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; align-items: center; gap: 12px; }
.settings-error { color: #b02635; margin: 0; }
.settings-footer .btn { min-width: 120px; }

@media (max-width: 620px) {
  .settings-stage { padding-inline: 12px; }
  .prompt-layout { grid-template-columns: minmax(0, 1fr); gap: 14px; }
  .action-switch { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .action-switch button { padding: 4px; text-align: center; }
}
</style>
