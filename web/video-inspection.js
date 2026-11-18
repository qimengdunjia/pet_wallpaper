/* 文件用途：展示原始视频规格，并从成片截取开头、中段和结尾以便人工比对。 */
"use strict";

const videoInspection = (() => {
  const section = document.querySelector("#video-inspection");
  const info = document.querySelector("#video-info");
  const button = document.querySelector("#sample-frames");
  const samples = document.querySelector("#video-samples");
  const buttonLabel = button.textContent;
  let activeUrl;
  let metadata;

  /** 等待视频事件。参数为临时播放器、事件名和启动动作，返回可等待的结果。 */
  function waitForFrame(video, event, start) {
    return new Promise((resolve, reject) => {
      function cleanup() {
        clearTimeout(timeout);
        video.removeEventListener(event, loaded);
        video.removeEventListener("error", failed);
      }
      function loaded() {
        cleanup();
        resolve();
      }
      function failed() {
        cleanup();
        reject(new Error("浏览器无法解码该视频或读取关键帧。"));
      }
      const timeout = setTimeout(failed, 10000);
      video.addEventListener(event, loaded);
      video.addEventListener("error", failed);
      start();
    });
  }

  /** 更新所选成片的实测规格。参数为本地地址和可选预设，返回值为空。 */
  async function show(url, preset) {
    if (activeUrl === url) return;
    activeUrl = url;
    metadata = null;
    section.hidden = !url;
    samples.replaceChildren();
    button.disabled = false;
    button.textContent = buttonLabel;
    if (!url) return;
    info.classList.remove("spec-warning", "spec-ok");
    info.textContent = "正在读取规格…";
    try {
      const response = await fetch(url.replace("/files/", "/video-info/"));
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "无法获取实际规格。");
      if (activeUrl !== url) return;
      metadata = data;
      const actual = `${data.width}×${data.height} · ${data.aspect_ratio} · ${Number(data.fps.toFixed(2))} fps · ${data.duration.toFixed(2)}s`;
      const issues = [];
      if (preset) {
        const expectedSizes = {"720p": [1280, 720], "1080p": [1920, 1080], "4k": [3840, 2160]};
        const expectedSize = expectedSizes[preset.options.resolution];
        if (expectedSize && (data.width !== expectedSize[0] || data.height !== expectedSize[1])) issues.push("分辨率");
        if (data.aspect_ratio !== "16:9") issues.push("画幅");
        if (data.fps !== preset.target_fps) issues.push("帧率");
        if (Math.abs(data.duration - preset.options.duration) > 0.001) issues.push("时长");
      }
      const result = issues.length ? ` · 差异：${issues.join("、")}` : preset ? " · 符合预设" : "";
      info.textContent = `${actual}${result}`;
      info.classList.toggle("spec-warning", !!issues.length);
      info.classList.toggle("spec-ok", !!preset && !issues.length);
    } catch (error) {
      if (activeUrl !== url) return;
      info.textContent = error.message;
    }
  }

  button.addEventListener("click", async () => {
    const url = activeUrl;
    if (!url) return;
    button.disabled = true;
    button.textContent = "正在抽帧…";
    samples.replaceChildren();
    const video = document.createElement("video"); // 独立解码，保持主播放器进度。
    video.preload = "auto";
    video.muted = true;
    try {
      await waitForFrame(video, "loadeddata", () => { video.src = url; });
      const frameDuration = 1 / (metadata?.fps || 24);
      const duration = Math.min(metadata?.duration || video.duration, video.duration);
      if (!Number.isFinite(duration) || duration <= 0) throw new Error("该视频无有效时长。");
      const targets = [["开头", 0], ["中段", duration / 2], ["结尾", Math.max(0, duration - frameDuration / 2)]];
      const frames = [];
      for (const [label, time] of targets) {
        if (activeUrl !== url) return;
        if (Math.abs(video.currentTime - time) > 0.0001) {
          await waitForFrame(video, "seeked", () => { video.currentTime = time; });
        }
        const figure = document.createElement("figure");
        const canvas = document.createElement("canvas");
        canvas.width = Math.min(480, video.videoWidth);
        canvas.height = Math.round(canvas.width * video.videoHeight / video.videoWidth);
        canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.classList.add("sample-canvas");
        canvas.title = "点击放大查看";
        canvas.addEventListener("click", () => {
          canvas.toBlob((blob) => {
            if (!blob || typeof openLightbox !== "function") return;
            const blobUrl = URL.createObjectURL(blob);
            openLightbox(blobUrl, `${label} · ${time.toFixed(2)} 秒抽帧画面`, () => URL.revokeObjectURL(blobUrl));
          });
        });
        const caption = document.createElement("figcaption");
        caption.textContent = `${label} · ${time.toFixed(2)}s`;
        figure.append(canvas, caption);
        frames.push(figure);
      }
      if (activeUrl === url) samples.replaceChildren(...frames);
    } catch (error) {
      if (activeUrl === url) samples.textContent = error.message;
    } finally {
      video.removeAttribute("src");
      video.load();
      if (activeUrl === url) {
        button.disabled = false;
        button.textContent = buttonLabel;
      }
    }
  });
  return {show};
})();
