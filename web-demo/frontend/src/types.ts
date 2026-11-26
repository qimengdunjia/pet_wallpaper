// 文件用途：定义网页 Demo 页面状态及后端返回的档案、任务和素材结构。
export type Species = "cat" | "dog";
export type Gender = "弟弟" | "妹妹" | "未设置";
export type HotzoneSlot = "left" | "center" | "right";
export type DrivingMode = "parked" | "driving";
export type ProviderMode = "mock" | "kling" | "comfyui";
export type ActionSlot = "idle" | HotzoneSlot;
export type RouteView =
  | "welcome"
  | "home"
  | "onboarding-species"
  | "onboarding-upload"
  | "onboarding-decoration"
  | "generating"
  | "wallpaper"
  | "settings";

export type DecorationBackground = "cream" | "pink" | "blue" | "lavender";
export type DecorationAccessory = "none" | "bow-tie" | "bandana" | "glasses" | "santa-hat";

export interface DecorationChoice {
  background: DecorationBackground;
  accessory: DecorationAccessory;
}

export interface GenerationSettings {
  provider: ProviderMode;
  image_width: number;
  image_height: number;
  video_width: number;
  video_height: number;
  // 每种宠物有四段动作视频，待机图另有一条提示词。
  prompts: Record<Species, Record<ActionSlot | "image", string>>;
}

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

type TransitionVideoMeta = VideoAssetMeta & {
  sha256?: string; // 过场素材的内容版本，旧清单可以省略。
  mse_codec?: string; // 分片 MP4 的编码标识，用于连续播放。
};

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
  status: "queued" | "generating" | "awaiting_decoration" | "ready" | "failed" | "cancelled";
  stage: string;
  progress: number;
  version_id: string | null;
  error_message: string | null;
  assets: AssetVersionManifest | null;
  staged?: boolean; // 是否需要先经过正面照与装扮确认。
  decoration?: DecorationChoice | null;
  preview_url?: string | null;
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
  seat_key_url?: string; // 由服务端与站点连接策略一起下发的按键地址。
  provider: ProviderMode;
  mock_controls_enabled: boolean;
  default_mock_delay_seconds: number;
  max_upload_mb: number;
  decoration_backgrounds?: Record<DecorationBackground, string>;
  transitions: {
    intro: TransitionVideoMeta | null;
    loop: TransitionVideoMeta | null;
  };
  sample_uploads: {
    cat: string;
    dog: string;
  };
  default_wallpaper?: CurrentWallpaper | null;
}
