<!-- 文件用途：展示正面照生成进度，并按原稿提供背景、装扮预览与继续生成操作。 -->
<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { cancelDecorations, confirmDecorations, createIdempotencyKey, submitGeneration } from "@/lib/api";
import { generationState, setDecorationBatch, startWaitingBatch, trackJob } from "@/stores/generationStore";
import { findPetById, upsertPet } from "@/stores/petStore";
import { guardParkedAction, setRoute, showToast, systemState } from "@/stores/systemStore";
import type { DecorationAccessory, DecorationBackground, DecorationChoice } from "@/types";

const backgrounds: { id: DecorationBackground; label: string; color: string }[] = [
  { id: "cream", label: "米白色", color: "#FCF6ED" },
  { id: "pink", label: "浅粉色", color: "#FADEE4" },
  { id: "blue", label: "浅蓝色", color: "#A3CEF7" },
  { id: "lavender", label: "浅紫色", color: "#C8C2F5" },
];

const accessories: { id: DecorationAccessory; label: string }[] = [
  { id: "none", label: "无配饰" },
  { id: "bow-tie", label: "蝴蝶结" },
  { id: "bandana", label: "三角巾" },
  { id: "glasses", label: "墨镜" },
  { id: "santa-hat", label: "圣诞帽" },
];

const assetRoot = "/api/assets/decoration/";
const defaultChoice: DecorationChoice = { background: "blue", accessory: "none" };
const selections = reactive<Record<string, DecorationChoice>>({});
const activeId = ref("");
const moreAccessories = ref(false);
const busy = ref(false);
const previewFailed = ref(false);
const previewAttempt = ref(0);
const previewLoaded = ref(false);
const jobs = computed(() => generationState.decorationJobIds.map((id) => generationState.jobsById[id]).filter(Boolean));
const activeJob = computed(() => jobs.value.find((item) => item.id === activeId.value) || jobs.value[0]);
const selection = computed(() => selections[activeJob.value?.id] || defaultChoice);
const canContinue = computed(() => jobs.value.length > 0 &&
  jobs.value.every((job) => job.status === "awaiting_decoration" && job.preview_url));
const previewUrl = computed(() => {
  const url = activeJob.value?.preview_url;
  if (!url) return "";
  if (!previewAttempt.value) return url;
  const query = new URLSearchParams({ retry: String(previewAttempt.value) });
  return url + (url.includes("?") ? "&" : "?") + query;
});

watch(previewUrl, () => {
  previewFailed.value = false;
  previewLoaded.value = false;
});
watch(activeJob, (job, previous) => {
  if (job?.id === previous?.id) return;
  moreAccessories.value = selection.value.accessory === "santa-hat";
});

function petName(petId: string): string {
  return findPetById(petId)?.name || "宠物";
}

function changeChoice(patch: Partial<DecorationChoice>) {
  if (!activeJob.value || !guardParkedAction("选择宠物装扮")) return;
  selections[activeJob.value.id] = { ...selection.value, ...patch };
}

/** 将各宠物选择一次提交给后端，收到已确认任务后进入动画等待页。 */
async function handleContinue() {
  if (busy.value || !canContinue.value || !previewLoaded.value || !guardParkedAction("继续生成")) return;
  busy.value = true;
  const routeRevision = systemState.routeRevision;
  try {
    const confirmed = await confirmDecorations(jobs.value.map((job) => ({
      job_id: job.id,
      ...(selections[job.id] || defaultChoice),
    })));
    confirmed.forEach((job) => trackJob(job));
    setDecorationBatch([]);
    if (systemState.routeRevision === routeRevision) {
      startWaitingBatch(confirmed.map((job) => job.id));
      setRoute("generating");
    }
  } catch (err) {
    showToast(err instanceof Error ? err.message : "提交装扮失败，请重试", "error");
  } finally {
    busy.value = false;
  }
}

/** 取消当前批次的正面照任务，并回到添加宠物前的页面。 */
async function handleCancel() {
  if (busy.value) return;
  if (!jobs.value.length) {
    setRoute(systemState.onboardingReturnRoute);
    return;
  }
  busy.value = true;
  const routeRevision = systemState.routeRevision;
  try {
    const cancelled = await cancelDecorations(jobs.value.map((job) => job.id));
    cancelled.forEach((job) => trackJob(job));
    setDecorationBatch([]);
    if (systemState.routeRevision === routeRevision) setRoute(systemState.onboardingReturnRoute);
  } catch (err) {
    showToast(err instanceof Error ? err.message : "取消生成失败，请重试", "error");
  } finally {
    busy.value = false;
  }
}

