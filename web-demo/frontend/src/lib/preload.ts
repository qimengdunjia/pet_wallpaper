// 文件用途：预加载图片与视频，并共享已检查的媒体资源。
import type { AssetVersionManifest } from "@/types";

const MAX_VIDEO_BLOBS = 32;
const videoBlobCache = new Map<string, { objectUrl: string; blob: Blob }>();
const pendingVideoBlobs = new Map<string, Promise<string>>();

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

/** 获取已缓存的本地 Blob 播放地址；尚未缓存时回退原 URL。 */
export function getPlayableVideoUrl(url: string): string {
  return videoBlobCache.get(url)?.objectUrl ?? url;
}

/** 清空内存中的视频 Blob 缓存（主要用于测试隔离）。 */
export function clearVideoBlobCache(): void {
  for (const { objectUrl } of videoBlobCache.values()) {
    if (typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
      URL.revokeObjectURL(objectUrl);
    }
  }
  videoBlobCache.clear();
  pendingVideoBlobs.clear();
}

function rememberVideoBlob(url: string, objectUrl: string, blob: Blob): void {
  if (videoBlobCache.has(url)) {
    const prev = videoBlobCache.get(url);
    videoBlobCache.delete(url);
    if (prev && prev.objectUrl !== objectUrl && typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
      URL.revokeObjectURL(prev.objectUrl);
    }
  }
  videoBlobCache.set(url, { objectUrl, blob });
  while (videoBlobCache.size > MAX_VIDEO_BLOBS) {
    const oldestKey = videoBlobCache.keys().next().value;
    if (!oldestKey) break;
    const oldestVal = videoBlobCache.get(oldestKey);
    videoBlobCache.delete(oldestKey);
    if (oldestVal && typeof URL !== "undefined" && typeof URL.revokeObjectURL === "function") {
      URL.revokeObjectURL(oldestVal.objectUrl);
    }
  }
}

/**
 * 完整拉取视频到内存 Blob URL 并校验可解码元数据，消除循环回跳和重播时的网络/磁盘寻道卡顿。
 */
export function preloadVideoBlob(url: string, timeoutMs = 20000): Promise<string> {
  if (!url) {
    return Promise.resolve(url);
  }
  const cached = videoBlobCache.get(url);
  if (cached) {
    // 刷新 LRU 顺序
    videoBlobCache.delete(url);
    videoBlobCache.set(url, cached);
    return Promise.resolve(cached.objectUrl);
  }
  const pending = pendingVideoBlobs.get(url);
  if (pending) {
    return pending;
  }
  if (
    typeof fetch !== "function" ||
    typeof URL === "undefined" ||
    typeof URL.createObjectURL !== "function"
  ) {
    return preloadVideoMetadata(url, timeoutMs).then(() => url);
  }

  const task = (async () => {
    const controller = typeof AbortController !== "undefined" ? new AbortController() : null;
    const timer =
      typeof window !== "undefined"
        ? window.setTimeout(() => controller?.abort(), timeoutMs)
        : null;
    try {
      const resp = await fetch(url, {
        credentials: "same-origin",
        signal: controller?.signal,
      });
      if (!resp.ok) {
        throw new Error(`互动视频加载失败（HTTP ${resp.status}）`);
      }
      const blob = await resp.blob();
      if (!blob || blob.size === 0) {
        throw new Error("互动视频内容为空");
      }
      const objectUrl = URL.createObjectURL(blob);
      try {
        await preloadVideoMetadata(objectUrl, timeoutMs);
      } catch (err) {
        URL.revokeObjectURL(objectUrl);
        throw err;
      }
      rememberVideoBlob(url, objectUrl, blob);
      return objectUrl;
    } finally {
      if (timer !== null && typeof window !== "undefined") {
        window.clearTimeout(timer);
      }
      pendingVideoBlobs.delete(url);
    }
  })();

  pendingVideoBlobs.set(url, task);
  return task;
}

/** 根据视频地址返回已预加载的原始字节，供连续视频的缓冲区使用。 */
export async function readPreloadedVideoBytes(url: string): Promise<ArrayBuffer> {
  await preloadVideoBlob(url);
  const blob = videoBlobCache.get(url)?.blob;
  if (!blob) throw new Error("过场视频预加载失败");
  return blob.arrayBuffer();
}

/** 在后台静默预加载一套壁纸的全部视频（首屏直接展示默认/历史壁纸时使用）。 */
export function preloadAssetVideosBackground(assets: AssetVersionManifest | null | undefined): void {
  if (!assets) return;
  const urls = [
    assets.idle_video?.url,
    assets.actions.left.url,
    assets.actions.center.url,
    assets.actions.right.url,
  ].filter((u): u is string => Boolean(u));
  for (const url of urls) {
    void preloadVideoBlob(url).catch(() => undefined);
  }
}

/** 在后台静默预加载过场先导与追逐循环视频。 */
export function preloadTransitionVideos(urls: Array<string | null | undefined>): void {
  for (const url of urls) {
    if (url) {
      void preloadVideoBlob(url).catch(() => undefined);
    }
  }
}

export async function verifyAndPreloadAssets(
  assets: AssetVersionManifest,
  options?: { simulateFailure?: boolean },
): Promise<void> {
  if (options?.simulateFailure) {
    throw new Error("模拟切换壁纸资源加载失败");
  }
  await preloadImage(assets.idle_image.url);
  const videoPreloads: Array<Promise<unknown>> = [
    preloadVideoBlob(assets.actions.left.url),
    preloadVideoBlob(assets.actions.center.url),
    preloadVideoBlob(assets.actions.right.url),
  ];
  if (assets.idle_video?.url) {
    videoPreloads.push(preloadVideoBlob(assets.idle_video.url));
  }
  await Promise.all(videoPreloads);
}
