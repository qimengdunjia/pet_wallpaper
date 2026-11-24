// 文件用途：验证选宠面板的轮播焦点切换、指示点定位与滚轮横向滚动行为。
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { mount } from "@vue/test-utils";
import PetEditModal from "@/components/PetEditModal.vue";
import PetSelectorPanel from "@/components/PetSelectorPanel.vue";
import {
  deletePetProfile,
  generationState,
  resetGenerationState,
  trackJob,
} from "@/stores/generationStore";
import {
  petState,
  resetPetState,
  setDefaultWallpaper,
  setPets,
  setSavedWallpaper,
} from "@/stores/petStore";
import { openPetSelector, playerState, resetPlayerState, setDisplayedWallpaper } from "@/stores/playerStore";
import { resetSystemState } from "@/stores/systemStore";
import type { AssetVersionManifest, GenerationJob, PetProfile } from "@/types";

function makeAssets(verId: string): AssetVersionManifest {
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
    size_bytes: 1000,
  });
  return {
    version_id: verId,
    version_number: 1,
    created_at: "2026-11-24T00:00:00Z",
    idle_image: {
      url: `${base}/idle`,
      format: "jpeg",
      mime: "image/jpeg",
      width: 1920,
      height: 1080,
      size_bytes: 500,
    },
    actions: {
      left: video("left"),
      center: video("center"),
      right: video("right"),
    },
  };
}

function makeDog(id: string, name: string, ready = false): PetProfile {
  const assets = ready ? makeAssets(`ver-${id}`) : null;
  return {
    id,
    species: "dog",
    name,
    gender: "弟弟",
    breed: "金毛",
    original_photo_url: null,
    active_version_id: ready ? `ver-${id}` : null,
    latest_job_id: null,
    active_assets: assets,
    latest_job: null,
    created_at: "2026-11-24T00:00:00Z",
    updated_at: "2026-11-24T00:00:00Z",
  };
}