/** 用当前失败任务的原照片重试，更新批次中的任务 ID。 */
async function retryPortrait() {
  const job = activeJob.value;
  if (busy.value || !job || !guardParkedAction("重试生成")) return;
  busy.value = true;
  try {
    const result = await submitGeneration({
      petId: job.pet_id,
      idempotencyKey: createIdempotencyKey("portrait-retry"),
      retryFromJobId: job.id,
      mockDelaySeconds: systemState.config?.mock_controls_enabled ? 1.8 : undefined,
    });
    if (result.pet) upsertPet(result.pet);
    trackJob(result.job);
    setDecorationBatch(generationState.decorationJobIds.map((id) => id === job.id ? result.job.id : id));
    activeId.value = result.job.id;
  } catch (err) {
    showToast(err instanceof Error ? err.message : "重试失败", "error");
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="decoration-screen" data-testid="onboarding-decoration-view">
    <div class="decoration-canvas">
      <div v-if="jobs.length > 1" class="pet-tabs" role="group" aria-label="选择要装扮的宠物">
        <button
          v-for="job in jobs"
          :key="job.id"
          type="button"
          :aria-pressed="activeJob?.id === job.id"
          :disabled="busy"
          @click="activeId = job.id"
        >
          {{ petName(job.pet_id) }}{{ job.status === 'failed' ? ' · 失败' : job.preview_url ? '' : ' · 生成中' }}
        </button>
      </div>

      <figure v-if="activeJob" class="portrait-card">
        <div class="portrait-frame" :aria-busy="!previewLoaded && !previewFailed && activeJob.status !== 'failed'">
          <img
            v-if="previewUrl && !previewFailed"
            :src="previewUrl"
            :alt="petName(activeJob.pet_id) + '装扮预览'"
            data-testid="decoration-preview"
            @load="previewLoaded = true"
            @error="previewFailed = true"
          />
          <div v-else-if="previewFailed || activeJob.status === 'failed'" class="portrait-status" role="status">
            <span>{{ previewFailed ? "预览加载失败" : activeJob.error_message || "正面照生成失败" }}</span>
            <button
              v-if="previewFailed"
              class="btn"
              :disabled="busy"
              @click="previewAttempt++"
            >重新加载</button>
            <button v-else class="btn" :disabled="busy" @click="retryPortrait">重试生成</button>
          </div>
          <div v-else class="portrait-status" role="status">
            <span>正在生成正面照</span>
            <progress :value="activeJob.progress" max="100" />
          </div>
        </div>
        <figcaption>{{ petName(activeJob.pet_id) }}</figcaption>
      </figure>

      <div v-if="activeJob" class="decoration-options">
        <h2 id="decoration-backgrounds">背景选择</h2>
        <div class="option-row backgrounds" role="group" aria-labelledby="decoration-backgrounds">
          <button
            v-for="option in backgrounds"
            :key="option.id"
            type="button"
            :aria-label="option.label"
            :aria-pressed="selection.background === option.id"
            :disabled="busy || !activeJob.preview_url"
            :style="{ backgroundColor: systemState.config?.decoration_backgrounds?.[option.id] || option.color }"
            @click="changeChoice({ background: option.id })"
          >
            <img :src="assetRoot + 'background-pet'" alt="" />
          </button>
        </div>

        <h2 id="decoration-accessories">装扮</h2>
        <div class="option-row accessories" role="group" aria-labelledby="decoration-accessories">
          <button
            v-for="option in accessories.slice(moreAccessories ? 1 : 0, moreAccessories ? 5 : 4)"
            :key="option.id"
            type="button"
            :aria-pressed="selection.accessory === option.id"
            :disabled="busy || !activeJob.preview_url"
            @click="changeChoice({ accessory: option.id })"
          >
            <img v-if="option.id !== 'none'" :src="assetRoot + option.id" alt="" />
            <span v-else class="no-accessory" aria-hidden="true" />
            <span>{{ option.label }}</span>
          </button>
          <button
            class="more-accessories"
            type="button"
            :aria-label="moreAccessories ? '上一组配饰' : '更多配饰'"
            :disabled="busy"
            @click="moreAccessories = !moreAccessories"
          >{{ moreAccessories ? '‹' : '›' }}</button>
        </div>
      </div>

      <p v-if="!jobs.length" class="empty-decoration" role="status">暂无待装扮的宠物</p>

      <div class="decoration-actions">
        <button
          v-if="jobs.length"
          class="btn btn-black"
          :disabled="busy || !canContinue || !previewLoaded"
          data-testid="decoration-continue"
          @click="handleContinue"
        >继续生成</button>
        <button class="btn" :disabled="busy" data-testid="decoration-cancel" @click="handleCancel">
          {{ jobs.length ? '取消生成' : '返回' }}
        </button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.decoration-screen {
  position: absolute;
  inset: 0;
  color: #252525;
  background: linear-gradient(180deg, #8dc4f9, #e6eefb);
  overflow: hidden;
}

.decoration-canvas {
  --u: var(--mastergo-unit);
  position: absolute;
  left: 50%;
  top: 50%;
  width: calc(2560 * var(--u));
  height: calc(1440 * var(--u));
  transform: translate(-50%, -50%);
}

.decoration-canvas::before {
  content: "";
  position: absolute;
  inset: 0;
  opacity: 0.35;
  pointer-events: none;
  background:
    url("../assets/mastergo/clouds.png") calc(-380 * var(--u)) calc(745 * var(--u)) / 49% auto no-repeat,
    url("../assets/mastergo/clouds.png") calc(1830 * var(--u)) calc(-55 * var(--u)) / 49% auto no-repeat,
    url("../assets/mastergo/clouds.png") calc(585 * var(--u)) calc(95 * var(--u)) / 29% auto no-repeat;
}

.pet-tabs {
  position: absolute;
  top: calc(152 * var(--u));
  left: calc(943 * var(--u));
  display: flex;
  gap: calc(18 * var(--u));
}

.pet-tabs button {
  border-radius: 999px;
  padding: 0.32em 0.85em;
  font-size: max(11px, calc(29 * var(--u)));
  background: #ffffff75;
}

.pet-tabs button[aria-pressed="true"] {
  background: #fff;
  font-weight: 650;
}

.portrait-card {
  position: absolute;
  top: calc(282 * var(--u));
  left: calc(200 * var(--u));
  width: calc(638 * var(--u));
  height: calc(766 * var(--u));
  margin: 0;
  padding: calc(42 * var(--u));
  border-radius: calc(48 * var(--u));
  background: #f4faffaa;
}

.portrait-frame {
  width: 100%;
  height: calc(574 * var(--u));
  border-radius: calc(36 * var(--u));
  background: #9ecafa9c;
  overflow: hidden;
  display: grid;
  place-items: center;
}

.portrait-frame > img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.portrait-card figcaption {
  margin-top: calc(38 * var(--u));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  text-align: center;
  font-size: max(13px, calc(44 * var(--u)));
}

.portrait-status {
  display: grid;
  gap: 0.85em;
  max-width: 85%;
  justify-items: center;
  text-align: center;
  font-size: max(12px, calc(32 * var(--u)));
}

.portrait-status progress {
  width: 90%;
  accent-color: #476e9e;
}

.decoration-options {
  position: absolute;
  top: calc(277 * var(--u));
  left: calc(943 * var(--u));
  width: calc(1436 * var(--u));
}

.decoration-options h2 {
  display: grid;
  place-items: center;
  width: calc(250 * var(--u));
  min-height: calc(80 * var(--u));
  margin: 0;
  border-radius: 999px;
  background: #eef7ff86;
  font-weight: 500;
  font-size: max(12px, calc(35 * var(--u)));
}

.option-row {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: calc(38 * var(--u));
  margin: calc(64 * var(--u)) 0 0 calc(26 * var(--u));
}

.backgrounds {
  margin-bottom: calc(64 * var(--u));
}

.option-row > button:not(.more-accessories) {
  border-radius: calc(40 * var(--u));
  padding: 0;
}

.option-row > button[aria-pressed="true"] {
  outline: max(2px, calc(5 * var(--u))) solid #d5ff4f;
  outline-offset: calc(6 * var(--u));
}

.backgrounds button {
  height: calc(180 * var(--u));
  border: max(2px, calc(8 * var(--u))) solid #ffffffa0;
  position: relative;
  overflow: hidden;
}

.backgrounds img {
  position: absolute;
  left: 50%;
  top: 12%;
  transform: translateX(-50%);
  width: 53%;
  pointer-events: none;
}

.accessories > button:not(.more-accessories) {
  height: calc(234 * var(--u));
  display: grid;
  grid-template-rows: minmax(0, 1fr) auto;
  place-items: center;
  background: #e8edf4a6;
  font-size: max(10px, calc(27 * var(--u)));
  color: #494949;
  padding: calc(27 * var(--u)) calc(18 * var(--u)) calc(22 * var(--u));
}

.accessories img {
  max-width: 78%;
  width: auto;
  max-height: calc(126 * var(--u));
}

.no-accessory {
  position: relative;
  display: block;
  width: calc(86 * var(--u));
  height: calc(86 * var(--u));
  border: max(2px, calc(8 * var(--u))) solid #adb6c0;
  border-radius: 50%;
}

.no-accessory::after {
  content: "";
  position: absolute;
  inset: 45% 0;
  background: #adb6c0;
  transform: rotate(-45deg);
}

.more-accessories {
  position: absolute;
  right: 0;
  top: 28%;
  width: calc(55 * var(--u));
  height: 44%;
  padding: 0;
  color: #364b65;
  font-size: max(16px, calc(52 * var(--u)));
}

.decoration-actions {
  position: absolute;
  top: calc(1142 * var(--u));
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: calc(240 * var(--u));
}

.decoration-actions .btn {
  width: calc(420 * var(--u));
  min-height: calc(120 * var(--u));
  min-width: 90px;
  padding: 0 5px;
  font-size: max(12px, calc(36 * var(--u)));
  font-weight: 500;
  box-shadow: none;
}

.decoration-actions .btn:disabled {
  opacity: 0.48;
}

.empty-decoration {
  position: absolute;
  inset: 42% 0 auto;
  text-align: center;
}
</style>
