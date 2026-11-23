// 文件用途：验证生成批次、播放器和宠物档案的状态流转及回归场景。
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  generationState,
  handleJobSnapshot,
  markFirstRoundComplete,
  resetGenerationState,
  retryWaitingWallpaper,
  startWaitingBatch,
  trackJob,
} from "@/stores/generationStore";
import {
  findPetById,
  getPetsBySpecies,
  petState,
  resetPetState,
  setDefaultWallpaper,
  setPets,
  setSavedWallpaper,
} from "@/stores/petStore";
import {
  activatePetWallpaper,
  interruptPlayback,
  openPetSelector,
  playerState,
  resetPlayerState,
  triggerHotzone,
} from "@/stores/playerStore";
import {
  guardParkedAction,
  resetSystemState,
  setDrivingMode,
  setRoute,
  systemState,
  triggerSafetyAlert,
} from "@/stores/systemStore";
import type { AssetVersionManifest, GenerationJob, PetProfile } from "@/types";

function makeAssets(species: "cat" | "dog", verId: string): AssetVersionManifest {
  const base = `/api/media/versions/${verId}`;
  const video = (slot: string) => ({
    url: `${base}/${slot}`,
    format: "mp4",
    mime: "video/mp4",
    width: 1920,
    height: 1080,
    fps: 24,
    duration: 4.0,
    aspect_ratio: "16:9",
    size_bytes: 100000,
  });
  return {
    version_id: verId,
    version_number: 1,
    created_at: "2026-11-23T00:00:00Z",
    idle_image: {
      url: `${base}/idle`,
      format: "jpeg",
      mime: "image/jpeg",
      width: 1920,
      height: 1080,
      size_bytes: 50000,
    },
    actions: {
      left: video("left"),
      center: video("center"),
      right: video("right"),
    },
  };
}

function makePet(id: string, species: "cat" | "dog", ready = true): PetProfile {
  const verId = `ver-${id}`;
  return {
    id,
    species,
    name: species === "cat" ? "橘宝" : "豆包",
    gender: "弟弟",
    breed: "",
    original_photo_url: null,
    active_version_id: ready ? verId : null,
    latest_job_id: null,
    active_assets: ready ? makeAssets(species, verId) : null,
    latest_job: null,
    created_at: "2026-11-23T00:00:00Z",
    updated_at: "2026-11-23T00:00:00Z",
  };
}

function makeReadyJob(pet: PetProfile, id: string, versionNumber = 1): GenerationJob {
  const versionId = `ver-${id}`;
  return {
    id,
    pet_id: pet.id,
    idempotency_key: id,
    provider: "mock",
    status: "ready",
    stage: "ready",
    progress: 100,
    version_id: versionId,
    error_message: null,
    assets: { ...makeAssets(pet.species, versionId), version_number: versionNumber },
    created_at: "2026-11-23T00:00:00Z",
    updated_at: "2026-11-23T00:00:02Z",
  };
}