describe("PetSelectorPanel carousel & delete behavior", () => {
  beforeEach(() => {
    resetSystemState();
    resetPetState();
    resetPlayerState();
    resetGenerationState();
    vi.restoreAllMocks();
  });

  it("navigates with arrows and pagination dots and scrolls focused card into view", async () => {
    setPets([
      makeDog("dog-1", "默认狗狗"),
      makeDog("dog-2", "测试"),
      makeDog("dog-3", "测试1"),
      makeDog("dog-4", "豆包"),
    ]);

    const wrapper = mount(PetSelectorPanel);
    openPetSelector();
    await nextTick();

    const strip = wrapper.find(".pet-cards-strip").element as HTMLElement;
    const scrollToSpy = vi.fn();
    strip.scrollTo = scrollToSpy;

    expect(wrapper.findAll("[data-testid^='selector-dot-']")).toHaveLength(4);
    expect(wrapper.get("[data-testid='selector-prev-btn'] img").classes()).toContain("arrow-prev");
    expect(wrapper.get("[data-testid='selector-next-btn'] img").classes()).not.toContain("arrow-next");

    await wrapper.get("[data-testid='selector-next-btn']").trigger("click");
    await nextTick();
    expect(wrapper.get("[data-testid='selector-pet-card-dog-2']").classes()).toContain("focused");
    expect(wrapper.get("[data-testid='selector-dot-1']").classes()).toContain("active");
    expect(scrollToSpy).toHaveBeenCalled();

    await wrapper.get("[data-testid='selector-dot-3']").trigger("click");
    await nextTick();
    expect(wrapper.get("[data-testid='selector-pet-card-dog-4']").classes()).toContain("focused");
    expect(wrapper.get("[data-testid='selector-dot-3']").classes()).toContain("active");

    await wrapper.get("[data-testid='selector-prev-btn']").trigger("click");
    await nextTick();
    expect(wrapper.get("[data-testid='selector-pet-card-dog-3']").classes()).toContain("focused");

    Object.defineProperty(strip, "scrollWidth", { configurable: true, value: 1400 });
    Object.defineProperty(strip, "clientWidth", { configurable: true, value: 900 });
    const scrollBySpy = vi.fn();
    strip.scrollBy = scrollBySpy;

    await wrapper.find(".pet-cards-strip").trigger("wheel", { deltaY: 120, deltaX: 0 });
    expect(scrollBySpy).toHaveBeenCalledWith({ left: 120, behavior: "auto" });

    wrapper.unmount();
  });

  it("hides delete on default pet, confirms delete in selector and falls back current wallpaper", async () => {
    const defaultAssets = makeAssets("default-dog-v1");
    setDefaultWallpaper({
      pet_id: "default-dog",
      version_id: "default-dog-v1",
      updated_at: "2026-11-24T00:00:00Z",
      pet: { ...makeDog("default-dog", "默认狗狗", true), is_default: true },
      assets: defaultAssets,
    });
    const dogA = makeDog("dog-a", "豆包", true);
    const dogB = makeDog("dog-b", "旺财", false);
    setPets([dogA, dogB]);
    setDisplayedWallpaper(dogA.id, dogA.active_version_id!, dogA.active_assets!);
    setSavedWallpaper({
      pet_id: dogA.id,
      version_id: dogA.active_version_id!,
      updated_at: "2026-11-24T00:00:00Z",
      pet: dogA,
      assets: dogA.active_assets!,
    });

    const job: GenerationJob = {
      id: "job-dog-a",
      pet_id: dogA.id,
      idempotency_key: "k1",
      provider: "mock",
      status: "ready",
      stage: "ready",
      progress: 100,
      version_id: dogA.active_version_id,
      error_message: null,
      assets: dogA.active_assets,
      created_at: "2026-11-24T00:00:00Z",
      updated_at: "2026-11-24T00:00:00Z",
    };
    trackJob(job);

    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith(`/api/pets/${dogA.id}`)) {
        return new Response(JSON.stringify({ deleted_pet_id: dogA.id, was_current: true }), { status: 200 });
      }
      if (url.endsWith("/api/current-wallpaper")) {
        return new Response(
          JSON.stringify({ current: petState.defaultWallpaper }),
          { status: 200 },
        );
      }
      return new Response("{}", { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);

    const wrapper = mount(PetSelectorPanel);
    openPetSelector();
    await nextTick();

    expect(wrapper.find("[data-testid='selector-delete-pet-btn-default-dog']").exists()).toBe(false);
    expect(wrapper.find("[data-testid='selector-delete-pet-btn-dog-a']").exists()).toBe(true);
    expect(wrapper.find("[data-testid='selector-delete-pet-btn-dog-b']").exists()).toBe(true);

    await wrapper.get("[data-testid='selector-delete-pet-btn-dog-a']").trigger("click");
    expect(playerState.confirmingPetId).toBeNull();
    expect(wrapper.find("[data-testid='pet-delete-confirm-modal']").exists()).toBe(true);

    await wrapper.get("[data-testid='delete-pet-cancel-btn']").trigger("click");
    expect(wrapper.find("[data-testid='pet-delete-confirm-modal']").exists()).toBe(false);
    expect(petState.pets).toHaveLength(2);

    const verifyAssets = vi.fn(async () => undefined);
    const persistWallpaper = vi.fn(async () => petState.defaultWallpaper!);
    const ok = await deletePetProfile(dogA, {
      deps: { verifyAssets, persistWallpaper },
      deleteApi: async (id) => ({ deleted_pet_id: id, was_current: true }),
    });
    expect(ok).toBe(true);
    expect(petState.pets.map((p) => p.id)).toEqual(["dog-b"]);
    expect(generationState.jobsById["job-dog-a"]).toBeUndefined();
    expect(playerState.currentPetId).toBe("default-dog");
    expect(persistWallpaper).toHaveBeenCalledWith("default-dog", "default-dog-v1");

    wrapper.unmount();
  });

  it("supports deleting pet from PetEditModal and clears editing state", async () => {
    const dogB = makeDog("dog-b", "旺财", true);
    setPets([dogB]);
    openPetSelector();
    playerState.confirmingPetId = dogB.id;
    playerState.editingPetId = dogB.id;

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({ deleted_pet_id: dogB.id, was_current: false }), { status: 200 })),
    );

    const wrapper = mount(PetEditModal);
    await nextTick();

    await wrapper.get("[data-testid='edit-pet-delete-btn']").trigger("click");
    expect(wrapper.find("[data-testid='pet-delete-confirm-modal']").exists()).toBe(true);

    await wrapper.get("[data-testid='delete-pet-confirm-btn']").trigger("click");
    await new Promise((r) => setTimeout(r, 20));
    await nextTick();

    expect(petState.pets).toHaveLength(0);
    expect(playerState.editingPetId).toBeNull();
    expect(playerState.confirmingPetId).toBeNull();

    wrapper.unmount();
  });
});
