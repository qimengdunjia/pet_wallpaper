<!-- 文件用途：录入猫狗档案、上传照片并提交生成任务，支持部分成功后继续提交。 -->
<script setup lang="ts">
import backChevron from "@/assets/mastergo/back-chevron.svg";
import { computed, onBeforeUnmount, reactive, ref, watch } from "vue";
import uploadPhotoIcon from "@/assets/mastergo/upload-photo.svg";
import profileCardArt from "@/assets/mastergo/profile-card-frame.svg";
import profileCardForeground from "@/assets/mastergo/profile-card-foreground.svg";
import profileCardWordmark from "@/assets/mastergo/profile-card-wordmark.svg";
import uploadTipDog from "@/assets/mastergo/upload-tip-dog.png";
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
  <section class="upload-screen mastergo-cloud-sky" data-testid="onboarding-upload-view">
    <img
      :src="profileCardArt"
      :class="{ 'profile-card-art-dual': drafts.length > 1 }"
      alt=""
      class="profile-card-art"
    />
    <img :src="profileCardForeground" alt="" class="profile-card-foreground" />

    <header class="upload-top">
      <div class="upload-top-left">
        <button
          class="circle-back-btn"
          aria-label="返回"
          data-testid="upload-back-btn"
          @click="handleBack"
        >
          <img :src="backChevron" alt="" />
        </button>
        <h1 class="upload-title">完善宠物信息</h1>
      </div>
    </header>

    <div class="house-wrapper" :class="{ 'is-dual': drafts.length > 1 }">
      <div class="house-body">
        <img :src="profileCardWordmark" alt="" class="id-card-watermark" />

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
                    <img :src="uploadPhotoIcon" alt="" />
                  </div>
                  <span class="upload-hint-title">{{ drafts.length === 1 ? "上传宠物照片" : `上传${draft.label}照片` }}</span>
                </template>
              </label>

              <div class="photo-sub-actions">
                <button
                  type="button"
                  class="sample-fill-btn"
                  :class="{ 'lime-tip': drafts.length === 1 && !draft.previewUrl }"
                  :disabled="loadingSample[draft.species] || draftLocked(draft)"
                  :data-testid="`fill-sample-${draft.species}`"
                  :aria-label="`填充示例${draft.label}照`"
                  :title="`填充示例${draft.label}照`"
                  @click="handleFillSample(draft)"
                >
                  <template v-if="drafts.length === 1 && !draft.previewUrl && !loadingSample[draft.species]">
                    <span class="lime-dot"><img :src="uploadTipDog" alt="" /></span>
                    <span>建议上传正面清晰照片 ~</span>
                  </template>
                  <template v-else>{{ loadingSample[draft.species] ? "载入中..." : `填充示例${draft.label}照` }}</template>
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
                  placeholder="选择品种"
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
  /* 以原稿截图中可见的三段天空色为基准，云朵仍使用原始图层。 */
  background: var(--bg-profile-sky);
  overflow: hidden;
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
  gap: calc(48 * var(--mastergo-unit));
}

.upload-title {
  margin: 0;
  font-size: clamp(16px, calc(48 * var(--mastergo-unit)), 48px);
  font-weight: 500;
  color: #2c2c2c;
}

.house-wrapper {
  position: absolute;
  top: 34.444vh;
  width: min(64.53125vw, 114.7222vh);
  z-index: 3;
}

.house-wrapper.is-dual,
.profile-card-art-dual {
  width: min(1060px, 94vw);
}

.profile-card-art-dual {
  height: min(45.9375vw, 81.667vh);
}

.house-body {
  position: relative;
  z-index: 2;
  border-radius: 0 0 36px 36px;
  padding: 16px 42px 46px;
}

.is-dual .house-body {
  padding: 0 4.84% 14px;
}

.is-dual .id-card-watermark {
  top: auto;
  bottom: 104%;
  right: 9%;
}

