<!-- 文件用途：录入猫狗档案、上传照片并提交生成任务，支持部分成功后继续提交。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import { createIdempotencyKey, createPet, submitGeneration, updatePet } from "@/lib/api";
import { startWaitingBatch, trackJob } from "@/stores/generationStore";
import { upsertPet } from "@/stores/petStore";
import { guardParkedAction, setRoute, showToast, systemState } from "@/stores/systemStore";
import type { Gender, Species } from "@/types";

type PetDetails = { name: string; gender: Gender; breed: string };

interface PetFormDraft {
  species: Species;
  label: string;
  name: string;
  gender: Gender;
  breed: string;
  file: Blob | File | null;
  previewUrl: string | null;
  idempotencyKey: string;
  // 资料和生成分别确认，重试沿用同一档案并跳过已提交的任务。
  petId: string | null;
  savedDetails: PetDetails | null;
  jobId: string | null;
}

function makeDraft(species: Species): PetFormDraft {
  return {
    species,
    label: species === "cat" ? "猫咪" : "狗狗",
    name: "",
    gender: "未设置",
    breed: "",
    file: null,
    previewUrl: null,
    idempotencyKey: createIdempotencyKey(species),
    petId: null,
    savedDetails: null,
    jobId: null,
  };
}

const drafts = reactive<PetFormDraft[]>([]);
const submitting = ref(false);
const loadingSample = reactive<Record<string, boolean>>({});

function rebuildDrafts() {
  for (const d of drafts) {
    if (d.previewUrl && d.previewUrl.startsWith("blob:")) {
      URL.revokeObjectURL(d.previewUrl);
    }
  }
  drafts.splice(0, drafts.length);
  const mode = systemState.onboardingSpeciesMode || "cat";
  if (mode === "both") {
    drafts.push(makeDraft("cat"), makeDraft("dog"));
  } else {
    drafts.push(makeDraft(mode));
  }
}

watch(
  () => systemState.onboardingSpeciesMode,
  () => rebuildDrafts(),
  { immediate: true },
);

onBeforeUnmount(() => {
  for (const d of drafts) {
    if (d.previewUrl && d.previewUrl.startsWith("blob:")) {
      URL.revokeObjectURL(d.previewUrl);
    }
  }
});

const allPhotosReady = computed(() =>
  drafts.length > 0 && drafts.every((draft) => draft.file && !loadingSample[draft.species]),
);

function draftLocked(draft: PetFormDraft) {
  return submitting.value || Boolean(draft.jobId);
}

function toggleGender(draft: PetFormDraft, value: "弟弟" | "妹妹") {
  draft.gender = draft.gender === value ? "未设置" : value;
}

function handleFileSelect(draft: PetFormDraft, event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  if (!file || draftLocked(draft) || !guardParkedAction("选择宠物照片")) {
    input.value = "";
    return;
  }
  if (draft.previewUrl && draft.previewUrl.startsWith("blob:")) {
    URL.revokeObjectURL(draft.previewUrl);
  }
  draft.file = file;
  draft.previewUrl = URL.createObjectURL(file);
  draft.idempotencyKey = createIdempotencyKey(draft.species);
  input.value = "";
}

async function handleFillSample(draft: PetFormDraft) {
  if (draftLocked(draft) || !guardParkedAction("加载示例照片")) return;
  const routeRevision = systemState.routeRevision;
  loadingSample[draft.species] = true;
  try {
    const sampleUrl =
      systemState.config?.sample_uploads?.[draft.species] ||
      `/api/assets/samples/${draft.species}/upload`;
    const resp = await fetch(sampleUrl);
    if (!resp.ok) {
      throw new Error("加载示例照片失败");
    }
    const blob = await resp.blob();
    if (systemState.routeRevision !== routeRevision) return;
    if (draft.previewUrl && draft.previewUrl.startsWith("blob:")) {
      URL.revokeObjectURL(draft.previewUrl);
    }
    draft.file = new File([blob], `sample-${draft.species}.jpg`, { type: "image/jpeg" });
    draft.previewUrl = URL.createObjectURL(blob);
    draft.idempotencyKey = createIdempotencyKey(draft.species);
    if (!draft.name) {
      draft.name = draft.species === "cat" ? "橘宝" : "豆包";
    }
    if (!draft.breed) {
      draft.breed = draft.species === "cat" ? "长毛橘白猫" : "拉布拉多";
    }
  } catch (err) {
    if (systemState.routeRevision === routeRevision) {
      showToast(err instanceof Error ? err.message : "加载示例照片失败", "error");
    }
  } finally {
    loadingSample[draft.species] = false;
  }
}

