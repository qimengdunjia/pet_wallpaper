// 文件用途：轮询生成任务，管理等待批次以及就绪壁纸的切入和回退。
import { nextTick, reactive } from "vue";
import { fetchGeneration } from "@/lib/api";
import type { GenerationJob } from "@/types";
import {
  applyJobToPet,
  findPetById,
  petState,
} from "./petStore";
import {
  activatePetWallpaper,
  playerState,
  restoreFallbackWallpaper,
  saveDisplayedWallpaper,
  type SwitchDeps,
} from "./playerStore";
import { setRoute, showToast, systemState } from "./systemStore";

export const generationState = reactive({
  jobsById: {} as Record<string, GenerationJob>,
  waitingJobIds: [] as string[],
  firstRoundComplete: false,
  // 只有本次等待无法继续时才显示失败面板。
  waitingError: null as { kind: "generation" | "assets"; message: string } | null,
});

const pollTimers = new Map<string, number>();
const loadFailures = new Map<string, string>();
let evaluation: { routeRevision: number } | null = null;

/** 开始等待 jobIds 对应的任务，清除上一次等待的播放和错误状态。 */
export function startWaitingBatch(jobIds: string[]) {
  clearWaitingBatch();
  generationState.waitingJobIds = [...jobIds];
}

export function clearWaitingBatch() {
  evaluation = null;
  loadFailures.clear();
  generationState.waitingJobIds = [];
  generationState.firstRoundComplete = false;
  generationState.waitingError = null;
}

export async function markFirstRoundComplete(deps?: SwitchDeps) {
  generationState.firstRoundComplete = true;
  await evaluateWaitingBatch(deps);
}

export function getWaitingJobs(): GenerationJob[] {
  return generationState.waitingJobIds
    .map((id) => generationState.jobsById[id])
    .filter((job): job is GenerationJob => Boolean(job));
}

export function isWaitingBatchAllFailed(): boolean {
  const jobs = getWaitingJobs();
  return jobs.length > 0 && jobs.every((j) => j.status === "failed");
}

export function isWaitingBatchActive(): boolean {
  const jobs = getWaitingJobs();
  return jobs.some((j) => j.status === "queued" || j.status === "generating");
}

/** 在当前等待页尝试切入已就绪壁纸，使用 deps 预加载和保存，失败时回退或显示错误。 */
export async function evaluateWaitingBatch(deps?: SwitchDeps): Promise<void> {
  const routeRevision = systemState.routeRevision;
  if (systemState.route !== "generating" || systemState.alertVisible || generationState.waitingError ||
      evaluation?.routeRevision === routeRevision) {
    return;
  }
  const canCutOut = systemState.cutoutStrategy === "immediate" || generationState.firstRoundComplete;
  if (getWaitingJobs().length === 0 || (!canCutOut && !isWaitingBatchAllFailed())) {
    return;
  }

  const attempt = { routeRevision };
  evaluation = attempt;
  const isCurrent = () => evaluation === attempt && systemState.routeRevision === routeRevision;
  try {
    while (canCutOut) {
      // 前一套加载失败时，继续尝试等待期间就绪的其他素材。
      const readyJobs = getWaitingJobs().filter((job) =>
        job.status === "ready" && job.assets && !loadFailures.has(job.assets.version_id),
      );
      readyJobs.sort((left, right) => left.updated_at.localeCompare(right.updated_at));
      const readyJob = readyJobs[0];
      if (!readyJob?.assets) break;
      const assets = readyJob.assets;
      const pet = findPetById(readyJob.pet_id);
      if (!pet) {
        loadFailures.set(assets.version_id, "宠物档案加载失败");
        continue;
      }
      const result = await activatePetWallpaper(
        { ...pet, active_version_id: assets.version_id, active_assets: assets },
        { persist: false, force: true, deps, isCurrent },
      );
      if (!isCurrent() || result.canceled) return;
      if (result.ok) {
        setRoute("wallpaper");
        const displayRevision = systemState.routeRevision;
        const message = isWaitingBatchActive()
          ? `${pet.name} 壁纸已就绪，其余宠物继续在后台生成`
          : `${pet.name} 壁纸已就绪`;
        showToast(message, "success");
        await nextTick();
        if (systemState.routeRevision === displayRevision && playerState.currentVersionId === assets.version_id) {
          await saveDisplayedWallpaper(deps);
        }
        return;
      }
      loadFailures.set(assets.version_id, result.reason || "壁纸素材加载失败");
    }
    if (isWaitingBatchActive()) return;
    const jobs = getWaitingJobs();
    const kind = jobs.some((job) => job.status === "ready") ? "assets" : "generation";
    const message = kind === "assets"
      ? loadFailures.values().next().value || "壁纸素材加载失败"
      : jobs.find((job) => job.error_message)?.error_message || "壁纸生成失败，请重试";
    const fallback = await restoreFallbackWallpaper({ deps, isCurrent, excludedVersions: new Set(loadFailures.keys()) });
    if (!isCurrent() || fallback.canceled) return;
    if (fallback.ok) {
      setRoute("wallpaper");
      showToast(`${message}，已恢复可用壁纸`, "error", 5000);
      return;
    }
    generationState.waitingError = { kind, message };
  } finally {
    if (evaluation === attempt) evaluation = null;
  }
}