.id-card-watermark {
  position: absolute;
  right: 36px;
  top: -12px;
  width: calc(320 * var(--mastergo-unit));
  height: auto;
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
  width: clamp(48px, 7.8125vw, 200px);
  height: clamp(48px, 7.8125vw, 200px);
  border-radius: 50%;
  background: rgba(79, 108, 164, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
}

.upload-circle img {
  width: 32%;
  height: 32%;
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
  gap: calc(14 * var(--mastergo-unit));
  width: 86.6667%;
  height: calc(90 * var(--mastergo-unit));
  border-radius: calc(24 * var(--mastergo-unit));
  white-space: nowrap;
}

.lime-dot {
  display: grid;
  place-items: center;
  width: calc(60 * var(--mastergo-unit));
  height: calc(60 * var(--mastergo-unit));
  border-radius: 50%;
  background: #ffffff;
  flex-shrink: 0;
}

.lime-dot img {
  width: 53.333%;
  height: 53.333%;
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

.sample-fill-btn.lime-tip {
  padding: 0 calc(15 * var(--mastergo-unit));
  font-size: clamp(9px, calc(28 * var(--mastergo-unit)), 28px);
  font-weight: 400;
  color: #666;
  background: rgba(216, 253, 104, 0.5);
}

.sample-fill-btn.lime-tip:hover:not(:disabled) {
  background: rgba(216, 253, 104, 0.68);
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
  top: calc(100% + min(14px, 2vh));
  transform: translateX(-50%);
  min-width: 210px;
  height: 48px;
  font-size: 16px;
  z-index: 5;
}

.start-cta-btn:active:not(:disabled) {
  transform: translateX(-50%) scale(0.97);
}

/* Page 1 的单宠照片框为 480 × 600，表单框为 952 × 600。 */
.upload-screen:has(.profile-card-art) .upload-top {
  position: absolute;
  top: calc(50% - 559 * var(--mastergo-unit));
  left: calc(50% - 1196 * var(--mastergo-unit));
  width: auto;
}

.upload-top .circle-back-btn {
  width: calc(100 * var(--mastergo-unit));
  height: calc(100 * var(--mastergo-unit));
}

.upload-top .circle-back-btn img {
  width: calc(15 * var(--mastergo-unit));
  height: calc(25 * var(--mastergo-unit));
}

.house-wrapper:not(.is-dual) .house-body {
  padding: 0 4.84%;
  background: transparent;
}

.house-wrapper:not(.is-dual) .draft-block {
  grid-template-columns: minmax(0, 480fr) minmax(0, 952fr);
  gap: 4.02%;
}

.house-wrapper:not(.is-dual) .photo-column {
  position: relative;
}

.house-wrapper:not(.is-dual) .photo-slot,
.house-wrapper:not(.is-dual) .form-column {
  height: min(23.4375vw, 41.6667vh);
  border-radius: clamp(12px, 1.875vw, 48px);
}

.house-wrapper:not(.is-dual) .photo-slot:not(.filled) {
  border: none;
  background: #fff;
}

.house-wrapper:not(.is-dual) .photo-slot:not(.filled) .upload-circle {
  position: absolute;
  top: 21.833%;
}

.house-wrapper:not(.is-dual) .upload-hint-title {
  position: absolute;
  top: 60.833%;
  color: #666;
  font-size: clamp(11px, calc(32 * var(--mastergo-unit)), 32px);
  font-weight: 400;
}

.house-wrapper:not(.is-dual) .photo-sub-actions {
  position: absolute;
  bottom: 5.333%;
  gap: 2px;
  pointer-events: none;
}

.house-wrapper:not(.is-dual) .sample-fill-btn {
  pointer-events: auto;
}

.house-wrapper:not(.is-dual) .form-column {
  gap: calc(48 * var(--mastergo-unit));
  padding: calc(48 * var(--mastergo-unit)) calc(80 * var(--mastergo-unit)) 0;
  background: #fff;
}

.house-wrapper:not(.is-dual) .form-section-title {
  margin: 0;
  height: calc(48 * var(--mastergo-unit));
  line-height: calc(48 * var(--mastergo-unit));
  color: #2c2c2c;
  font-size: clamp(12px, calc(36 * var(--mastergo-unit)), 36px);
  font-weight: 500;
}

.house-wrapper:not(.is-dual) .form-row {
  grid-template-columns: calc(160 * var(--mastergo-unit)) minmax(0, 1fr);
  gap: calc(32 * var(--mastergo-unit));
}

.house-wrapper:not(.is-dual) .row-label {
  color: #666;
  font-size: clamp(11px, calc(32 * var(--mastergo-unit)), 32px);
  font-weight: 400;
  white-space: nowrap;
}

.house-wrapper:not(.is-dual) :is(.input-field, .gender-btn) {
  height: calc(100 * var(--mastergo-unit));
  min-height: 0;
  border: 0;
  border-radius: calc(24 * var(--mastergo-unit));
  background: rgba(79, 108, 164, 0.08);
  font-size: clamp(11px, calc(32 * var(--mastergo-unit)), 32px);
  font-weight: 400;
}

.house-wrapper:not(.is-dual) .input-field {
  padding: 0 calc(34 * var(--mastergo-unit));
}

.house-wrapper:not(.is-dual) .input-field::placeholder {
  color: #ccc;
}

.house-wrapper:not(.is-dual) .gender-pair {
  gap: calc(32 * var(--mastergo-unit));
}

.house-wrapper:not(.is-dual) .gender-btn.active {
  background: #ddfd66;
}

.house-wrapper:not(.is-dual) .id-card-watermark {
  right: calc(109 * var(--mastergo-unit));
  top: calc(-90 * var(--mastergo-unit));
}

.house-wrapper:not(.is-dual) .start-cta-btn {
  top: calc(100% + 3.89vh);
  min-width: max(105px, 16.406vw);
  height: max(36px, 8.333vh);
  font-size: clamp(14px, calc(36 * var(--mastergo-unit)), 36px);
  font-weight: 400;
}

.start-cta-btn:disabled {
  background: #858d99;
  border-color: #858d99;
  color: #fff;
}

@media (max-height: 440px) {
  .house-wrapper:not(.is-dual) {
    top: 31vh;
  }

  .house-wrapper:not(.is-dual) .form-column {
    gap: 8px;
    padding-top: 7px;
  }

  .house-wrapper:not(.is-dual) :is(.input-field, .gender-btn) {
    min-height: 24px;
    height: 25px;
    padding-block: 0;
  }

  .house-wrapper:not(.is-dual) .form-row {
    grid-template-columns: 65px minmax(0, 1fr);
    gap: 4px;
  }

  .house-wrapper:not(.is-dual) .upload-circle {
    width: 40px;
    height: 40px;
  }

  .house-wrapper.is-dual {
    top: max(96px, 27.8vh);
  }

  .is-dual .house-body {
    padding: 6px 12px 8px;
  }

  .dual .draft-block {
    grid-template-columns: minmax(0, 4fr) minmax(0, 5fr);
    gap: 6px;
    padding: 6px 8px;
  }

  .dual .photo-slot {
    height: 29vh;
  }

  .dual .upload-circle {
    width: 34px;
    height: 34px;
  }

  .dual .form-column,
  .dual .form-row {
    gap: 2px;
  }

  .dual :is(.input-field, .gender-btn) {
    min-height: 23px;
    height: 23px;
    padding: 0 5px;
    font-size: 12px;
  }

  .is-dual .start-cta-btn {
    height: 36px;
    top: 100%;
  }
}
</style>
