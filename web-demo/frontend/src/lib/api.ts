// 文件用途：封装网页 Demo 的同源接口，包含宠物档案、生成任务和设置管理。
import type {
  AppConfig,
  CurrentWallpaper,
  DecorationChoice,
  Gender,
  GenerationJob,
  GenerationSettings,
  PetProfile,
  Species,
} from "@/types";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function getSessionHeader(): Record<string, string> {
  if (typeof window === "undefined") return {};
  const params = new URLSearchParams(window.location.search);
  const override = params.get("session")?.trim();
  return override ? { "X-Demo-Session": override } : {};
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers || {});
  const sessionHeaders = getSessionHeader();
  for (const [k, v] of Object.entries(sessionHeaders)) {
    headers.set(k, v);
  }
  const res = await fetch(url, {
    credentials: "same-origin",
    ...init,
    headers,
  });
  let payload: Record<string, unknown> | null = null;
  try {
    payload = (await res.json()) as Record<string, unknown>;
  } catch {
    payload = null;
  }
  if (!res.ok) {
    const detail =
      payload && typeof payload.detail === "string"
        ? payload.detail
        : `请求失败 (${res.status})`;
    throw new ApiError(res.status, detail);
  }
  return payload as T;
}

export function createIdempotencyKey(prefix = "gen"): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return `${prefix}-${crypto.randomUUID()}`;
  }
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 10)}`;
}

/** 读取 Demo 配置，并按素材内容版本更新过场地址，供预加载和播放器共用。 */
export async function fetchConfig(): Promise<AppConfig> {
  const config = await requestJson<AppConfig>("/api/config");
  for (const video of [config.transitions?.intro, config.transitions?.loop]) {
    if (!video?.sha256) continue;
    const separator = video.url.includes("?") ? "&" : "?";
    video.url += `${separator}v=${encodeURIComponent(video.sha256)}`;
  }
  return config;
}

/** 用设置密码换取短期令牌，并返回当前生成设置。 */
export function unlockGenerationSettings(password: string): Promise<{ token: string; settings: GenerationSettings }> {
  return requestJson("/api/settings/unlock", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
}

/** 使用页面持有的 token 保存 settings，返回生效设置和模拟控件状态。 */
export function saveGenerationSettings(
  token: string,
  settings: GenerationSettings,
): Promise<{ settings: GenerationSettings; mock_controls_enabled: boolean }> {
  return requestJson("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
    body: JSON.stringify(settings),
  });
}

export async function fetchPets(): Promise<PetProfile[]> {
  const data = await requestJson<{ pets: PetProfile[] }>("/api/pets");
  return data.pets;
}

export async function createPet(input: {
  species: Species;
  name?: string;
  gender?: Gender;
  breed?: string;
}): Promise<PetProfile> {
  const data = await requestJson<{ pet: PetProfile }>("/api/pets", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return data.pet;
}

export async function updatePet(
  petId: string,
  input: { name?: string; gender?: Gender; breed?: string },
): Promise<PetProfile> {
  const data = await requestJson<{ pet: PetProfile }>(`/api/pets/${encodeURIComponent(petId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return data.pet;
}

export function deletePet(petId: string): Promise<{ deleted_pet_id: string; was_current: boolean }> {
  return requestJson<{ deleted_pet_id: string; was_current: boolean }>(
    `/api/pets/${encodeURIComponent(petId)}`,
    { method: "DELETE" },
  );
}

export async function submitGeneration(input: {
  petId: string;
  idempotencyKey: string;
  photo?: File | Blob | null;
  mockDelaySeconds?: number;
  mockFail?: boolean;
  mockFailStage?: string;
  mockFailMessage?: string;
  requireDecoration?: boolean;
  retryFromJobId?: string;
}): Promise<{ reused: boolean; job: GenerationJob; pet?: PetProfile }> {
  const form = new FormData();
  form.append("pet_id", input.petId);
  form.append("idempotency_key", input.idempotencyKey);
  if (input.requireDecoration) form.append("require_decoration", "true");
  if (input.retryFromJobId) form.append("retry_from_job_id", input.retryFromJobId);
  if (input.photo) {
    const filename = input.photo instanceof File ? input.photo.name : "pet-photo.jpg";
    form.append("photo", input.photo, filename);
  }
  if (input.mockDelaySeconds !== undefined) {
    form.append("mock_delay_seconds", String(input.mockDelaySeconds));
  }
  if (input.mockFail) {
    form.append("mock_fail", "true");
    if (input.mockFailStage) form.append("mock_fail_stage", input.mockFailStage);
    if (input.mockFailMessage) form.append("mock_fail_message", input.mockFailMessage);
  }
  return requestJson<{ reused: boolean; job: GenerationJob; pet?: PetProfile }>("/api/generations", {
    method: "POST",
    body: form,
  });
}

/** 一次提交 choices 中各宠物的选择，返回进入动画生成的任务。 */
export async function confirmDecorations(
  choices: (DecorationChoice & { job_id: string })[],
): Promise<GenerationJob[]> {
  const { jobs } = await requestJson<{ jobs: GenerationJob[] }>("/api/generations/confirm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ choices }),
  });
  return jobs;
}

/** 取消给定的未确认任务，返回其最新状态。 */
export async function cancelDecorations(jobIds: string[]): Promise<GenerationJob[]> {
  const { jobs } = await requestJson<{ jobs: GenerationJob[] }>("/api/generations/cancel-decoration", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ job_ids: jobIds }),
  });
  return jobs;
}

export async function fetchGenerations(): Promise<GenerationJob[]> {
  const data = await requestJson<{ jobs: GenerationJob[] }>("/api/generations");
  return data.jobs;
}

export async function fetchGeneration(jobId: string): Promise<GenerationJob> {
  const data = await requestJson<{ job: GenerationJob }>(`/api/generations/${encodeURIComponent(jobId)}`);
  return data.job;
}

export async function fetchCurrentWallpaper(): Promise<CurrentWallpaper | null> {
  const data = await requestJson<{ current: CurrentWallpaper | null }>("/api/current-wallpaper");
  return data.current;
}

export async function saveCurrentWallpaper(petId: string, versionId: string): Promise<CurrentWallpaper> {
  const data = await requestJson<{ current: CurrentWallpaper }>("/api/current-wallpaper", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pet_id: petId, version_id: versionId }),
  });
  return data.current;
}