function getMockParamsForSpecies(species: Species) {
  if (!systemState.config?.mock_controls_enabled) {
    return {};
  }
  switch (systemState.mockPreset) {
    case "over10s":
      return { mockDelaySeconds: 12.0 };
    case "staggered":
      return { mockDelaySeconds: species === "cat" ? 1.8 : 14.0 };
    case "fail":
      return {
        mockDelaySeconds: 1.2,
        mockFail: true,
        mockFailStage: "center",
        mockFailMessage: "模拟生成失败（中区动作生成异常）",
      };
    case "fast":
    default:
      return { mockDelaySeconds: 1.8 };
  }
}

/** 提交当前表单中未接受的任务；全部确认后打开生成等待页。 */
async function handleSubmit() {
  if (submitting.value || !allPhotosReady.value) return;
  if (!guardParkedAction("提交生成壁纸")) return;
  const routeRevision = systemState.routeRevision;
  const isCurrent = () => systemState.routeRevision === routeRevision;
  submitting.value = true;
  try {
    const jobIds: string[] = [];
    for (const draft of drafts) {
      if (draft.jobId) {
        jobIds.push(draft.jobId);
        continue;
      }
      const details = {
        name: draft.name.trim(),
        gender: draft.gender,
        breed: draft.breed.trim(),
      };
      if (!draft.petId) {
        const pet = await createPet({ species: draft.species, ...details });
        draft.petId = pet.id;
        draft.savedDetails = details;
        upsertPet(pet);
      } else if (details.name !== draft.savedDetails?.name || details.gender !== draft.savedDetails?.gender ||
                 details.breed !== draft.savedDetails?.breed) {
        const pet = await updatePet(draft.petId, { ...details, name: details.name || undefined });
        draft.savedDetails = details;
        upsertPet(pet);
      }
      if (!isCurrent()) return;

      const mockParams = getMockParamsForSpecies(draft.species);
      const res = await submitGeneration({
        petId: draft.petId,
        idempotencyKey: draft.idempotencyKey,
        photo: draft.file,
        ...mockParams,
      });
      if (res.pet) upsertPet(res.pet);
      trackJob(res.job);
      draft.jobId = res.job.id;
      jobIds.push(draft.jobId);
      if (!isCurrent()) return;
    }
    startWaitingBatch(jobIds);
    setRoute("generating");
  } catch (err) {
    if (isCurrent()) showToast(err instanceof Error ? err.message : "提交失败，请重试", "error", 4200);
  } finally {
    submitting.value = false;
  }
}

function handleBack() {
  setRoute("onboarding-species");
}
</script>

