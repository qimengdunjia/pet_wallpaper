/* 文件用途：管理两个测试页的图片选择、提示词、生成结果和历史任务。 */
"use strict";

const $ = (selector) => document.querySelector(selector);
const kind = document.body.dataset.jobKind;
const isVideo = kind === "video";
const generationPreset = $(isVideo ? "#video-preset" : "#image-preset");
const promptPresetsURL = `/api/prompt-presets/${kind}`;
const stage = isVideo ? "video" : "idle";
const outputLabel = isVideo ? "视频" : "待机图";
const historyKey = `pet-wallpaper-${kind}-job`;
const statusLabels = {queued: "排队中", running: "生成中", complete: "已完成", failed: "失败", needs_review: "待核对"};

let config = {};
let currentJob = null;
let selectedFile = null;
const referenceDraft = []; // 按添加顺序保存图生图的待提交文件和预览。
let styleDraft = null; // 同批共用的姿态风格图及预览。
let batchJobs = []; // 当前展示的批次，按上传顺序排列。
let previewURL = null; // 上传预览用的临时 URL。
let selectedSource = null; // 首帧选中的素材记录，含上传 ID 或生成任务与版本。
const videoReferenceDraft = []; // Omni 普通参考图按上传顺序保留。
let selectedTail = null;
let selectedTailSource = null; // 尾帧选中的素材记录。
let tailPreviewURL = null;
let requesting = false;
let polling = false;
let selectionVersion = 0; // 忽略历史切换前发起的请求。
let galleryButtons = [];
let updatingGallery = false; // 串行处理素材操作，避免旧列表覆盖新结果。
let lastVideoTime = 0;
let loops = 0;
let savedPrompts = Object.create(null); // 键为当前页面的预设 ID，含用户修改和命名副本。
let promptsLoaded = false;
let savingPrompt = false;
let comparingOriginal = false;
let activePresetTab = null; // 当前高亮的一级分类，辅助无子项或自存切换。

function busy() {
  return requesting || config.busy || ["queued", "running"].includes(currentJob?.status);
}

/** 请求本机接口；参数为地址与选项，返回 JSON，失败时抛出错误。 */
async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "请求内容不正确，请检查后重试");
  return data;
}

function showError(message = "") {
  $("#alert").textContent = message;
  $("#alert").hidden = !message;
}

function showToast(message, type = "info") {
  let container = $(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.className = "toast-container";
    document.body.append(container);
  }
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.append(toast);
  setTimeout(() => {
    toast.classList.add("leaving");
    setTimeout(() => toast.remove(), 220);
  }, 2400);
}

function openLightbox(src, alt = "", onClose = null) {
  if (!src) return;
  const overlay = document.createElement("div");
  overlay.className = "lightbox-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-label", "高清壁纸全屏预览");

  const container = document.createElement("div");
  container.className = "lightbox-container";

  const img = document.createElement("img");
  img.src = src;
  img.alt = alt || "高清壁纸预览";

  const closeBtn = document.createElement("button");
  closeBtn.type = "button";
  closeBtn.className = "lightbox-close";
  closeBtn.setAttribute("aria-label", "关闭全屏预览");
  closeBtn.textContent = "✕";

  container.append(img, closeBtn);
  overlay.append(container);
  document.body.append(overlay);

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    overlay.classList.add("leaving");
    window.removeEventListener("keydown", onKeyDown);
    setTimeout(() => {
      overlay.remove();
      if (typeof onClose === "function") onClose();
    }, 180);
  };

  const onKeyDown = (e) => {
    if (e.key === "Escape") close();
  };

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay || e.target === closeBtn) close();
  });
  window.addEventListener("keydown", onKeyDown);
}

