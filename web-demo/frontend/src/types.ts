// 文件用途：定义网页 Demo 页面状态及后端返回的档案、任务和素材结构。
export type Species = "cat" | "dog";
export type Gender = "弟弟" | "妹妹" | "未设置";
export type HotzoneSlot = "left" | "center" | "right";
export type DrivingMode = "parked" | "driving";
export type RouteView =
  | "welcome"
  | "home"
  | "onboarding-species"
  | "onboarding-upload"
  | "generating"
  | "wallpaper";

export interface ImageAssetMeta {
  url: string;
  format: string;
  mime: string;
  width: number;
  height: number;
  size_bytes: number;
}

export interface VideoAssetMeta {
  url: string;
  format: string;
  mime: string;
  width: number;
  height: number;
  fps: number;
  duration: number;
  aspect_ratio: string;
  size_bytes: number;
}

export interface AssetVersionManifest {
  version_id: string;
  version_number: number;
  created_at: string;
  idle_image: ImageAssetMeta;
  idle_video?: VideoAssetMeta | null;
  actions: Record<HotzoneSlot, VideoAssetMeta>;
}

export interface GenerationJob {
  id: string;
  pet_id: string;
  idempotency_key: string;
  provider: string;
  status: "queued" | "generating" | "ready" | "failed";
  stage: string;
  progress: number;
  version_id: string | null;
  error_message: string | null;
  assets: AssetVersionManifest | null;
  created_at: string;
  updated_at: string;
}

export interface PetProfile {
  id: string;
  species: Species;
  name: string;
  gender: Gender;
  breed: string;
  is_default?: boolean;
  original_photo_url: string | null;
  active_version_id: string | null;
  latest_job_id: string | null;
  active_assets: AssetVersionManifest | null;
  latest_job: GenerationJob | null;
  created_at: string;
  updated_at: string;
}

export interface CurrentWallpaper {
  pet_id: string;
  version_id: string;
  updated_at: string;
  pet: PetProfile;
  assets: AssetVersionManifest;
}

export interface AppConfig {
  provider: "mock" | "kling";
  mock_controls_enabled: boolean;
  default_mock_delay_seconds: number;
  max_upload_mb: number;
  transitions: {
    intro: VideoAssetMeta | null;
    loop: VideoAssetMeta | null;
  };
  sample_uploads: {
    cat: string;
    dog: string;
  };
  default_wallpaper?: CurrentWallpaper | null;
}