<template>
  <section class="upload-screen" data-testid="onboarding-upload-view">
    <!-- 右侧 MasterGo 蓝色星芒装饰 -->
    <svg class="deco-burst" viewBox="0 0 120 120" fill="none" aria-hidden="true">
      <path
        d="M60,8 L72,34 L98,20 L86,46 L114,56 L88,68 L104,94 L74,84 L62,112 L48,84 L18,94 L32,68 L6,56 L34,46 L22,20 L48,34 Z"
        fill="#6DA3FF"
        opacity="0.72"
      />
    </svg>

    <header class="upload-top">
      <div class="upload-top-left">
        <button
          class="circle-back-btn"
          aria-label="返回"
          data-testid="upload-back-btn"
          @click="handleBack"
        >
          <svg viewBox="0 0 20 20" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12.5 5 7.5 10l5 5" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </button>
        <h1 class="upload-title">完善宠物信息</h1>
      </div>
    </header>

    <!-- 标志性白色小屋形 ID CARD 主体 -->
    <div class="house-wrapper" :class="{ 'is-dual': drafts.length > 1 }">
      <!-- 顶部蓝色弯曲飘带装饰 -->
      <svg class="ribbon-deco" viewBox="0 0 120 120" fill="none" aria-hidden="true">
        <path
          d="M20,90 C28,42 54,18 92,22"
          stroke="#276ADE"
          stroke-width="22"
          stroke-linecap="round"
        />
      </svg>

      <!-- 小屋尖顶轮廓 -->
      <svg class="house-roof" viewBox="0 0 1000 90" preserveAspectRatio="none" aria-hidden="true">
        <path d="M0,90 L0,76 L486,6 Q500,2 514,6 L1000,76 L1000,90 Z" fill="#FFFFFF" />
      </svg>

      <div class="house-body">
        <div class="id-card-watermark" aria-hidden="true">ID CARD</div>

        <div class="draft-container" :class="{ dual: drafts.length > 1 }">
          <div
            v-for="draft in drafts"
            :key="draft.species"
            class="draft-block"
            :data-testid="`upload-panel-${draft.species}`"
          >
            <!-- 左侧照片上传区 -->
            <div class="photo-column">
              <label class="photo-slot" :class="{ filled: Boolean(draft.previewUrl) }" :data-testid="`dropzone-${draft.species}`">
                <input
                  type="file"
                  accept="image/jpeg,image/png"
                  :disabled="draftLocked(draft) || loadingSample[draft.species]"
                  class="hidden-file-input"
                  :data-testid="`file-input-${draft.species}`"
                  @change="(e) => handleFileSelect(draft, e)"
                />
                <template v-if="draft.previewUrl">
                  <img
                    :src="draft.previewUrl"
                    :alt="draft.label"
                    class="preview-img"
                    :data-testid="`preview-img-${draft.species}`"
                  />
                  <span v-if="!draftLocked(draft)" class="replace-chip">点击替换照片</span>
                </template>
                <template v-else>
                  <div class="upload-circle">
                    <svg viewBox="0 0 28 28" width="28" height="28" fill="none" stroke="#2c3346" stroke-width="2">
                      <rect x="4" y="5" width="20" height="18" rx="4" />
                      <circle cx="10.5" cy="11.5" r="2" />
                      <path d="m7 20 5-5 3.5 3.5L18.5 15 22 20" stroke-linecap="round" stroke-linejoin="round" />
                    </svg>
                  </div>
                  <span class="upload-hint-title">上传{{ draft.label }}照片</span>
                </template>
              </label>

              <div class="photo-sub-actions">
                <span class="lime-tip">
                  <span class="lime-dot" />
                  建议上传正面清晰照片 ~
                </span>
                <button
                  type="button"
                  class="sample-fill-btn"
                  :disabled="loadingSample[draft.species] || draftLocked(draft)"
                  :data-testid="`fill-sample-${draft.species}`"
                  @click="handleFillSample(draft)"
                >
                  {{ loadingSample[draft.species] ? "载入中..." : `填充示例${draft.label}照` }}
                </button>
              </div>
            </div>

            <!-- 右侧宠物信息表单区 -->
            <div class="form-column">
              <div class="form-section-title">{{ drafts.length > 1 ? `${draft.label}信息` : "宠物信息" }}</div>

              <div class="form-row">
                <span class="row-label">宠物爱称：</span>
                <input
                  v-model="draft.name"
                  type="text"
                  maxlength="40"
                  :disabled="draftLocked(draft)"
                  class="input-field"
                  placeholder="请输入昵称"
                  :data-testid="`input-name-${draft.species}`"
                />
              </div>

              <div class="form-row">
                <span class="row-label">宠物性别：</span>
                <div class="gender-pair">
                  <button
                    v-for="g in (['弟弟', '妹妹'] as const)"
                    :key="g"
                    type="button"
                    :disabled="draftLocked(draft)"
                    class="gender-btn"
                    :class="{ active: draft.gender === g }"
                    :data-testid="`gender-${draft.species}-${g}`"
                    @click="toggleGender(draft, g)"
                  >
                    {{ g }}
                  </button>
                </div>
              </div>

              <div class="form-row">
                <span class="row-label">宠物品种：</span>
                <input
                  v-model="draft.breed"
                  type="text"
                  maxlength="40"
                  :disabled="draftLocked(draft)"
                  class="input-field"
                  :placeholder="draft.species === 'cat' ? '例如：橘猫 / 布偶' : '例如：拉布拉多 / 柴犬'"
                  :data-testid="`input-breed-${draft.species}`"
                />
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 压在小屋底边的超大纯黑胶囊 CTA -->
      <button
        class="btn btn-black start-cta-btn"
        :disabled="!allPhotosReady || submitting"
        data-testid="start-generation-btn"
        @click="handleSubmit"
      >
        {{ submitting ? "正在提交..." : "开始生成" }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.upload-screen {
  position: relative;
  flex: 1;
  width: 100%;
  height: 100%;
  padding: 50px 44px 54px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: space-between;
  background: var(--bg-sky);
  overflow: hidden;
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

.upload-top {
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: flex-start;
  z-index: 3;
}

.upload-top-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.upload-title {
  margin: 0;
  font-size: 22px;
  font-weight: 600;
  color: #121628;
}

.house-wrapper {
  position: relative;
  width: min(900px, 90vw);
  margin-bottom: 16px;
  z-index: 3;
  filter: drop-shadow(0 20px 48px rgba(42, 85, 148, 0.16));
}

.house-wrapper.is-dual {
  width: min(1060px, 94vw);
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

.is-dual .house-roof {
  height: 40px;
}

.house-body {
  position: relative;
  z-index: 2;
  background: #ffffff;
  border-radius: 0 0 36px 36px;
  padding: 16px 42px 46px;
}

.is-dual .house-body {
  padding: 12px 30px 40px;
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

.draft-container {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.draft-container.dual {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px;
}

.draft-block {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 30px;
  align-items: center;
}

.dual .draft-block {
  grid-template-columns: 168px 1fr;
  gap: 16px;
  padding: 12px 14px;
  border-radius: 22px;
  background: #f6f9ff;
  border: 1px solid #e6effc;
}

.photo-column {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}

.photo-slot {
  position: relative;
  width: 100%;
  height: 224px;
  border-radius: 24px;
  background: #f5f7fb;
  border: 1.5px dashed #d3dce9;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  cursor: pointer;
  overflow: hidden;
}

.dual .photo-slot {
  height: 174px;
  border-radius: 20px;
}

.photo-slot.filled {
  border-style: solid;
  border-color: #93c5fd;
  background: linear-gradient(180deg, #5ba7ff 0%, #beddff 100%);
}

.hidden-file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.upload-circle {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  background: #eaeef5;
  display: flex;
  align-items: center;
  justify-content: center;
}

.dual .upload-circle {
  width: 56px;
  height: 56px;
}

.upload-hint-title {
  font-size: 13.5px;
  font-weight: 600;
  color: #536478;
}

.preview-img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.replace-chip {
  position: absolute;
  bottom: 8px;
  right: 8px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(18, 22, 40, 0.72);
  color: #ffffff;
}

.photo-sub-actions {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  width: 100%;
}

.lime-tip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 5px 12px;
  border-radius: 999px;
  font-size: 11.5px;
  font-weight: 600;
  color: #121628;
  background: #ebff9a;
}

.dual .lime-tip {
  display: none;
}

.lime-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #ffffff;
  flex-shrink: 0;
}

.sample-fill-btn {
  padding: 4px 12px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  color: #2563eb;
  background: #eaf2ff;
}

.sample-fill-btn:hover:not(:disabled) {
  background: #d7e7ff;
}

.form-column {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.dual .form-column {
  gap: 10px;
}

.form-section-title {
  text-align: center;
  font-size: 16px;
  font-weight: 700;
  color: #121628;
  margin-bottom: 2px;
}

.dual .form-section-title {
  text-align: left;
  font-size: 14px;
  margin-bottom: 0;
}

.form-row {
  display: grid;
  grid-template-columns: 78px 1fr;
  align-items: center;
  gap: 10px;
}

.dual .form-row {
  grid-template-columns: 1fr;
  gap: 4px;
}

.row-label {
  font-size: 13px;
  font-weight: 600;
  color: #536478;
}

.dual .row-label {
  font-size: 12px;
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

.dual .gender-btn {
  height: 34px;
  font-size: 13px;
}

.gender-btn.active {
  background: #ddfd66;
  color: #121628;
  box-shadow: 0 4px 12px rgba(176, 212, 42, 0.25);
}

.start-cta-btn {
  position: absolute;
  left: 50%;
  bottom: -24px;
  transform: translateX(-50%);
  min-width: 210px;
  height: 48px;
  font-size: 16px;
  z-index: 5;
}

.start-cta-btn:active:not(:disabled) {
  transform: translateX(-50%) scale(0.97);
}
</style>