function dateLabel(value) {
  return new Date(value).toLocaleString("zh-CN", {month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit"});
}

function formatDuration(ms) {
  const sec = Math.max(0, Math.floor(ms / 1000));
  const m = String(Math.floor(sec / 60)).padStart(2, "0");
  const s = String(sec % 60).padStart(2, "0");
  return `${m}:${s}`;
}

function imageKey(image) { return image.asset_id || `${image.job_id}:${image.version}`; }

/** 将素材来源写入视频表单；参数为表单、字段前缀和素材记录，无返回值。 */
function appendFrameSource(form, prefix, image) {
  if (image.asset_id) {
    form.append(`${prefix}_asset_id`, image.asset_id);
  } else {
    form.append(`${prefix}_job_id`, image.job_id);
    form.append(`${prefix}_version`, image.version);
  }
}

function basePreset(id = generationPreset.value) {
  return savedPrompts[id]?.name ? savedPrompts[id].base_preset || "" : id;
}

function imagePreset() { return config.image_presets?.[basePreset()]; }

function videoPresets() { return Object.assign(Object.create(null), ...Object.values(config.video_presets || {})); }

function presetPrompt(id) {
  const presets = isVideo ? videoPresets() : config.image_presets;
  return savedPrompts[id]?.prompt ?? presets?.[id]?.prompt;
}

function presetLabel(id) {
  if (savedPrompts[id]?.name) return savedPrompts[id].name;
  return (isVideo ? videoPresets()[id] : config.image_presets?.[id])?.label || "";
}

function showPromptStatus(message = "", failed = false) {
  const status = $("#prompt-save-status");
  status.textContent = message;
  status.classList.toggle("save-error", failed);
  status.hidden = !message;
}

/** 构造预设分类结构供分段选项卡与子选项渲染。 */
function getPresetCategories() {
  const categories = [];
  if (isVideo) {
    categories.push({id: "custom", label: "自定义", presets: [{id: "", label: "自定义动作"}]});
    for (const [group, presets] of Object.entries(config.video_presets || {})) {
      const shortName = group === "猫咪" ? "猫咪动作" : group === "狗狗" ? "狗狗动作" : group;
      categories.push({
        id: group,
        label: shortName,
        presets: Object.entries(presets).map(([id, spec]) => ({id, label: spec.label})),
      });
    }
  } else {
    categories.push({id: "custom", label: "批量出图", presets: [{id: "", label: "自定义 · 批量出图"}]});
    const imgPresets = config.image_presets || {};
    if (imgPresets["cat-idle"]) categories.push({id: "cat-idle", label: "猫咪待机", presets: [{id: "cat-idle", label: "猫咪待机"}]});
    if (imgPresets["dog-idle"]) categories.push({id: "dog-idle", label: "狗狗待机", presets: [{id: "dog-idle", label: "狗狗待机"}]});
    const chase = Object.entries(imgPresets)
      .filter(([id]) => id.startsWith("chase-"))
      .map(([id, spec]) => ({id, label: spec.label.replace(/^追逐 · |^切换 · /, "")}));
    if (chase.length) categories.push({id: "chase", label: "追逐关键帧", presets: chase});
  }
  const savedEntries = Object.entries(savedPrompts).filter(([, record]) => record.name);
  if (savedEntries.length) {
    categories.push({
      id: "saved",
      label: `自存 (${savedEntries.length})`,
      presets: savedEntries.map(([id, record]) => ({id, label: record.name})),
    });
  }
  return categories;
}

/** 根据当前预设值渲染简洁的分类标签和子选项药丸。 */
function renderPresetUI(disabled) {
  const categories = getPresetCategories();
  const currentId = generationPreset.value;
  let matchedCategory = categories.find((cat) => cat.presets.some((item) => item.id === currentId));
  if (!matchedCategory) matchedCategory = categories[0];
  activePresetTab = matchedCategory?.id || "custom";

  const catBar = $("#preset-categories");
  catBar.replaceChildren(...categories.map((cat) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "seg-btn";
    btn.textContent = cat.label;
    btn.disabled = disabled;
    btn.setAttribute("aria-pressed", String(cat.id === activePresetTab));
    btn.addEventListener("click", () => {
      if (disabled) return;
      const targetId = cat.presets.some((item) => item.id === generationPreset.value)
        ? generationPreset.value
        : cat.presets[0].id;
      if (generationPreset.value !== targetId) {
        generationPreset.value = targetId;
        generationPreset.dispatchEvent(new Event("change"));
      } else {
        renderPresetUI(disabled);
      }
    });
    return btn;
  }));

  const subRow = $("#preset-subpills");
  const showSubs = matchedCategory && matchedCategory.presets.length > 1;
  subRow.hidden = !showSubs;
  if (showSubs) {
    subRow.replaceChildren(...matchedCategory.presets.map((item) => {
      const pill = document.createElement("button");
      pill.type = "button";
      pill.className = "subpill";
      pill.textContent = item.label;
      pill.disabled = disabled;
      pill.setAttribute("aria-pressed", String(item.id === currentId));
      pill.addEventListener("click", () => {
        if (disabled || generationPreset.value === item.id) return;
        generationPreset.value = item.id;
        generationPreset.dispatchEvent(new Event("change"));
      });
      return pill;
    }));
  } else {
    subRow.replaceChildren();
  }
}

/** 更新自存预设选项。参数为保存后选中的 ID，可省略以保留当前选择。 */
function renderSavedPrompts(selected = generationPreset.value) {
  generationPreset.querySelector("[data-saved-prompts]")?.remove();
  const entries = Object.entries(savedPrompts).filter(([, record]) => record.name);
  if (entries.length) {
    const group = document.createElement("optgroup");
    group.label = "自存提示词";
    group.dataset.savedPrompts = "";
    for (const [id, record] of entries) group.append(new Option(record.name, id));
    generationPreset.append(group);
  }
  generationPreset.value = selected;
}

function renderPromptControls(running) {
  const selected = generationPreset.value;
  const prompt = $("#prompt").value.trim();
  const disabled = running || savingPrompt || !promptsLoaded;
  const defaultForSelected = selected ? (presetPrompt(selected) ?? "") : "";
  const isModified = !!selected && prompt !== defaultForSelected;

  const update = $("#prompt-update");
  const saveAs = $("#prompt-save-as");
  const reset = $("#btn-reset-prompt");
  const dirty = $("#prompt-dirty");

  if (dirty) dirty.hidden = !isModified;
  if (reset) {
    reset.hidden = !isModified;
    reset.disabled = disabled;
  }
  update.hidden = !selected || !isModified;
  update.disabled = disabled || !prompt || !isModified;
  saveAs.disabled = disabled || !prompt;
  saveAs.textContent = selected ? "另存为预设" : "保存为预设";
  $("#prompt-preset-name").disabled = disabled;
  $("#prompt-save-confirm").disabled = disabled || !prompt;
  $("#prompt-save-cancel").disabled = savingPrompt;
}

function insertPromptToken(token) {
  const textarea = $("#prompt");
  if (!textarea || textarea.disabled) return;
  const start = textarea.selectionStart ?? textarea.value.length;
  const end = textarea.selectionEnd ?? textarea.value.length;
  const before = textarea.value.slice(0, start);
  const after = textarea.value.slice(end);
  const padBefore = before && !/\s$/.test(before) ? " " : "";
  const padAfter = after && !/^\s/.test(after) ? " " : "";
  textarea.value = `${before}${padBefore}${token}${padAfter}${after}`;
  const cursor = start + padBefore.length + token.length;
  textarea.focus();
  textarea.setSelectionRange(cursor, cursor);
  textarea.dispatchEvent(new Event("input"));
  showToast(`已插入 ${token}`);
}

/** 保存当前提示词。参数 asNew 区分另存与直接更新，成功后刷新预设选项。 */
async function savePrompt(asNew) {
  if (busy() || savingPrompt || !promptsLoaded) return;
  const selected = generationPreset.value;
  const prompt = $("#prompt").value.trim();
  const name = $("#prompt-preset-name").value.trim();
  if (!prompt || (!asNew && (!selected || prompt === presetPrompt(selected)))) return;
  if (asNew && !name) {
    showPromptStatus("请输入预设名称。", true);
    return;
  }
  savingPrompt = true;
  showPromptStatus();
  render();
  try {
    const address = asNew ? promptPresetsURL : `${promptPresetsURL}/${encodeURIComponent(selected)}`;
    const body = asNew ? {name, prompt, base_preset: basePreset() || null} : {prompt};
    const {id, ...record} = await api(address, {
      method: asNew ? "POST" : "PUT",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
    savedPrompts[id] = record;
    if (asNew) renderSavedPrompts(id);
    $("#prompt-save-form").hidden = true;
    showPromptStatus("已保存");
    showToast(asNew ? `新预设「${name}」已保存` : "提示词修改已更新");
  } catch (error) {
    showPromptStatus(error.message, true);
  } finally {
    savingPrompt = false;
    render();
  }
}

function imageLabel(image) {
  if (image.asset_id) return image.name;
  return [config.image_presets?.[image.preset]?.label, dateLabel(image.created_at), `v${image.version}`]
    .filter(Boolean).join(" · ");
}

function photoRole(index) {
  if (imagePreset()?.min_photos === 2) return ["猫咪正面照", "狗狗正面照", "场景参考图"][index] || `额外图片 ${index + 1}`;
  return imagePreset() ? "宠物正面照" : `原图 ${index + 1}`;
}

function setPreview(preview, url) {
  if (!preview) return;
  if (url && preview.getAttribute("src") !== url) preview.src = url;
  if (!url) preview.removeAttribute("src");
  preview.hidden = !url;
}

function setFirst(file, source = null) {
  if (previewURL) URL.revokeObjectURL(previewURL);
  selectedFile = file;
  selectedSource = source;
  previewURL = file ? URL.createObjectURL(file) : null;
  const url = source?.url || previewURL;
  setPreview($("#upload-preview"), url);
  $("#dropzone").classList.toggle("has-image", !!url);
  $("#upload-label").textContent = source ? imageLabel(source) : (file?.name || "上传或从下方点选");
  if (isVideo) {
    if (!file) $("#photo").value = "";
    const page = new URL(location.href);
    if (source) page.searchParams.set("source", imageKey(source));
    else page.searchParams.delete("source");
    history.replaceState(null, "", page);
  }
  showError();
  render();
}

function setTail(file, source = null) {
  if (file && !checkFile(file)) return showError("请选择符合大小要求的 JPG 或 PNG 尾帧。");
  if (tailPreviewURL) URL.revokeObjectURL(tailPreviewURL);
  selectedTail = file;
  selectedTailSource = source;
  tailPreviewURL = file ? URL.createObjectURL(file) : null;
  setPreview($("#tail-preview"), source?.url || tailPreviewURL);
  $("#tail-zone").classList.toggle("has-image", !!(file || source));
  if (!file) $("#tail-photo").value = "";
  showError();
  render();
}

/** 互换首尾帧（不提前释放仍需使用的本地预览 URL）。 */
function swapFirstAndTail() {
  if (!isVideo || busy()) return;
  const prevFirstFile = selectedFile;
  const prevFirstSource = selectedSource;
  const prevFirstUrl = previewURL;

  selectedFile = selectedTail;
  selectedSource = selectedTailSource;
  previewURL = tailPreviewURL;

  selectedTail = prevFirstFile;
  selectedTailSource = prevFirstSource;
  tailPreviewURL = prevFirstUrl;

  const firstUrl = selectedSource?.url || previewURL;
  setPreview($("#upload-preview"), firstUrl);
  $("#dropzone").classList.toggle("has-image", !!firstUrl);
  $("#upload-label").textContent = selectedSource ? imageLabel(selectedSource) : (selectedFile?.name || "上传或从下方点选");

  const tailUrl = selectedTailSource?.url || tailPreviewURL;
  setPreview($("#tail-preview"), tailUrl);
  $("#tail-zone").classList.toggle("has-image", !!tailUrl);

  const page = new URL(location.href);
  if (selectedSource) page.searchParams.set("source", imageKey(selectedSource));
  else page.searchParams.delete("source");
  history.replaceState(null, "", page);
  showToast("已互换首尾帧");
  render();
}

function checkFile(file) {
  return ["image/jpeg", "image/png"].includes(file.type) && file.size <= (config.max_upload_mb || 10) * 1024 * 1024;
}

function selectPhoto(file) {
  if (!file || busy()) return;
  if (!checkFile(file)) return showError("请选择符合大小要求的 JPG 或 PNG 图片。");
  setFirst(file);
}

function referenceCard(url, label, {clickableToken = false, zoomable = true} = {}) {
  const card = document.createElement("li");
  const image = document.createElement("img");
  image.src = url;
  image.alt = label;
  image.loading = "lazy";
  if (zoomable) {
    image.classList.add("zoomable-thumb");
    image.title = "点击放大查看";
    image.addEventListener("click", (e) => {
      e.preventDefault();
      openLightbox(url, label);
    });
  }
  const token = document.createElement(clickableToken ? "button" : "code");
  if (clickableToken) {
    token.type = "button";
    token.className = "token-insert-btn";
    token.title = `点击插入 ${label} 到提示词`;
    token.addEventListener("click", () => insertPromptToken(label));
  }
  token.textContent = label;
  token.title = label;
  card.append(image, token);
  return card;
}

/** 更新选择区；无参数，按当前上传顺序显示预览和提示词编号。 */
function updateReferenceDraft() {
  const list = $("#reference-draft");
  const singleMode = imagePreset()?.max_photos === 1;
  if (singleMode && referenceDraft.length <= 1) {
    list.replaceChildren();
    list.hidden = true;
    render();
    return;
  }
  list.replaceChildren(...referenceDraft.map(({file, url}, index) => {
    const role = photoRole(index);
    const card = referenceCard(url, role);
    card.title = file.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "card-remove-x";
    remove.textContent = "✕";
    remove.setAttribute("aria-label", `移除原图 ${index + 1}`);
    remove.addEventListener("click", () => {
      if (busy()) return;
      URL.revokeObjectURL(referenceDraft.splice(index, 1)[0].url);
      updateReferenceDraft();
    });
    card.append(remove);
    return card;
  }));
  list.hidden = !referenceDraft.length;
  render();
}

/** 渲染 Omni 参考图，并随帧模式更新提示词编号。 */
function updateVideoReferences() {
  const offset = $("#video-frame-mode").value === "first_last" ? 3 : 2;
  const list = $("#video-reference-draft");
  list.replaceChildren(...videoReferenceDraft.map(({file, url}, index) => {
    const card = referenceCard(url, `<<<image_${index + offset}>>>`, {clickableToken: true});
    card.title = file.name;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "card-remove-x";
    remove.textContent = "✕";
    remove.setAttribute("aria-label", `移除参考图 ${index + 1}`);
    remove.disabled = busy();
    remove.addEventListener("click", () => {
      if (busy()) return;
      URL.revokeObjectURL(videoReferenceDraft.splice(index, 1)[0].url);
      updateVideoReferences();
    });
    card.append(remove);
    return card;
  }));
  list.hidden = !videoReferenceDraft.length;
}

function selectUploads(files) {
  if (isVideo) return selectPhoto(files[0]);
  if (!files.length || busy()) return;
  const limit = imagePreset()?.max_photos || config.max_image_references;
  if (limit === 1 && files.length === 1 && checkFile(files[0])) {
    for (const {url} of referenceDraft.splice(0)) URL.revokeObjectURL(url);
  }
  if (referenceDraft.length + files.length > limit) {
    return showError(`当前预设最多可添加 ${limit} 张图片。`);
  }
  if (Array.from(files).some((file) => !checkFile(file))) {
    return showError("每张原图都需为符合大小要求的 JPG 或 PNG。");
  }
  for (const file of files) referenceDraft.push({file, url: URL.createObjectURL(file)});
  showError();
  updateReferenceDraft();
}

/** 设置批次的姿态风格图，保留用户手动编辑过的提示词。 */
function setStyle(file) {
  if (busy()) return;
  if (file && !checkFile(file)) return showError("请选择符合大小要求的 JPG 或 PNG 姿态风格图。");
  if (styleDraft) URL.revokeObjectURL(styleDraft.url);
  styleDraft = file ? {file, url: URL.createObjectURL(file)} : null;
  setPreview($("#style-preview"), styleDraft?.url);
  $("#style-dropzone").classList.toggle("has-image", !!file);
  $("#style-label").textContent = file ? `姿态底图 · ${file.name}` : "添加姿态风格底图（可选 · 整批共用）";
  const prompt = $("#prompt");
  if (!generationPreset.value && [config.default_image_prompt, config.default_image_style_prompt].includes(prompt.value)) {
    prompt.value = file ? config.default_image_style_prompt : config.default_image_prompt;
  }
  showError();
  render();
}

/** 刷新素材卡片；参数为素材列表和可选的首帧标识，无返回值。 */
function renderGallery(images, preselect) {
  const firstKey = selectedSource ? imageKey(selectedSource) : !selectedFile && preselect;
  galleryButtons = images.map((image) => {
    const card = document.createElement("div");
    card.className = "idle-card";

    const button = document.createElement("button");
    button.type = "button";
    button.className = "idle-choice";
    const img = document.createElement("img");
    img.src = image.url;
    img.alt = "";
    img.loading = "lazy";
    const label = document.createElement("span");
    label.className = "idle-name";
    label.textContent = imageLabel(image);
    const frameTag = document.createElement("span");
    frameTag.className = "idle-frame-tag";
    frameTag.hidden = true;
    button.title = `点击设为首帧 · ${label.textContent}`;
    button.setAttribute("aria-label", label.textContent);
    button.append(img, frameTag, label);
    button.addEventListener("click", () => setFirst(null, image));

    const footer = document.createElement("div");
    footer.className = "idle-card-footer";

    const setTailBtn = document.createElement("button");
    setTailBtn.type = "button";
    setTailBtn.className = "idle-set-tail";
    setTailBtn.textContent = "设为尾帧";
    setTailBtn.addEventListener("click", () => {
      const isCurrentlyTail = selectedTailSource && imageKey(selectedTailSource) === imageKey(image);
      setTail(null, isCurrentlyTail ? null : image);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "idle-remove";
    remove.textContent = "删除";
    remove.setAttribute("aria-label", `删除素材 ${label.textContent}`);
    remove.addEventListener("click", () => deleteGalleryImage(image));

    footer.append(setTailBtn, remove);
    card.append(button, footer);
    return {card, button, frameTag, setTailBtn, remove, image};
  });

  $("#idle-gallery").replaceChildren(...galleryButtons.map(({card}) => card));
  $("#idle-gallery").hidden = images.length === 0;
  $("#gallery-count").textContent = images.length ? `· ${images.length} 张` : "";

  if (selectedTailSource) {
    const tail = images.find((image) => imageKey(image) === imageKey(selectedTailSource));
    setTail(null, tail);
  }
  $("#gallery-empty").hidden = images.length > 0;
  $("#gallery-empty").textContent = "暂无素材，可点击上方添加图片或先去「图生图」生成";
  if (firstKey) {
    const image = images.find((item) => imageKey(item) === firstKey);
    setFirst(null, image);
    if (!image && preselect) showError("该素材已不可用，请选择其他图片。");
  }
}

/** 执行素材库操作；参数为返回新列表的异步函数和可选的首帧标识，返回是否成功。 */
async function updateGallery(loadImages, preselect) {
  if (updatingGallery) return false;
  updatingGallery = true;
  showError();
  render();
  try {
    renderGallery(await loadImages(), preselect);
    return true;
  } catch (error) {
    showError(error.message);
    return false;
  } finally {
    updatingGallery = false;
    render();
  }
}

function loadGallery(preselect) {
  return updateGallery(async () => (await api("/api/idle-images")).images, preselect);
}

/** 提交本机图片到素材库；参数为待上传文件，无返回值。 */
async function addGalleryImage(file) {
  if (!file) return;
  if (!checkFile(file)) return showError("请选择符合大小要求的 JPG 或 PNG 图片。");
  const form = new FormData();
  form.append("file", file);
  const added = await updateGallery(async () => {
    const image = await api("/api/idle-images", {method: "POST", body: form});
    return [image, ...galleryButtons.map((item) => item.image)];
  });
  if (added) showToast("已添加到素材库");
}

/** 确认并删除指定素材；参数为卡片对应的素材记录，无返回值。 */
async function deleteGalleryImage(image) {
  if (!confirm(`从素材库删除「${imageLabel(image)}」？`)) return;
  const key = imageKey(image);
  const path = image.asset_id ? image.url : `/api/idle-images/${image.job_id}/${image.version}`;
  const usedAsFirst = selectedSource && imageKey(selectedSource) === key;
  const usedAsTail = selectedTailSource && imageKey(selectedTailSource) === key;
  const removed = await updateGallery(async () => {
    await api(path, {method: "DELETE"});
    return galleryButtons.map((item) => item.image).filter((item) => imageKey(item) !== key);
  });
  if (removed) {
    if (usedAsFirst) setFirst(null);
    if (usedAsTail) setTail(null);
    $("#add-image").focus();
    showToast(usedAsTail || usedAsFirst ? "已删除素材并清理对应帧位" : "已删除素材");
  }
}

function readVideoOptions() {
  return {
    model: $("#video-model").value,
    duration: Number($("#video-duration").value),
    resolution: $("#video-resolution").value,
    frame_mode: $("#video-frame-mode").value,
  };
}

function readImageOptions() {
  return {
    model: $("#image-model").value,
    resolution: $("#image-resolution").value,
    aspect_ratio: $("#image-aspect-ratio").value,
  };
}

function updateImageOptions(previous) {
  const model = config.image_models[$("#image-model").value];
  const defaults = config.default_image_options;
  const ratios = model.aspect_ratios || config.image_aspect_ratios;
  const resolution = $("#image-resolution");
  resolution.replaceChildren(...model.resolutions.map((value) => new Option(value.toUpperCase(), value)));
  resolution.value = model.resolutions.includes(previous.resolution) ? previous.resolution : defaults.resolution;
  const ratio = $("#image-aspect-ratio");
  ratio.replaceChildren(...ratios.map((value) => new Option(value === "auto" ? "自动" : value, value)));
  ratio.value = ratios.includes(previous.aspect_ratio) ? previous.aspect_ratio : defaults.aspect_ratio;
}

function updateVideoOptions(previous) {
  const model = config.video_models[$("#video-model").value];
  const minimum = config.min_video_duration;
  const duration = Math.min(previous.duration, model.max_duration);
  const choices = Array.from({length: model.max_duration - minimum + 1}, (_, i) => minimum + i);
  $("#video-duration").replaceChildren(...choices.map((seconds) => new Option(`${seconds} 秒`, seconds)));
  $("#video-duration").value = duration;
  $("#video-resolution").replaceChildren(...model.resolutions.map((value) => new Option(value === "4k" ? "4K" : value, value)));
  $("#video-resolution").value = model.resolutions.includes(previous.resolution) ? previous.resolution : model.resolutions[0];
  $("#video-frame-mode").replaceChildren(...model.frame_modes.map((value) => new Option(value === "first" ? "仅首帧" : "首尾帧", value)));
  $("#video-frame-mode").value = model.frame_modes.includes(previous.frame_mode) ? previous.frame_mode : model.frame_modes[0];
}

/** 应用 PRD 视频预设。参数为预设 ID，更新提示词和参数，保留已选首帧。 */
function applyVideoPreset(id) {
  const preset = videoPresets()[basePreset(id)];
  if (preset) {
    $("#video-model").value = preset.options.model;
    updateVideoOptions(preset.options);
    setTail(null);
  }
  const prompt = presetPrompt(id);
  if (prompt !== undefined) $("#prompt").value = prompt;
  render();
}

function updateStatusTimer() {
  const timer = $("#status-timer");
  if (!timer) return;
  const isRunning = ["queued", "running"].includes(currentJob?.status);
  timer.hidden = !isRunning;
  if (!isRunning) {
    timer.textContent = "";
    return;
  }
  const output = currentJob?.stages?.[stage];
  const since = Date.parse(output?.attempt?.created_at || currentJob?.updated_at || currentJob?.created_at || "");
  if (Number.isFinite(since)) {
    timer.textContent = `已用时 ${formatDuration(Date.now() - since)}`;
  } else {
    timer.textContent = "";
  }
}

/** 渲染结果与任务操作；表单保留当前输入，便于在同一张图上反复试验。 */
function render() {
  const running = busy();
  const output = currentJob?.stages[stage];
  const hasOutput = !!output?.url;
  const imageSpec = isVideo ? null : imagePreset();
  const videoSpec = isVideo ? videoPresets()[basePreset()] : null;
  const useTail = isVideo && $("#video-frame-mode").value === "first_last";
  const missingTail = videoSpec?.tail_hint && useTail && !selectedTail && !selectedTailSource;
  const promptTrimmed = $("#prompt").value.trim();

  const hasInput = isVideo ? !!(selectedFile || selectedSource) && !missingTail :
    referenceDraft.length >= (imageSpec?.min_photos || 1) &&
    referenceDraft.length <= (imageSpec?.max_photos || config.max_image_references);
  const incompatibleStyle = !isVideo && !!(!imageSpec && styleDraft || imageSpec?.min_photos > 1) &&
    $("#image-model").value === "kling-v3";
  const modelReady = !!$(isVideo ? "#video-model" : "#image-model").value;

  $("#start").disabled = running || savingPrompt || updatingGallery || !config.configured || !hasInput ||
    !promptTrimmed || !modelReady || incompatibleStyle;

  if (isVideo) {
    const dur = $("#video-duration").value;
    $("#start").textContent = requesting ? "正在提交…" : dur ? `生成 ${dur} 秒视频` : "生成视频";
  } else {
    $("#start").textContent = requesting ? "正在提交…" :
      imageSpec?.min_photos > 1 ? "生成关键帧" :
        referenceDraft.length > 1 ? `生成 ${referenceDraft.length} 张待机图` :
          imageSpec ? `生成${imageSpec.label}` : "生成待机图";
  }
  $("#start").classList.toggle("loading", requesting);

  // 提示词不满足或参数冲突时给出温和直白的指引
  const hint = $("#submit-hint");
  let hintText = "";
  if (config.configured && !running) {
    if (incompatibleStyle) hintText = "请先上方切换为支持多图/底图的模型。";
    else if (!isVideo && imageSpec && referenceDraft.length > imageSpec.max_photos) {
      hintText = `当前预设最多 ${imageSpec.max_photos} 张图片，请移除多余图片。`;
    } else if (!isVideo && imageSpec?.min_photos === 2 && referenceDraft.length === 1) {
      hintText = "还需要添加第 2 张狗狗正面照。";
    } else if (isVideo && missingTail) {
      hintText = `该预设需要指定尾帧（${videoSpec.tail_hint}）。`;
    } else if (!promptTrimmed && (isVideo ? (selectedFile || selectedSource) : referenceDraft.length > 0)) {
      hintText = "请先填写提示词。";
    }
  }
  hint.textContent = hintText;
  hint.hidden = !hintText;

  // 顶部状态徽章
  const servicePill = $("#service-pill");
  if (servicePill) {
    if (!("configured" in config)) {
      servicePill.textContent = "连接中…";
      servicePill.className = "service-pill";
    } else if (!config.configured) {
      servicePill.textContent = "未配置密钥";
      servicePill.className = "service-pill warn";
    } else if (config.busy || ["queued", "running"].includes(currentJob?.status)) {
      servicePill.textContent = "任务执行中";
      servicePill.className = "service-pill running";
    } else {
      servicePill.textContent = "已就绪";
      servicePill.className = "service-pill ready";
    }
  }

  const counter = $("#prompt-counter");
  if (counter) {
    const len = $("#prompt").value.length;
    counter.textContent = `${len}/2500`;
    counter.classList.toggle("limit-warn", len >= 2400);
  }
  $("#photo").disabled = running || (!isVideo && !config.max_image_references);
  $("#prompt").disabled = running || savingPrompt;
  renderPromptControls(running);
  renderPresetUI(running || savingPrompt || !(isVideo ? config.video_presets : config.image_presets));
  $("#history").disabled = requesting;
  $("#config-notice").hidden = !!config.configured || !("configured" in config);
  $("#config-notice").textContent = "尚未配置可灵 API 密钥。请在项目 .env 中填写 KLING_API_KEY 并重启服务。";

  const status = currentJob?.status;
  const titles = {
    queued: "等待提交", running: `正在生成${outputLabel}`, complete: `${outputLabel}已生成`,
    failed: `${outputLabel}未生成`, needs_review: "提交待核对",
  };
  $("#status-title").textContent = titles[status] || (config.busy ? "本机正在处理其他任务" :
    isVideo ? "等待生成视频" : "等待生成待机图");
  const providerId = output?.attempt?.provider_id;
  $("#status-detail").textContent = [currentJob?.error, providerId && `任务 ID · ${providerId}`].filter(Boolean).join(" · ");
  $("#status-dot").className = `status-dot ${running ? "running" : status || ""}`;
  updateStatusTimer();
  $("#retry").hidden = status !== "failed";
  $("#review").hidden = status !== "needs_review";
  for (const id of ["retry", "bind-task", "not-created"]) $("#" + id).disabled = running || !config.configured;

  const media = $(".media-box img, .media-box video");
  const mediaBox = $("#media-box");
  if (isVideo && media.getAttribute("src") !== (output?.url || null)) {
    lastVideoTime = loops = 0;
    $("#loop-count").textContent = "";
  }
  const displayUrl = !isVideo && comparingOriginal && currentJob?.input_url ? currentJob.input_url : output?.url;
  setPreview(media, displayUrl);
  if (mediaBox) mediaBox.classList.toggle("is-empty", !hasOutput);
  $(".media-box .empty").hidden = hasOutput;
  $(".badge").textContent = output?.stale ? "保留上一版" : (statusLabels[output?.state] || "待生成");
  $(".badge").className = `badge ${output?.state || ""}`;
  $("#card-actions").hidden = !hasOutput;
  $(".card-actions .download").hidden = !hasOutput;
  if (hasOutput) $(".card-actions .download").href = output.url + "?download=true";
  $(".redo").hidden = !hasOutput;
  $(".redo").disabled = running || !config.configured || status !== "complete";
  $("#job-inputs").hidden = !currentJob;
  $("#job-prompt").textContent = (isVideo ? currentJob?.video_prompt : currentJob?.image_prompt) || "";

  if (isVideo) {
    generationPreset.disabled = running || savingPrompt || !config.video_presets;
    const presetNote = $("#video-preset-note");
    presetNote.hidden = !videoSpec;
    if (videoSpec) {
      const frames = !useTail ? "" : videoSpec.tail_hint ? ` → 尾帧：${videoSpec.tail_hint}` : "";
      presetNote.textContent = `建议首帧：${videoSpec.first_hint}${frames} · 目标 ${videoSpec.options.duration}s / ${videoSpec.options.resolution} / 24fps`;
    }

    // 帧模式顶部切换与选项同步
    const currentModel = config.video_models?.[$("#video-model").value];
    const allowedModes = currentModel?.frame_modes || ["first_last", "first"];
    $("#frame-mode-toggle").querySelectorAll("button").forEach((btn) => {
      const mode = btn.dataset.frameMode;
      btn.setAttribute("aria-pressed", String($("#video-frame-mode").value === mode));
      btn.disabled = running || !$("#video-model").value || !allowedModes.includes(mode);
    });

    $("#video-options").disabled = running || !$("#video-model").value;
    const vModelLabel = currentModel?.label || $("#video-model").value || "";
    $("#video-options-summary").textContent = vModelLabel
      ? `${vModelLabel} · ${$("#video-duration").value} 秒 · ${$("#video-resolution").value === "4k" ? "4K" : $("#video-resolution").value}`
      : "加载中…";

    const optionsNote = $("#video-options-note");
    optionsNote.hidden = !useTail;
    optionsNote.textContent = videoSpec?.tail_hint ? "该预设需指定尾帧。" : "尾帧留空时将自动复用首帧。";

    // 首帧、尾帧与互换按钮
    $("#clear-first").hidden = !(selectedFile || selectedSource);
    $("#clear-first").disabled = running;
    $("#tail-zone").hidden = !useTail;
    $("#tail-zone").classList.toggle("needs-tail", !!missingTail);
    if (!(selectedTail || selectedTailSource)) {
      $("#tail-label").textContent = videoSpec?.tail_hint ? `尾帧（必选 · ${videoSpec.tail_hint}）` : "留空复用首帧";
      $("#tail-help").textContent = videoSpec?.tail_hint ? "请上传或从素材库指定" : "可上传或从素材库指定";
    } else {
      $("#tail-label").textContent = selectedTailSource ? imageLabel(selectedTailSource) : selectedTail.name;
    }
    $("#tail-photo").disabled = running || !useTail;
    $("#clear-tail").hidden = !useTail || !(selectedTail || selectedTailSource);
    $("#clear-tail").disabled = running;
    $("#swap-frames").hidden = !useTail || !(selectedTail || selectedTailSource) || !(selectedFile || selectedSource);
    $("#swap-frames").disabled = running;

    const supportsReferences = !!currentModel?.max_references;
    $("#video-reference-section").hidden = !supportsReferences;
    $("#video-reference-photo").disabled = running || !supportsReferences;
    updateVideoReferences();

    const jobRefsList = $("#job-video-references");
    const jobRefs = currentJob?.video_reference_urls || [];
    jobRefsList.hidden = !jobRefs.length;
    jobRefsList.replaceChildren(...jobRefs.map((url, index) => {
      const offset = currentJob.video_options.frame_mode === "first_last" ? 3 : 2;
      return referenceCard(url, `<<<image_${index + offset}>>>`);
    }));

    // 任务输入复盘：缩略图显示首帧与尾帧
    const framesRecap = $("#job-frames-recap");
    if (currentJob) {
      const recapItems = [referenceCard(currentJob.input_url, "首帧")];
      if (currentJob.video_options?.frame_mode === "first_last") {
        const tailUrl = currentJob.tail_url || currentJob.input_url;
        recapItems.push(referenceCard(tailUrl, currentJob.tail_url ? "尾帧" : "尾帧 (复用首帧)"));
      }
      framesRecap.replaceChildren(...recapItems);
    } else {
      framesRecap.replaceChildren();
    }

    $("#add-image").disabled = updatingGallery;
    $("#refresh-images").disabled = updatingGallery;
    for (const {button, frameTag, setTailBtn, remove, image} of galleryButtons) {
      const k = imageKey(image);
      const isFirst = !!selectedSource && imageKey(selectedSource) === k;
      const isTail = !!selectedTailSource && imageKey(selectedTailSource) === k;
      button.setAttribute("aria-pressed", String(isFirst));
      button.classList.toggle("is-tail", isTail);
      button.disabled = running || updatingGallery;
      if (isFirst && isTail) {
        frameTag.textContent = "首+尾帧";
        frameTag.dataset.role = "both";
        frameTag.hidden = false;
      } else if (isFirst) {
        frameTag.textContent = "首帧";
        frameTag.dataset.role = "first";
        frameTag.hidden = false;
      } else if (isTail) {
        frameTag.textContent = "尾帧";
        frameTag.dataset.role = "tail";
        frameTag.hidden = false;
      } else {
        frameTag.hidden = true;
      }
      setTailBtn.hidden = !useTail;
      setTailBtn.disabled = running || updatingGallery;
      setTailBtn.textContent = isTail ? "取消尾帧" : "设为尾帧";
      setTailBtn.classList.toggle("active", isTail);
      remove.disabled = updatingGallery;
    }

    const options = currentJob?.video_options;
    const descEl = $("#video-description");
    descEl.hidden = !options;
    descEl.textContent = options ? [
      presetLabel(currentJob.preset),
      config.video_models?.[options.model]?.label || options.model,
      `${options.duration} 秒 · ${options.resolution}`,
      options.frame_mode === "first_last" ? "首尾帧" : "仅首帧",
    ].filter(Boolean).join(" · ") : "";
    $("#loop-note").hidden = !hasOutput;
    videoInspection.show(output?.url, videoPresets()[currentJob?.preset]);
  } else {
    const limit = imageSpec?.max_photos || config.max_image_references;
    const singleMode = limit === 1 && referenceDraft.length <= 1;
    generationPreset.disabled = running || savingPrompt || !config.image_presets;
    $("#photo").multiple = limit !== 1;

    const dropzone = $("#dropzone");
    const singleFile = singleMode ? referenceDraft[0] : null;
    dropzone.classList.toggle("has-image", !!singleFile);
    dropzone.classList.toggle("compact", !singleMode && referenceDraft.length > 0);
    setPreview($("#single-preview"), singleFile?.url);
    $("#single-actions").hidden = !singleFile;
    $("#replace-single").disabled = running;
    $("#clear-single").disabled = running;

    if (singleFile) {
      $("#images-label").textContent = singleFile.file.name;
    } else if (imageSpec?.min_photos === 2) {
      $("#images-label").textContent = "按顺序添加猫、狗正面照（可选场景参考图）";
    } else if (!singleMode && referenceDraft.length > 0) {
      $("#images-label").textContent = "继续添加图片（支持拖拽或 Ctrl+V）";
    } else {
      $("#images-label").textContent = "点击、拖拽或 Ctrl+V 粘贴宠物正面照";
    }

    $("#reference-count").textContent = imageSpec?.min_photos === 2 ?
      `已选 ${referenceDraft.length} / 3 张` :
      imageSpec ? `已选 ${referenceDraft.length} / 1 张` : limit ?
        `已选 ${referenceDraft.length} / ${limit} 张` : "";

    $("#style-settings").hidden = !!imageSpec;
    $("#image-credit-note").textContent = imageSpec ? "每次提交按可灵账户额度生成 1 张图片" :
      `每张原图单独提交生成 · 并发最多 ${config.image_batch_concurrency || 3} 张`;
    $("#style-photo").disabled = running || !limit;
    $("#clear-style").hidden = !styleDraft;
    $("#clear-style").disabled = running;

    $("#image-model-warning").hidden = !incompatibleStyle;
    $("#image-model-warning-text").textContent = imageSpec?.min_photos > 1
      ? "追逐关键帧需要多图参考，Kling Image 3.0 不支持"
      : "使用姿态风格底图时，需选择 Image 3.0 Omni 或 O1";

    $("#reference-draft").querySelectorAll("button").forEach((button) => { button.disabled = running; });
    $("#image-options").disabled = running || !$("#image-model").value;
    $("#image-aspect-ratio").disabled = !!imageSpec;

    const iModel = config.image_models?.[$("#image-model").value];
    const iRatio = $("#image-aspect-ratio").value;
    $("#image-options-summary").textContent = iModel
      ? `${iModel.label.replace(/^Kling /, "")} · ${$("#image-resolution").value.toUpperCase()} · ${iRatio === "auto" ? "自动画幅" : iRatio}`
      : "加载中…";

    const options = currentJob?.image_options;
    const description = $("#image-description");
    description.hidden = !options;
    description.textContent = options ?
      [presetLabel(currentJob.preset), config.image_models?.[options.model]?.label || options.model,
        options.resolution.toUpperCase(), options.aspect_ratio === "auto" ? "自动画幅" : options.aspect_ratio]
        .filter(Boolean).join(" · ") : "";

    // 放大提示与对比原图按钮
    const canCompare = hasOutput && currentJob?.input_url && currentJob.input_url !== output.url;
    $("#compare-original").hidden = !canCompare;
    $("#compare-original").setAttribute("aria-pressed", String(comparingOriginal));
    $("#compare-original").textContent = comparingOriginal ? "返回生成图" : "对比原图";
    $("#compare-badge").hidden = !canCompare || !comparingOriginal;
    $("#zoom-hint").hidden = !hasOutput;

    $("#use-idle").hidden = !hasOutput;
    if (hasOutput) {
      const defaults = {"cat-idle": "cat-center", "dog-idle": "dog-center", "chase-entry": "chase-intro",
        "chase-pair": "chase-loop", "chase-cat": "cat-to-dog", "chase-dog": "dog-to-cat"};
      const preset = defaults[currentJob.preset];
      $("#use-idle").href = `/image-to-video?source=${currentJob.id}:${output.version}${preset ? `&preset=${preset}` : ""}`;
    }
  }
}

/** 显示整批图片进度与缩略图，点击任意一项可查看该任务详情。 */
function renderBatch() {
  $("#image-batch").hidden = batchJobs.length <= 1;
  const complete = batchJobs.filter((job) => job.status === "complete").length;
  const failed = batchJobs.filter((job) => job.status === "failed" || job.status === "needs_review").length;
  $("#batch-summary").textContent = `已完成 ${complete} / ${batchJobs.length}` +
    (failed ? ` · ${failed} 待处理` : "");
  $("#batch-results").replaceChildren(...batchJobs.map((job) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "batch-choice";
    button.setAttribute("aria-pressed", String(job.id === currentJob?.id));
    const image = document.createElement("img");
    image.src = job.stages.idle.url || job.input_url;
    image.alt = "";
    image.loading = "lazy";
    const label = document.createElement("span");
    label.textContent = `#${job.batch_index} · ${statusLabels[job.status] || job.status}`;
    button.append(image, label);
    button.addEventListener("click", () => {
      if (requesting) return;
      selectionVersion++;
      showError();
      setJob(job);
    });
    item.append(button);
    return item;
  }));
}

async function loadBatch(job) {
  if (!job.batch_id) return [];
  return (await api(`/api/image-batches/${job.batch_id}`)).jobs;
}

function setJob(job) {
  currentJob = job;
  comparingOriginal = false;
  if (!isVideo) {
    renderBatch();
    $("#job-references").replaceChildren(...job.reference_urls.map((url, index) => {
      const isChase = config.image_presets?.[job.preset]?.min_photos === 2;
      const role = isChase ? ["猫咪正面照", "狗狗正面照", "场景参考图"][index] :
        url === job.style_url ? "姿态底图" : url === job.input_url ? "主体照" : `图 ${index + 1}`;
      return referenceCard(url, `${role} <<<image_${index + 1}>>>`.trim());
    }));
  }
  $("#history").value = job.id;
  localStorage.setItem(historyKey, job.id);
  render();
}

async function loadHistory() {
  const {jobs} = await api(`/api/jobs?kind=${kind}`);
  const select = $("#history");
  select.replaceChildren(new Option(jobs.length ? `历史记录 (${jobs.length})` : "暂无记录", ""));
  for (const job of jobs) {
    const index = job.batch_index ? ` · #${job.batch_index}` : "";
    const title = presetLabel(job.preset);
    select.add(new Option(`${dateLabel(job.created_at)} · ${statusLabels[job.status] || job.status}${index} · ${title || job.id.slice(0, 6)}`, job.id));
  }
  select.value = currentJob?.id || "";
  return jobs;
}

async function operate(path, body) {
  if (busy()) return;
  requesting = true;
  selectionVersion++;
  showError();
  render();
  try {
    const options = body instanceof FormData ? {method: "POST", body} :
      {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
    const result = await api(path, options);
    const job = result.jobs?.[0] || result;
    if (!isVideo) {
      batchJobs = result.jobs || batchJobs.map((item) => item.id === job.id ? job : item);
    }
    config.busy = true;
    setJob(job);
    await loadHistory();
  } catch (error) { showError(error.message); }
  finally { requesting = false; render(); }
}

$("#photo").addEventListener("change", (event) => {
  selectUploads(event.target.files);
  if (!isVideo) event.target.value = "";
});
for (const type of ["dragenter", "dragover", "dragleave", "drop"]) {
  $("#dropzone").addEventListener(type, (event) => {
    event.preventDefault();
    $("#dropzone").classList.toggle("dragging", !busy() && ["dragenter", "dragover"].includes(type));
    if (type === "drop") selectUploads(event.dataTransfer.files);
  });
}

// 支持页面级粘贴图片文件（截图后直接 Ctrl+V）
window.addEventListener("paste", (event) => {
  if (busy()) return;
  const files = Array.from(event.clipboardData?.files || []).filter((file) => file.type.startsWith("image/"));
  if (!files.length) return;
  event.preventDefault();
  selectUploads(files);
  showToast(isVideo ? "已粘贴为首帧" : `已粘贴 ${files.length} 张图片`);
});

$("#prompt").addEventListener("input", () => {
  showPromptStatus();
  render();
});
$("#btn-reset-prompt")?.addEventListener("click", () => {
  const selected = generationPreset.value;
  if (!selected) return;
  const original = presetPrompt(selected);
  if (original === undefined) return;
  $("#prompt").value = original;
  $("#prompt").dispatchEvent(new Event("input"));
  showToast("已恢复预设提示词");
});
$("#btn-copy-prompt")?.addEventListener("click", async () => {
  const text = $("#prompt").value;
  if (!text.trim()) return showToast("当前提示词为空", "warn");
  try {
    await navigator.clipboard.writeText(text);
    showToast("提示词已复制到剪贴板");
  } catch {
    showToast("复制失败，请手动选中文本", "error");
  }
});
$("#btn-clear-prompt")?.addEventListener("click", () => {
  if (!$("#prompt").value) return;
  $("#prompt").value = "";
  $("#prompt").dispatchEvent(new Event("input"));
  showToast("提示词已清空");
});
$("#load-job-prompt")?.addEventListener("click", () => {
  const text = $("#job-prompt").textContent;
  if (!text) return;
  $("#prompt").value = text;
  $("#prompt").dispatchEvent(new Event("input"));
  $("#prompt").focus();
  showToast("已载入本次提示词");
});
$(".media-box img")?.addEventListener("click", (event) => {
  if (event.target.src && !event.target.hidden) {
    openLightbox(event.target.src, event.target.alt || "高清壁纸预览");
  }
});
generationPreset.addEventListener("change", () => {
  $("#prompt-save-form").hidden = true;
  showPromptStatus();
});
$("#prompt-update").addEventListener("click", () => savePrompt(false));
$("#prompt-save-as").addEventListener("click", () => {
  $("#prompt-save-form").reset();
  $("#prompt-save-form").hidden = false;
  showPromptStatus();
  $("#prompt-preset-name").focus();
});
$("#prompt-save-cancel").addEventListener("click", () => {
  $("#prompt-save-form").hidden = true;
  showPromptStatus();
  $("#prompt-save-as").focus();
});
$("#prompt-save-form").addEventListener("submit", (event) => {
  event.preventDefault();
  savePrompt(true);
});

if (isVideo) {
  $("video").addEventListener("timeupdate", ({target: video}) => {
    if (lastVideoTime > video.duration - 0.8 && video.currentTime < 0.8) {
      $("#loop-count").textContent = `· 第 ${++loops} 次`;
    }
    lastVideoTime = video.currentTime;
  });
  $("#refresh-images").addEventListener("click", () => loadGallery());
  $("#add-image").addEventListener("click", () => $("#gallery-photo").click());
  $("#gallery-photo").addEventListener("change", (event) => {
    const [file] = event.target.files;
    event.target.value = "";
    addGalleryImage(file);
  });
  generationPreset.addEventListener("change", (event) => applyVideoPreset(event.target.value));
  $("#video-model").addEventListener("change", () => { updateVideoOptions(readVideoOptions()); render(); });
  $("#video-duration").addEventListener("change", render);
  $("#video-resolution").addEventListener("change", render);
  $("#video-frame-mode").addEventListener("change", render);
  $("#frame-mode-toggle").addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-frame-mode]");
    if (!btn || btn.disabled) return;
    $("#video-frame-mode").value = btn.dataset.frameMode;
    render();
  });
  $("#clear-first").addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!busy()) setFirst(null);
  });
  $("#tail-photo").addEventListener("change", (event) => setTail(event.target.files[0] || null));
  for (const type of ["dragenter", "dragover", "dragleave", "drop"]) {
    $("#tail-zone").addEventListener(type, (event) => {
      event.preventDefault();
      $("#tail-zone").classList.toggle("dragging", !busy() && ["dragenter", "dragover"].includes(type));
      if (type === "drop" && !busy() && event.dataTransfer.files.length) {
        setTail(event.dataTransfer.files[0]);
      }
    });
  }
  $("#clear-tail").addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!busy()) setTail(null);
  });
  $("#swap-frames").addEventListener("click", swapFirstAndTail);
  $("#video-reference-photo").addEventListener("change", (event) => {
    const files = Array.from(event.target.files);
    event.target.value = "";
    const limit = config.video_models[$("#video-model").value]?.max_references || 0;
    if (videoReferenceDraft.length + files.length > limit) return showError(`最多添加 ${limit} 张额外参考图。`);
    if (files.some((file) => !checkFile(file))) return showError("参考图需为符合大小要求的 JPG 或 PNG。");
    for (const file of files) videoReferenceDraft.push({file, url: URL.createObjectURL(file)});
    showError();
    updateVideoReferences();
  });
} else {
  generationPreset.addEventListener("change", () => {
    const spec = imagePreset();
    const previous = readImageOptions();
    if (spec?.min_photos === 2 && previous.model === "kling-v3") {
      $("#image-model").value = config.default_image_options.model;
    }
    if (spec) previous.aspect_ratio = "16:9";
    updateImageOptions(previous);
    $("#prompt").value = presetPrompt(generationPreset.value) ??
      (styleDraft ? config.default_image_style_prompt : config.default_image_prompt);
    showError();
    updateReferenceDraft();
  });
  $("#replace-single").addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (!busy()) $("#photo").click();
  });
  $("#clear-single").addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (busy()) return;
    for (const {url} of referenceDraft.splice(0)) URL.revokeObjectURL(url);
    updateReferenceDraft();
  });
  $("#style-photo").addEventListener("change", (event) => {
    if (event.target.files.length) setStyle(event.target.files[0]);
    event.target.value = "";
  });
  $("#clear-style").addEventListener("click", () => setStyle(null));
  for (const type of ["dragenter", "dragover", "dragleave", "drop"]) {
    $("#style-dropzone").addEventListener(type, (event) => {
      event.preventDefault();
      $("#style-dropzone").classList.toggle("dragging", !busy() && ["dragenter", "dragover"].includes(type));
      if (type === "drop" && !busy()) {
        const {files} = event.dataTransfer;
        if (files.length > 1) showError("一批只能选择一张姿态风格图。");
        else if (files.length) setStyle(files[0]);
      }
    });
  }
  $("#image-model").addEventListener("change", () => {
    updateImageOptions(readImageOptions());
    render();
  });
  $("#image-resolution").addEventListener("change", render);
  $("#image-aspect-ratio").addEventListener("change", render);
  $("#fix-image-model").addEventListener("click", () => {
    $("#image-model").value = config.default_image_options?.model || "kling-v3-omni";
    updateImageOptions(readImageOptions());
    render();
    showToast("已切换为 Kling Image 3.0 Omni");
  });
  $("#compare-original").addEventListener("click", () => {
    comparingOriginal = !comparingOriginal;
    render();
  });
}