/** 使用现有成品清单重试加载，可通过 deps 注入测试依赖。 */
export async function retryWaitingWallpaper(deps?: SwitchDeps) {
  loadFailures.clear();
  generationState.waitingError = null;
  await evaluateWaitingBatch(deps);
}

export async function handleJobSnapshot(job: GenerationJob, deps?: SwitchDeps): Promise<void> {
  const prevStatus = generationState.jobsById[job.id]?.status;
  generationState.jobsById[job.id] = job;
  const updatedPet = applyJobToPet(job);
  const petName = updatedPet?.name || "宠物";

  const isCurrentWaiting =
    systemState.route === "generating" && generationState.waitingJobIds.includes(job.id);

  if (job.status === "ready" || job.status === "failed") {
    stopPollingJob(job.id);
  }

  // 用户已退出等待页或当前不在关注这批任务：只更新对应宠物状态与轻提示，不覆盖当前壁纸
  if (!isCurrentWaiting) {
    if (prevStatus !== job.status) {
      if (job.status === "ready") {
        showToast(`${petName} 的壁纸已生成就绪，可在「切换宠物」中选择`, "success", 4200);
      } else if (job.status === "failed") {
        showToast(
          `${petName} 生成失败：${job.error_message || "请重试"}（当前壁纸不受影响）`,
          "warning",
          4200,
        );
      }
    }
    return;
  }

  await evaluateWaitingBatch(deps);
}

/** 跟踪 job，仅更新档案中适用的任务和素材版本，继续轮询进行中的任务。 */
export function trackJob(job: GenerationJob, deps?: SwitchDeps) {
  generationState.jobsById[job.id] = job;
  applyJobToPet(job);
  if (job.status === "queued" || job.status === "generating") {
    startPollingJob(job.id, deps);
  }
}

export function startPollingJob(jobId: string, deps?: SwitchDeps) {
  if (typeof window === "undefined" || pollTimers.has(jobId)) {
    return;
  }
  let requestPending = false;
  const tick = async () => {
    if (requestPending) return;
    requestPending = true;
    try {
      const latest = await fetchGeneration(jobId);
      if (pollTimers.get(jobId) === timer) await handleJobSnapshot(latest, deps);
    } catch {
      // 短暂轮询错误保持继续重试
    } finally {
      requestPending = false;
    }
  };
  const timer = window.setInterval(() => {
    void tick();
  }, 500);
  pollTimers.set(jobId, timer);
}

export function stopPollingJob(jobId: string) {
  const timer = pollTimers.get(jobId);
  if (timer !== undefined && typeof window !== "undefined") {
    window.clearInterval(timer);
  }
  pollTimers.delete(jobId);
}

export function stopAllPolling() {
  for (const jobId of Array.from(pollTimers.keys())) {
    stopPollingJob(jobId);
  }
}

export function hasActiveBackgroundJobs(): boolean {
  return (
    Object.values(generationState.jobsById).some(
      (job) => job.status === "queued" || job.status === "generating",
    ) ||
    petState.pets.some(
      (pet) =>
        pet.latest_job?.status === "queued" || pet.latest_job?.status === "generating",
    )
  );
}

export function resetGenerationState() {
  stopAllPolling();
  clearWaitingBatch();
  generationState.jobsById = {};
}
