import type { AssetVersionManifest } from "@/types";

export function preloadImage(url: string, timeoutMs = 8000): Promise<void> {
  if (typeof Image === "undefined") {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const img = new Image();
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error("待机壁纸图片加载超时"));
    }, timeoutMs);

    const cleanup = () => {
      window.clearTimeout(timer);
      img.onload = null;
      img.onerror = null;
    };

    img.onload = () => {
      cleanup();
      if (typeof img.decode === "function") {
        img.decode().then(resolve, () => resolve());
      } else {
        resolve();
      }
    };
    img.onerror = () => {
      cleanup();
      reject(new Error("待机壁纸图片加载失败"));
    };
    img.src = url;
  });
}

export function preloadVideoMetadata(url: string, timeoutMs = 8000): Promise<void> {
  if (typeof document === "undefined") {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const video = document.createElement("video");
    video.preload = "metadata";
    video.muted = true;
    const timer = window.setTimeout(() => {
      cleanup();
      reject(new Error("互动视频元数据预加载超时"));
    }, timeoutMs);

    const cleanup = () => {
      window.clearTimeout(timer);
      video.onloadedmetadata = null;
      video.onerror = null;
      video.removeAttribute("src");
      video.load();
    };

    video.onloadedmetadata = () => {
      cleanup();
      resolve();
    };
    video.onerror = () => {
      cleanup();
      reject(new Error("互动视频加载失败"));
    };
    video.src = url;
  });
}

export async function verifyAndPreloadAssets(
  assets: AssetVersionManifest,
  options?: { simulateFailure?: boolean },
): Promise<void> {
  if (options?.simulateFailure) {
    throw new Error("模拟切换壁纸资源加载失败");
  }
  await preloadImage(assets.idle_image.url);
  await Promise.all([
    preloadVideoMetadata(assets.actions.left.url),
    preloadVideoMetadata(assets.actions.center.url),
    preloadVideoMetadata(assets.actions.right.url),
  ]);
}