$("#start").addEventListener("click", () => {
  if ($("#start").disabled) return;
  const form = new FormData();
  const preset = basePreset();
  if (preset) form.append("preset", preset);
  form.append("prompt", $("#prompt").value.trim());
  if (selectedFile) form.append("file", selectedFile);
  if (selectedSource) appendFrameSource(form, "source", selectedSource);
  if (isVideo) {
    const options = readVideoOptions();
    form.append("video_options", JSON.stringify(options));
    if (options.frame_mode === "first_last" && selectedTail) form.append("tail", selectedTail);
    if (options.frame_mode === "first_last" && selectedTailSource) {
      appendFrameSource(form, "tail_source", selectedTailSource);
    }
    if (config.video_models[options.model]?.max_references) {
      for (const {file} of videoReferenceDraft) form.append("reference", file);
    }
  } else {
    for (const {file} of referenceDraft) form.append("file", file);
    if (!preset && styleDraft) form.append("style", styleDraft.file);
    form.append("image_options", JSON.stringify(readImageOptions()));
  }
  const path = isVideo ? "/api/video-jobs" : preset ? "/api/image-jobs" : "/api/image-batches";
  operate(path, form);
});

function retry() { operate(`/api/jobs/${currentJob.id}/retry`, {stage}); }
$("#retry").addEventListener("click", retry);
$(".redo").addEventListener("click", retry);
$("#bind-task").addEventListener("click", () => {
  const id = $("#provider-id").value.trim();
  if (!/^[a-zA-Z0-9_-]{1,128}$/.test(id)) return showError("请填写控制台中的任务 ID。");
  operate(`/api/jobs/${currentJob.id}/reconcile`, {stage, provider_id: id});
});
$("#not-created").addEventListener("click", () => {
  if (confirm("请确认已在可灵控制台核对任务。继续将发起一次新的付费生成。")) {
    operate(`/api/jobs/${currentJob.id}/reconcile`, {stage, confirmed_not_created: true});
  }
});
$("#history").addEventListener("change", async (event) => {
  if (!event.target.value) return;
  const version = ++selectionVersion;
  showError();
  try {
    const job = await api(`/api/jobs/${event.target.value}`);
    const jobs = await loadBatch(job);
    if (version === selectionVersion) {
      batchJobs = jobs;
      setJob(jobs.find((item) => item.id === job.id) || job);
    }
  } catch (error) { showError(error.message); }
});

