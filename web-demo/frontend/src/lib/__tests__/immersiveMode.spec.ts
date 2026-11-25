// 文件用途：验证壁纸沉浸模式的入口、界面隐藏、实体按键保活、画布互动及多种退出方式。
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";
import { mount } from "@vue/test-utils";
import CarBottomDock from "@/components/CarBottomDock.vue";
import SystemTopBar from "@/components/SystemTopBar.vue";
import WallpaperStageView from "@/views/WallpaperStageView.vue";
import { resetPetState, setPets } from "@/stores/petStore";
import { playerState, resetPlayerState, setDisplayedWallpaper } from "@/stores/playerStore";
import {
  isWallpaperImmersive,
  resetSystemState,
  setImmersiveMode,
  setRoute,
  showToast,
  systemState,
} from "@/stores/systemStore";
import type { AssetVersionManifest, PetProfile } from "@/types";

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
    created_at: "2026-11-25T00:00:00Z",
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

function setupWallpaperPet(): PetProfile {
  const assets = makeAssets("ver-dog-1");
  const dog: PetProfile = {
    id: "dog-1",
    species: "dog",
    name: "豆包",
    gender: "弟弟",
    breed: "柯基",
    original_photo_url: null,
    active_version_id: assets.version_id,
    latest_job_id: null,
    active_assets: assets,
    latest_job: null,
    created_at: "2026-11-25T00:00:00Z",
    updated_at: "2026-11-25T00:00:00Z",
  };
  setPets([dog]);
  setDisplayedWallpaper(dog.id, assets.version_id, assets);
  return dog;
}

