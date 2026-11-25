// 文件用途：验证视频内存 Blob 预加载去重缓存与双缓冲循环组件的切换行为。
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mount } from "@vue/test-utils";
import SeamlessLoopVideo from "@/components/SeamlessLoopVideo.vue";
import {
  clearVideoBlobCache,
  getPlayableVideoUrl,
  preloadVideoBlob,
  verifyAndPreloadAssets,
} from "@/lib/preload";
import type { AssetVersionManifest } from "@/types";

describe("video preload cache & seamless loop component", () => {
  const originalCreateObjectURL = URL.createObjectURL;
  const originalRevokeObjectURL = URL.revokeObjectURL;
  const originalFetch = globalThis.fetch;
  let createElementSpy: { mockRestore(): void } | null = null;

  beforeEach(() => {
    clearVideoBlobCache();
    let blobSeq = 0;
    URL.createObjectURL = vi.fn(() => `blob:mock-video-${++blobSeq}`);
    URL.revokeObjectURL = vi.fn();
    globalThis.fetch = vi.fn(async () => ({
      ok: true,
      status: 200,
      blob: async () => new Blob(["mp4data"], { type: "video/mp4" }),
    })) as unknown as typeof fetch;

    const realCreateElement = document.createElement.bind(document);
    createElementSpy = vi.spyOn(document, "createElement").mockImplementation(((tagName: string) => {
      const el = realCreateElement(tagName);
      if (tagName.toLowerCase() === "video") {
        (el as HTMLMediaElement).load = vi.fn();
        Object.defineProperty(el, "src", {
          configurable: true,
          get() {
            return el.getAttribute("src") || "";
          },
          set(val: string) {
            el.setAttribute("src", val);
            if (val) {
              queueMicrotask(() => {
                el.onloadedmetadata?.(new Event("loadedmetadata"));
              });
            }
          },
        });
      }
      return el;
    }) as typeof document.createElement);
  });

  afterEach(() => {
    clearVideoBlobCache();
    createElementSpy?.mockRestore();
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("caches and deduplicates video blob fetches and preloads all manifest videos", async () => {
    const url = "/api/assets/default-wallpaper/idle-video";
    const [u1, u2] = await Promise.all([preloadVideoBlob(url), preloadVideoBlob(url)]);
    expect(u1).toBe("blob:mock-video-1");
    expect(u2).toBe(u1);
    expect(getPlayableVideoUrl(url)).toBe("blob:mock-video-1");
    expect(globalThis.fetch).toHaveBeenCalledTimes(1);

    const OriginalImage = globalThis.Image;
    globalThis.Image = class {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      set src(_v: string) {
        queueMicrotask(() => this.onload?.());
      }
    } as unknown as typeof Image;

    try {
      const assets: AssetVersionManifest = {
        version_id: "v1",
        version_number: 1,
        created_at: "2026-11-24T00:00:00Z",
        idle_image: {
          url: "/api/assets/default-wallpaper/idle",
          format: "jpeg",
          mime: "image/jpeg",
          width: 1920,
          height: 1080,
          size_bytes: 100,
        },
        idle_video: {
          url,
          format: "mp4",
          mime: "video/mp4",
          width: 1920,
          height: 1080,
          fps: 24,
          duration: 4.458,
          aspect_ratio: "16:9",
          size_bytes: 200,
        },
        actions: {
          left: { url: "/api/v1/left", format: "mp4", mime: "video/mp4", width: 1920, height: 1080, fps: 24, duration: 4, aspect_ratio: "16:9", size_bytes: 100 },
          center: { url: "/api/v1/center", format: "mp4", mime: "video/mp4", width: 1920, height: 1080, fps: 24, duration: 4, aspect_ratio: "16:9", size_bytes: 100 },
          right: { url: "/api/v1/right", format: "mp4", mime: "video/mp4", width: 1920, height: 1080, fps: 24, duration: 4, aspect_ratio: "16:9", size_bytes: 100 },
        },
      };

      await verifyAndPreloadAssets(assets);
      expect(getPlayableVideoUrl("/api/v1/left")).toBe("blob:mock-video-2");
      expect(getPlayableVideoUrl("/api/v1/center")).toBe("blob:mock-video-3");
      expect(getPlayableVideoUrl("/api/v1/right")).toBe("blob:mock-video-4");
      expect(globalThis.fetch).toHaveBeenCalledTimes(4);
    } finally {
      globalThis.Image = OriginalImage;
    }
  });

  it("renders dual video buffers and hands off on ended fallback", async () => {
    const playSpy = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    const pauseSpy = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);

    const wrapper = mount(SeamlessLoopVideo, {
      props: {
        src: "/api/assets/transitions/chase-loop-7s.mp4",
        playing: true,
        testId: "loop-test",
      },
    });

    const videos = wrapper.findAll("video");
    expect(videos).toHaveLength(2);
    expect(videos[0].classes()).toContain("active");
    expect(videos[1].classes()).not.toContain("active");

    Object.defineProperty(videos[1].element, "readyState", { configurable: true, value: 4 });
    await videos[0].trigger("ended");
    await new Promise((r) => setTimeout(r, 140));

    expect(videos[1].classes()).toContain("active");
    expect(videos[0].classes()).not.toContain("active");
    expect(wrapper.emitted("loopRound")?.length).toBeGreaterThanOrEqual(1);
    expect(playSpy).toHaveBeenCalled();
    expect(pauseSpy).toHaveBeenCalled();

    wrapper.unmount();
  });

  it("waits for the visible round and cancels a pending buffer handoff", async () => {
    const playSpy = vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue();
    vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const wrapper = mount(SeamlessLoopVideo, { props: { src: "/idle.mp4" } });
    const [active, standby] = wrapper.findAll("video");
    Object.defineProperty(standby.element, "readyState", { value: 4 });

    // 模拟正常循环已开始预播下一层，但当前可见层尚未结束。
    let finishStandbyPlay!: () => void;
    playSpy.mockImplementationOnce(() => new Promise<void>((resolve) => { finishStandbyPlay = resolve; }));
    Object.defineProperties(active.element, {
      duration: { value: 4 },
      currentTime: { value: 3.96, writable: true },
    });
    await vi.waitFor(() => expect(playSpy).toHaveBeenCalledTimes(2));
    await wrapper.setProps({ holdAtEnd: true });
    finishStandbyPlay();

    await standby.trigger("ended");
    expect(wrapper.emitted("roundEnd")).toBeUndefined();
    await active.trigger("ended");
    expect(wrapper.emitted("roundEnd")).toHaveLength(1);
    await new Promise((resolve) => setTimeout(resolve, 120));
    expect(active.classes()).toContain("active");
    expect(playSpy).toHaveBeenCalledTimes(2);

    wrapper.unmount();
  });
});