/** 轮询本机任务状态；只读取已创建任务，不发起生成。 */
async function poll() {
  if (polling || requesting) return;
  polling = true;
  const version = selectionVersion;
  try {
    const nextConfig = await api("/api/config");
    if (version !== selectionVersion || requesting) return;
    config = nextConfig;
    if (currentJob?.batch_id && (config.busy || batchJobs.some((job) => ["queued", "running"].includes(job.status)))) {
      const jobs = await loadBatch(currentJob);
      if (version !== selectionVersion || requesting) return;
      const changed = jobs.some((job, index) => job.updated_at !== batchJobs[index]?.updated_at);
      if (changed) {
        batchJobs = jobs;
        currentJob = jobs.find((job) => job.id === currentJob.id);
        renderBatch();
        await loadHistory();
      }
    } else if (currentJob && ["queued", "running"].includes(currentJob.status)) {
      const job = await api(`/api/jobs/${currentJob.id}`);
      if (version !== selectionVersion || requesting) return;
      const changed = job.status !== currentJob.status;
      currentJob = job;
      if (changed) await loadHistory();
    }
    render();
  } catch (error) { showError(`无法连接本机服务：${error.message}`); }
  finally { polling = false; }
}

async function init() {
  try {
    config = await api("/api/config");
    try {
      const {presets} = await api(promptPresetsURL);
      savedPrompts = Object.assign(Object.create(null), presets);
      promptsLoaded = true;
    } catch (error) {
      showPromptStatus(`无法读取提示词预设：${error.message}`, true);
    }
    if (isVideo) {
      for (const [group, presets] of Object.entries(config.video_presets)) {
        const options = document.createElement("optgroup");
        options.label = group;
        for (const [id, preset] of Object.entries(presets)) options.append(new Option(preset.label, id));
        generationPreset.append(options);
      }
      for (const [value, model] of Object.entries(config.video_models)) {
        $("#video-model").add(new Option(model.label, value));
      }
      $("#video-model").value = config.default_video_options.model;
      updateVideoOptions(config.default_video_options);
    } else {
      for (const [id, preset] of Object.entries(config.image_presets)) {
        generationPreset.add(new Option(preset.label, id));
      }
      const defaults = config.default_image_options;
      for (const [value, model] of Object.entries(config.image_models)) {
        $("#image-model").add(new Option(model.label, value));
      }
      $("#image-model").value = defaults.model;
      updateImageOptions(defaults);
      if (!$("#prompt").value) $("#prompt").value = config.default_image_prompt;
    }
    renderSavedPrompts();
    const params = new URLSearchParams(location.search);
    const gallery = isVideo ? loadGallery(params.get("source")) : null;
    const presetID = params.get("preset");
    if (isVideo && videoPresets()[presetID]) {
      generationPreset.value = presetID;
      applyVideoPreset(presetID);
    }
    const jobs = await loadHistory();
    const saved = localStorage.getItem(historyKey);
    const job = jobs.find((item) => item.id === config.active_job_id) || jobs.find((item) => item.id === saved) || jobs[0];
    if (job) {
      batchJobs = await loadBatch(job);
      setJob(batchJobs.find((item) => item.id === job.id) || job);
    }
    await gallery;
    render();
  } catch (error) { showError(error.message); }
  setInterval(poll, 3000);
  setInterval(updateStatusTimer, 1000);
}
init();
