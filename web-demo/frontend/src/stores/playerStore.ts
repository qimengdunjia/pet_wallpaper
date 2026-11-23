// 文件用途：校验、切换和播放宠物壁纸，管理最近一次成功显示的素材。
import { reactive } from "vue";
import { saveCurrentWallpaper } from "@/lib/api";
import { verifyAndPreloadAssets } from "@/lib/preload";
import type { AssetVersionManifest, HotzoneSlot, PetProfile } from "@/types";
import { getDefaultPet, petState, setSavedWallpaper } from "./petStore";
import { showToast, systemState } from "./systemStore";

export interface SwitchDeps {
  verifyAssets?: typeof verifyAndPreloadAssets;
  persistWallpaper?: typeof saveCurrentWallpaper;
}

type SwitchResult = { ok: boolean; reason?: string; canceled?: boolean };

export const playerState = reactive({
  currentPetId: null as string | null,
  currentVersionId: null as string | null,
  currentAssets: null as AssetVersionManifest | null,
  playbackState: "idle" as "idle" | "playing" | "switching",
  activeAction: null as HotzoneSlot | null,
  lastTriggered: null as { slot: HotzoneSlot; ratioX: number; at: string } | null,
  operationSeq: 0,
  selectorOpen: false,
  confirmingPetId: null as string | null,
  editingPetId: null as string | null,
});

export function setDisplayedWallpaper(petId: string, versionId: string, assets: AssetVersionManifest) {
  playerState.currentPetId = petId;
  playerState.currentVersionId = versionId;
  playerState.currentAssets = assets;
  playerState.playbackState = "idle";
  playerState.activeAction = null;
}

/** 保存当前已展示的版本；deps 可注入持久化实现，isCurrent 用于丢弃已取消操作的回执。 */
export async function saveDisplayedWallpaper(deps?: SwitchDeps, isCurrent?: () => boolean) {
  const { currentPetId, currentVersionId, operationSeq } = playerState;
  if (!currentPetId || !currentVersionId) return;
  const persist = deps?.persistWallpaper ?? saveCurrentWallpaper;
  const stillDisplayed = () => playerState.operationSeq === operationSeq && (isCurrent?.() ?? true);
  try {
    const saved = await persist(currentPetId, currentVersionId);
    if (stillDisplayed()) setSavedWallpaper(saved);
  } catch {
    if (stillDisplayed()) showToast("已显示壁纸，保存上次显示记录失败", "warning");
  }
}

/** 预加载宠物 pet 的素材，按 options 保存显示记录，返回切换结果。 */
export async function activatePetWallpaper(
  pet: PetProfile,
  options?: {
    persist?: boolean;
    force?: boolean;
    deps?: SwitchDeps;
    // 调用方可绑定页面或批次，避免过时的预加载结果改变播放器。
    isCurrent?: () => boolean;
  },
): Promise<SwitchResult> {
  const { active_assets: assets, active_version_id: versionId } = pet;
  if (!assets || !versionId) {
    return { ok: false, reason: "该宠物壁纸尚未生成完成" };
  }
  if (!options?.force && playerState.playbackState === "playing") {
    return { ok: false, reason: "互动动作播放中，请待本段结束后再切换" };
  }

  const seq = ++playerState.operationSeq;
  const isCurrent = () => seq === playerState.operationSeq && (options?.isCurrent?.() ?? true);
  const canceled = { ok: false, canceled: true, reason: "切换操作已取消" };
  const prevState = playerState.playbackState;
  playerState.playbackState = "switching";

  const verifyFn = options?.deps?.verifyAssets ?? verifyAndPreloadAssets;
  const shouldSimulateFailure = systemState.simulateNextSwitchFailure;
  if (shouldSimulateFailure) {
    systemState.simulateNextSwitchFailure = false;
  }

  let loadError: string | undefined;
  try {
    await verifyFn(assets, { simulateFailure: shouldSimulateFailure });
  } catch (err) {
    loadError = err instanceof Error ? err.message || "壁纸素材加载失败" : "壁纸素材加载失败";
  }
  if (!isCurrent() || loadError) {
    if (seq === playerState.operationSeq) {
      playerState.playbackState = prevState === "playing" ? "playing" : "idle";
    }
    return isCurrent() ? { ok: false, reason: `壁纸加载失败（${loadError}）` } : canceled;
  }

  setDisplayedWallpaper(pet.id, versionId, assets);

  if (options?.persist !== false) {
    await saveDisplayedWallpaper(options?.deps, isCurrent);
  }
  return isCurrent() ? { ok: true } : canceled;
}

