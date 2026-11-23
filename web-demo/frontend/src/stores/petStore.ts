// 文件用途：保存宠物档案、生成状态及上次成功显示的壁纸。
import { reactive } from "vue";
import type { CurrentWallpaper, GenerationJob, PetProfile, Species } from "@/types";

export const petState = reactive({
  pets: [] as PetProfile[],
  savedWallpaper: null as CurrentWallpaper | null,
  defaultWallpaper: null as CurrentWallpaper | null,
  loading: false,
});

export function setPets(pets: PetProfile[]) {
  petState.pets = pets;
}

export function upsertPet(pet: PetProfile) {
  const index = petState.pets.findIndex((item) => item.id === pet.id);
  if (index >= 0) {
    petState.pets[index] = pet;
  } else {
    petState.pets.push(pet);
  }
}

export function setSavedWallpaper(wallpaper: CurrentWallpaper | null) {
  petState.savedWallpaper = wallpaper;
}

export function setDefaultWallpaper(wallpaper: CurrentWallpaper | null) {
  petState.defaultWallpaper = wallpaper;
}

export function getDefaultPet(): PetProfile | undefined {
  const dw = petState.defaultWallpaper;
  if (!dw) return undefined;
  return {
    ...dw.pet,
    is_default: true,
    active_version_id: dw.version_id,
    active_assets: dw.assets,
  };
}

export function getAllPets(): PetProfile[] {
  const defaultPet = getDefaultPet();
  return defaultPet ? [defaultPet, ...petState.pets] : [...petState.pets];
}

export function findPetById(petId: string | null | undefined): PetProfile | undefined {
  if (!petId) return undefined;
  const userPet = petState.pets.find((p) => p.id === petId);
  if (userPet) return userPet;
  const defaultPet = getDefaultPet();
  if (defaultPet && defaultPet.id === petId) return defaultPet;
  return undefined;
}

/** 将轮询返回的 job 合并到所属档案，返回更新后的宠物（若档案存在）。 */
export function applyJobToPet(job: GenerationJob): PetProfile | undefined {
  const pet = findPetById(job.pet_id);
  if (!pet) return undefined;
  const updated = { ...pet };
  const latest = pet.latest_job;
  const updatesLatest = !pet.latest_job_id || (pet.latest_job_id === job.id
    ? !latest || job.updated_at >= latest.updated_at
    : latest && job.created_at > latest.created_at);
  if (updatesLatest) {
    updated.latest_job_id = job.id;
    updated.latest_job = job;
  }
  if (job.status === "ready" && job.version_id && job.assets &&
      job.assets.version_number > (pet.active_assets?.version_number ?? 0)) {
    updated.active_version_id = job.version_id;
    updated.active_assets = job.assets;
  }
  upsertPet(updated);
  return updated;
}

export function getPetsBySpecies(species: Species): PetProfile[] {
  return getAllPets().filter((pet) => pet.species === species);
}

export function getFirstReadyPet(): PetProfile | undefined {
  return petState.pets.find((pet) => Boolean(pet.active_assets && pet.active_version_id));
}

export function resetPetState() {
  petState.pets = [];
  petState.savedWallpaper = null;
  petState.defaultWallpaper = null;
  petState.loading = false;
}
