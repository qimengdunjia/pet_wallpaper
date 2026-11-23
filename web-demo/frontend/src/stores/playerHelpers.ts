import { findPetById } from "@/stores/petStore";
import { closePetSelector, playerState } from "@/stores/playerStore";

export { closePetSelector, playerState };

export function findPetByIdSafe(petId: string | null | undefined) {
  return findPetById(petId);
}