describe("wallpaper immersive mode", () => {
  beforeEach(() => {
    resetSystemState();
    resetPetState();
    resetPlayerState();
    vi.restoreAllMocks();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(new Blob(["video"], { type: "video/mp4" }), { status: 200 })),
    );
    vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  });

  it("only enables immersive mode on wallpaper route and auto-exits when leaving", () => {
    setRoute("home", { syncHash: false });
    setImmersiveMode(true);
    expect(systemState.immersiveMode).toBe(false);
    expect(isWallpaperImmersive()).toBe(false);

    setRoute("wallpaper", { syncHash: false });
    systemState.drawerOpen = true;
    showToast("提示文本");
    setImmersiveMode(true);
    expect(isWallpaperImmersive()).toBe(true);
    expect(systemState.drawerOpen).toBe(false);
    expect(systemState.toast).toBeNull();

    setRoute("home", { syncHash: false });
    expect(systemState.immersiveMode).toBe(false);
    expect(isWallpaperImmersive()).toBe(false);
  });

  it("hides top bar, bottom dock, floating info, guides and controls while keeping seat key mounted and canvas interactive", async () => {
    setupWallpaperPet();
    setRoute("wallpaper", { syncHash: false });
    systemState.showHotzoneGuides = true;
    systemState.config = {
      provider: "mock",
      mock_controls_enabled: true,
      default_mock_delay_seconds: 2,
      max_upload_mb: 10,
      seat_key_url: "ws://192.168.4.1/ws",
      transitions: {
        intro: null,
        loop: null,
      },
      sample_uploads: {
        cat: "/cat.jpg",
        dog: "/dog.jpg",
      },
    };

    const topBar = mount(SystemTopBar, { attachTo: document.body });
    const bottomDock = mount(CarBottomDock, { attachTo: document.body });
    const stage = mount(WallpaperStageView, { attachTo: document.body });
    await nextTick();

    expect(topBar.find("[data-testid='toggle-immersive']").exists()).toBe(true);
    expect(bottomDock.find("[data-testid='car-bottom-dock']").exists()).toBe(true);
    expect(stage.find("[data-testid='floating-stage-info']").exists()).toBe(true);
    expect(stage.find("[data-testid='hotzone-guides']").exists()).toBe(true);
    const controlsBar = stage.get("[data-testid='mode-controls-bar']");
    expect((controlsBar.element as HTMLElement).style.display).not.toBe("none");
    expect(controlsBar.isVisible()).toBe(true);
    expect(stage.find(".seat-key-control").exists()).toBe(true);

    // 点击进入沉浸模式
    await topBar.get("[data-testid='toggle-immersive']").trigger("click");
    await nextTick();

    expect(isWallpaperImmersive()).toBe(true);
    expect(topBar.find("[data-testid='system-topbar']").exists()).toBe(false);
    expect(bottomDock.find("[data-testid='car-bottom-dock']").exists()).toBe(false);
    expect(stage.find("[data-testid='floating-stage-info']").exists()).toBe(false);
    expect(stage.find("[data-testid='hotzone-guides']").exists()).toBe(false);
    expect(stage.find("[data-testid='exit-immersive-btn']").exists()).toBe(false);
    expect((controlsBar.element as HTMLElement).style.display).toBe("none");
    expect(controlsBar.isVisible()).toBe(false);
    // SeatKeyControl 保持挂载不断开 WebSocket
    expect(stage.find(".seat-key-control").exists()).toBe(true);

    // 沉浸模式下画布点击互动仍然生效
    const canvas = stage.get("[data-testid='wallpaper-canvas']");
    vi.spyOn(canvas.element, "getBoundingClientRect").mockReturnValue({
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 1600,
      bottom: 900,
      width: 1600,
      height: 900,
      toJSON: () => ({}),
    });
    await canvas.trigger("click", { clientX: 800, clientY: 450 });
    expect(playerState.playbackState).toBe("playing");
    expect(playerState.activeAction).toBe("center");

    // 按 Escape 退出沉浸模式
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    await nextTick();

    expect(isWallpaperImmersive()).toBe(false);
    expect(topBar.find("[data-testid='system-topbar']").exists()).toBe(true);
    expect(bottomDock.find("[data-testid='car-bottom-dock']").exists()).toBe(true);
    expect(stage.find("[data-testid='floating-stage-info']").exists()).toBe(true);
    expect(stage.get("[data-testid='mode-controls-bar']").isVisible()).toBe(true);

    topBar.unmount();
    bottomDock.unmount();
    stage.unmount();
  });

  it("reveals exit button via top edge hover or click and supports touch swipe down to exit", async () => {
    setupWallpaperPet();
    setRoute("wallpaper", { syncHash: false });
    const stage = mount(WallpaperStageView);

    setImmersiveMode(true);
    await nextTick();
    expect(stage.find("[data-testid='exit-immersive-btn']").exists()).toBe(false);

    // 刚进入时指针还在顶部不会立即误触显示退出按钮
    const topMove = new Event("pointermove");
    Object.defineProperties(topMove, {
      clientY: { value: 12 },
      pointerType: { value: "mouse" },
    });
    window.dispatchEvent(topMove);
    await nextTick();
    expect(stage.find("[data-testid='exit-immersive-btn']").exists()).toBe(false);

    // 指针离开顶部区域后再移回顶部，唤出退出按钮
    const awayMove = new Event("pointermove");
    Object.defineProperties(awayMove, {
      clientY: { value: 200 },
      pointerType: { value: "mouse" },
    });
    window.dispatchEvent(awayMove);
    window.dispatchEvent(topMove);
    await nextTick();
    expect(stage.find("[data-testid='exit-immersive-btn']").exists()).toBe(true);

    await stage.get("[data-testid='exit-immersive-btn']").trigger("click");
    await nextTick();
    expect(isWallpaperImmersive()).toBe(false);

    // 再次进入后，验证触屏从顶部感应条下拉退出
    setImmersiveMode(true);
    await nextTick();
    const hotspot = stage.get("[data-testid='immersive-exit-hotspot']");
    await hotspot.trigger("touchstart", { touches: [{ clientY: 10 }] });
    await hotspot.trigger("touchmove", { touches: [{ clientY: 60 }] });
    await nextTick();
    expect(isWallpaperImmersive()).toBe(false);

    stage.unmount();
  });
});