export function triggerHotzone(slot: HotzoneSlot, ratioX: number): boolean {
  if (systemState.alertVisible) {
    return false;
  }
  if (systemState.drivingMode === "driving") {
    showToast("车辆行驶中已禁用画布点击互动，请注意行车安全", "warning", 2800);
    return false;
  }
  if (playerState.selectorOpen || playerState.confirmingPetId || playerState.editingPetId) {
    return false;
  }
  if (playerState.playbackState !== "idle") {
    return false;
  }
  if (!playerState.currentAssets) {
    return false;
  }
  playerState.playbackState = "playing";
  playerState.activeAction = slot;
  playerState.lastTriggered = {
    slot,
    ratioX,
    at: new Date().toLocaleTimeString("zh-CN", { hour12: false }),
  };
  return true;
}

export function completeActionPlayback() {
  if (playerState.playbackState === "playing") {
    playerState.playbackState = "idle";
    playerState.activeAction = null;
  }
}

export function interruptPlayback(notice?: string) {
  playerState.operationSeq += 1;
  playerState.playbackState = "idle";
  playerState.activeAction = null;
  if (notice) {
    showToast(notice, "warning", 3000);
  }
}

export function openPetSelector() {
  if (playerState.playbackState === "playing") {
    showToast("动作播放期间暂停切换宠物，请稍候", "warning", 2400);
    return false;
  }
  playerState.confirmingPetId = null;
  playerState.editingPetId = null;
  playerState.selectorOpen = true;
  return true;
}

export function closePetSelector() {
  playerState.selectorOpen = false;
  playerState.confirmingPetId = null;
  playerState.editingPetId = null;
}

/** 按保存记录、当前显示和档案素材依次尝试回退，返回首套加载成功的结果。 */
export async function restoreFallbackWallpaper(options: {
  deps?: SwitchDeps;
  isCurrent: () => boolean;
  excludedVersions: ReadonlySet<string>;
}): Promise<SwitchResult> {
  const saved = petState.savedWallpaper;
  const savedPet = saved && { ...saved.pet, active_version_id: saved.version_id, active_assets: saved.assets };
  const currentPet = petState.pets.find((pet) => pet.id === playerState.currentPetId);
  const displayedPet = currentPet && {
    ...currentPet,
    active_version_id: playerState.currentVersionId,
    active_assets: playerState.currentAssets,
  };
  const defaultPet = getDefaultPet();
  const attempted = new Set(options.excludedVersions);
  for (const pet of [savedPet, displayedPet, ...petState.pets, defaultPet]) {
    if (!pet?.active_version_id || attempted.has(pet.active_version_id)) continue;
    attempted.add(pet.active_version_id);
    const result = await activatePetWallpaper(pet, { ...options, persist: false, force: true });
    if (result.ok || result.canceled) return result;
  }
  return { ok: false, reason: "暂无可加载的历史壁纸" };
}

export function resetLocalView() {
  playerState.operationSeq += 1;
  playerState.playbackState = "idle";
  playerState.activeAction = null;
  playerState.selectorOpen = false;
  playerState.confirmingPetId = null;
  playerState.editingPetId = null;
}

export function resetPlayerState() {
  playerState.currentPetId = null;
  playerState.currentVersionId = null;
  playerState.currentAssets = null;
  playerState.playbackState = "idle";
  playerState.activeAction = null;
  playerState.lastTriggered = null;
  playerState.operationSeq += 1;
  playerState.selectorOpen = false;
  playerState.confirmingPetId = null;
  playerState.editingPetId = null;
}