describe("frontend stores state machine & decoupling", () => {
  beforeEach(() => {
    resetSystemState();
    resetPetState();
    resetPlayerState();
    resetGenerationState();
  });

  it("keeps the latest pet status and version when caching or receiving historic jobs", async () => {
    const pet = makePet("cat", "cat", false);
    const latest = makeReadyJob(pet, "latest", 2);
    const old = makeReadyJob(pet, "old", 1);
    setPets([{
      ...pet,
      latest_job_id: latest.id,
      latest_job: latest,
      active_version_id: latest.version_id,
      active_assets: latest.assets,
    }]);

    trackJob(latest);
    trackJob(old);
    await handleJobSnapshot(old);

    expect(petState.pets[0].latest_job_id).toBe(latest.id);
    expect(petState.pets[0].active_version_id).toBe(latest.version_id);
  });

  it("leaves the homepage active when an abandoned wallpaper preload completes", async () => {
    const cat = makePet("new-cat", "cat", false);
    const dog = makePet("saved-dog", "dog");
    setPets([cat, dog]);
    setSavedWallpaper({
      pet_id: dog.id,
      version_id: dog.active_version_id!,
      pet: dog,
      assets: dog.active_assets!,
      updated_at: dog.updated_at,
    });
    setRoute("generating", { syncHash: false });
    systemState.cutoutStrategy = "immediate";
    const ready = makeReadyJob(cat, "new-cat-job");
    startWaitingBatch([ready.id]);

    let finishPreload!: () => void;
    const pending = new Promise<void>((resolve) => { finishPreload = resolve; });
    const verifyAssets = vi.fn(async (assets: AssetVersionManifest) => {
      if (assets.version_id === ready.version_id) await pending;
    });
    const persistWallpaper = vi.fn();
    const entering = handleJobSnapshot(ready, { verifyAssets, persistWallpaper });

    interruptPlayback();
    setRoute("home", { syncHash: false });
    finishPreload();
    await entering;

    expect(systemState.route).toBe("home");
    expect(verifyAssets).toHaveBeenCalledTimes(1);
    expect(persistWallpaper).not.toHaveBeenCalled();
  });

  it("lets the first wallpaper reload the finished assets after a preload failure", async () => {
    const cat = makePet("new-cat", "cat", false);
    setPets([cat]);
    setRoute("generating", { syncHash: false });
    systemState.cutoutStrategy = "immediate";
    const ready = makeReadyJob(cat, "new-cat-job");
    startWaitingBatch([ready.id]);
    const verifyAssets = vi.fn(async () => undefined).mockRejectedValueOnce(new Error("素材 404"));
    const persistWallpaper = vi.fn(async () => ({
      pet_id: cat.id,
      version_id: ready.version_id!,
      pet: cat,
      assets: ready.assets!,
      updated_at: ready.updated_at,
    }));

    await handleJobSnapshot(ready, { verifyAssets, persistWallpaper });
    expect(generationState.waitingError?.kind).toBe("assets");
    expect(verifyAssets).toHaveBeenCalledTimes(1);
    expect(persistWallpaper).not.toHaveBeenCalled();

    await retryWaitingWallpaper({ verifyAssets, persistWallpaper });
    expect(generationState.waitingError).toBeNull();
    expect(systemState.route).toBe("wallpaper");
    expect(persistWallpaper).toHaveBeenCalledOnce();
  });

  it("keeps current wallpaper when background job finishes after leaving waiting view", async () => {
    const cat = makePet("cat-1", "cat", true);
    const dog = makePet("dog-1", "dog", false);
    setPets([cat, dog]);

    const persistMock = vi.fn(async (petId: string, versionId: string) => ({
      pet_id: petId,
      version_id: versionId,
      updated_at: "2026-11-23T00:00:01Z",
      pet: cat,
      assets: cat.active_assets!,
    }));
    const verifyMock = vi.fn(async () => undefined);

    await activatePetWallpaper(cat, { deps: { verifyAssets: verifyMock, persistWallpaper: persistMock } });
    setRoute("wallpaper", { syncHash: false });

    const dogJob: GenerationJob = {
      id: "job-dog",
      pet_id: dog.id,
      idempotency_key: "k-dog",
      provider: "mock",
      status: "ready",
      stage: "ready",
      progress: 100,
      version_id: "ver-dog-1",
      error_message: null,
      assets: makeAssets("dog", "ver-dog-1"),
      created_at: "2026-11-23T00:00:00Z",
      updated_at: "2026-11-23T00:00:02Z",
    };

    await handleJobSnapshot(dogJob, { verifyAssets: verifyMock, persistWallpaper: persistMock });

    expect(playerState.currentPetId).toBe("cat-1");
    expect(systemState.route).toBe("wallpaper");
    expect(petState.pets.find((p) => p.id === "dog-1")?.active_version_id).toBe("ver-dog-1");
  });

  it("waits for first round transition completion before cutting out when after_first_round is selected", async () => {
    const cat = makePet("cat-1", "cat", false);
    setPets([cat]);
    setRoute("generating", { syncHash: false });
    startWaitingBatch(["job-cat"]);

    const verifyMock = vi.fn(async () => undefined);
    const persistMock = vi.fn(async (petId: string, versionId: string) => ({
      pet_id: petId,
      version_id: versionId,
      updated_at: "2026-11-23T00:00:01Z",
      pet: { ...cat, active_version_id: versionId, active_assets: makeAssets("cat", versionId) },
      assets: makeAssets("cat", versionId),
    }));

    const readyJob: GenerationJob = {
      id: "job-cat",
      pet_id: cat.id,
      idempotency_key: "k-cat",
      provider: "mock",
      status: "ready",
      stage: "ready",
      progress: 100,
      version_id: "ver-cat-1",
      error_message: null,
      assets: makeAssets("cat", "ver-cat-1"),
      created_at: "2026-11-23T00:00:00Z",
      updated_at: "2026-11-23T00:00:02Z",
    };

    await handleJobSnapshot(readyJob, { verifyAssets: verifyMock, persistWallpaper: persistMock });
    expect(systemState.route).toBe("generating");

    await markFirstRoundComplete({ verifyAssets: verifyMock, persistWallpaper: persistMock });
    expect(systemState.route).toBe("wallpaper");
    expect(playerState.currentPetId).toBe("cat-1");
    expect(persistMock).toHaveBeenCalledWith("cat-1", "ver-cat-1");
  });

  it("preserves previous wallpaper and never calls saveCurrentWallpaper when switch preload fails", async () => {
    const cat = makePet("cat-1", "cat", true);
    const dog = makePet("dog-1", "dog", true);
    setPets([cat, dog]);

    const okVerify = vi.fn(async () => undefined);
    const persistMock = vi.fn(async (petId: string, versionId: string) => ({
      pet_id: petId,
      version_id: versionId,
      updated_at: "2026-11-23T00:00:01Z",
      pet: cat,
      assets: cat.active_assets!,
    }));

    await activatePetWallpaper(cat, { deps: { verifyAssets: okVerify, persistWallpaper: persistMock } });
    persistMock.mockClear();

    const failVerify = vi.fn(async () => {
      throw new Error("素材加载失败");
    });
    const res = await activatePetWallpaper(dog, {
      deps: { verifyAssets: failVerify, persistWallpaper: persistMock },
    });

    expect(res.ok).toBe(false);
    expect(playerState.currentPetId).toBe("cat-1");
    expect(playerState.playbackState).toBe("idle");
    expect(persistMock).not.toHaveBeenCalled();
  });

  it("recovers existing wallpaper on failed generation, or stays in generating on first failure", async () => {
    const firstCat = makePet("cat-first", "cat", false);
    setPets([firstCat]);
    setRoute("generating", { syncHash: false });
    startWaitingBatch(["job-fail-1"]);

    const failJob: GenerationJob = {
      id: "job-fail-1",
      pet_id: firstCat.id,
      idempotency_key: "k-fail-1",
      provider: "mock",
      status: "failed",
      stage: "center",
      progress: 50,
      version_id: null,
      error_message: "生成失败",
      assets: null,
      created_at: "2026-11-23T00:00:00Z",
      updated_at: "2026-11-23T00:00:01Z",
    };
    await handleJobSnapshot(failJob);
    expect(systemState.route).toBe("generating");

    // 若系统已有历史壁纸，则应回退恢复
    const oldDog = makePet("dog-old", "dog", true);
    setPets([oldDog, firstCat]);
    setSavedWallpaper({
      pet_id: oldDog.id,
      version_id: oldDog.active_version_id!,
      updated_at: "2026-11-23T00:00:00Z",
      pet: oldDog,
      assets: oldDog.active_assets!,
    });
    startWaitingBatch(["job-fail-2"]);
    await handleJobSnapshot({ ...failJob, id: "job-fail-2" }, { verifyAssets: async () => undefined });
    expect(systemState.route).toBe("wallpaper");
    expect(playerState.currentPetId).toBe("dog-old");
  });

  it("enforces driving restrictions, ignores double clicks while playing, and interrupts on safety alert", async () => {
    const cat = makePet("cat-1", "cat", true);
    setPets([cat]);
    await activatePetWallpaper(cat, {
      persist: false,
      deps: { verifyAssets: async () => undefined },
    });

    // 动作播放中忽略连点且锁定宠物选择入口
    expect(triggerHotzone("left", 0.17)).toBe(true);
    expect(playerState.playbackState).toBe("playing");
    expect(triggerHotzone("right", 0.83)).toBe(false);
    expect(openPetSelector()).toBe(false);

    // 系统安全驾驶提醒可立即打断动作播放
    triggerSafetyAlert();
    interruptPlayback("安全提醒打断");
    expect(playerState.playbackState).toBe("idle");
    expect(playerState.activeAction).toBeNull();

    // 行驶中禁用点击及停车操作
    setDrivingMode("driving");
    expect(triggerHotzone("center", 0.5)).toBe(false);
    expect(guardParkedAction("新增宠物")).toBe(false);
  });

  it("exposes default dog wallpaper in store queries, falls back on failure, and cleans up on reset", async () => {
    const defaultAssets = {
      ...makeAssets("dog", "default-dog-v1"),
      idle_video: {
        url: "/api/assets/default-wallpaper/idle-video",
        format: "mp4",
        mime: "video/mp4",
        width: 1920,
        height: 1080,
        fps: 24,
        duration: 4.458,
        aspect_ratio: "16:9",
        size_bytes: 4725747,
      },
    };
    const defaultDog: PetProfile = {
      ...makePet("default-dog", "dog", true),
      name: "默认狗狗",
      breed: "默认壁纸",
      is_default: true,
      active_version_id: "default-dog-v1",
      active_assets: defaultAssets,
    };

    setDefaultWallpaper({
      pet_id: defaultDog.id,
      version_id: "default-dog-v1",
      updated_at: "2026-11-23T00:00:00Z",
      pet: defaultDog,
      assets: defaultAssets,
    });

    expect(findPetById("default-dog")?.is_default).toBe(true);
    expect(getPetsBySpecies("dog").map((p) => p.id)).toContain("default-dog");
    expect(getPetsBySpecies("cat")).toHaveLength(0);

    // 无自定义历史壁纸时生成失败可回退至默认狗狗壁纸
    const firstCat = makePet("cat-new", "cat", false);
    setPets([firstCat]);
    setRoute("generating", { syncHash: false });
    startWaitingBatch(["job-fail-default"]);
    await handleJobSnapshot(
      {
        id: "job-fail-default",
        pet_id: firstCat.id,
        idempotency_key: "k-fail-default",
        provider: "mock",
        status: "failed",
        stage: "center",
        progress: 50,
        version_id: null,
        error_message: "生成失败",
        assets: null,
        created_at: "2026-11-23T00:00:00Z",
        updated_at: "2026-11-23T00:00:01Z",
      },
      { verifyAssets: async () => undefined },
    );

    expect(systemState.route).toBe("wallpaper");
    expect(playerState.currentPetId).toBe("default-dog");
    expect(playerState.currentAssets?.idle_video?.url).toBe("/api/assets/default-wallpaper/idle-video");

    resetPetState();
    expect(petState.defaultWallpaper).toBeNull();
    expect(findPetById("default-dog")).toBeUndefined();
    expect(getPetsBySpecies("dog")).toHaveLength(0);
  });
});
