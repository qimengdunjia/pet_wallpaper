<!-- 文件用途：提供再次进入已保存壁纸的入口，使用 MasterGo 首页的环境素材。 -->
<script setup lang="ts">
import { computed } from "vue";
import wallpaperDog from "@/assets/mastergo/wallpaper-dog.png";
import { getDefaultPet, getFirstReadyPet, petState } from "@/stores/petStore";
import { activatePetWallpaper } from "@/stores/playerStore";
import { guardParkedAction, setRoute, showToast, systemState } from "@/stores/systemStore";

const featuredPet = computed(() => {
  if (petState.savedWallpaper) {
    return {
      pet: {
        ...petState.savedWallpaper.pet,
        active_version_id: petState.savedWallpaper.version_id,
        active_assets: petState.savedWallpaper.assets,
      },
      isLastSaved: true,
    };
  }
  const firstReady = getFirstReadyPet();
  if (firstReady) {
    return { pet: firstReady, isLastSaved: false };
  }
  const defaultPet = getDefaultPet();
  if (defaultPet) {
    return { pet: defaultPet, isLastSaved: false };
  }
  return null;
});

async function handleEnterWallpaper() {
  if (!featuredPet.value) {
    if (!guardParkedAction("创建宠物档案")) return;
    systemState.onboardingReturnRoute = "home";
    setRoute("onboarding-species");
    return;
  }
  const res = await activatePetWallpaper(featuredPet.value.pet, { persist: true, force: true });
  if (res.ok) {
    setRoute("wallpaper");
  } else {
    showToast(res.reason || "加载壁纸失败，请重试", "error");
  }
}

function handleAddPet() {
  if (!guardParkedAction("新增宠物")) return;
  systemState.onboardingReturnRoute = "home";
  systemState.onboardingSpeciesMode = null;
  setRoute("onboarding-species");
}
</script>

<template>
  <section class="home-screen mastergo-cloud-sky" data-testid="home-return-view">
    <!-- 底部草绿渐变氛围 -->
    <div class="home-meadow-strip" aria-hidden="true" />

    <div class="home-layout">
      <div class="home-left">
        <template v-if="featuredPet">
          <h1 class="home-pet-hero sky-gradient-title">
            {{ featuredPet.pet.name }}
          </h1>
          <div class="home-meta-row">
            <span>{{ featuredPet.pet.breed || (featuredPet.pet.species === "cat" ? "猫咪模式" : "狗狗模式") }}</span>
            <span class="gender-tag">
              {{ featuredPet.pet.gender === "弟弟" ? "♂ 弟弟" : featuredPet.pet.gender === "妹妹" ? "♀ 妹妹" : "未设置性别" }}
            </span>
          </div>
        </template>
        <template v-else>
          <h1 class="home-pet-hero sky-gradient-title">欢迎回来</h1>
          <p class="home-desc">尚未保存可用的宠物壁纸，您可以上传照片立即生成专属动态壁纸。</p>
        </template>

        <div class="home-cta-row">
          <button
            class="btn btn-black home-enter-btn"
            data-testid="home-enter-wallpaper-btn"
            @click="handleEnterWallpaper"
          >
            {{ featuredPet ? "进入壁纸" : "创建我的宠物档案" }}
          </button>
          <button
            class="btn btn-ghost"
            data-testid="home-add-pet-btn"
            @click="handleAddPet"
          >
            + 新增宠物
          </button>
        </div>
      </div>

      <div v-if="featuredPet" class="home-right-card" data-testid="saved-wallpaper-card">
        <div class="saved-header">
          <strong>已保存的宠物壁纸</strong>
          <span class="pill-tag info">
            {{ featuredPet.pet.is_default ? `默认壁纸：${featuredPet.pet.name}` : `上次使用：${featuredPet.pet.name}` }}
          </span>
        </div>
        <div class="saved-frame">
          <img
            :src="featuredPet.pet.active_assets?.idle_image.url || featuredPet.pet.original_photo_url || ''"
            :alt="featuredPet.pet.name"
          />
        </div>
      </div>
      <img v-else :src="wallpaperDog" alt="" class="home-dog-art" />
    </div>
  </section>
</template>

<style scoped>
.home-screen {
  position: relative;
  flex: 1;
  width: 100%;
  height: 100%;
  padding: 58px 64px 62px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-sky);
  overflow: hidden;
}

.home-meadow-strip {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 25%;
  background: var(--bg-meadow-floor);
  pointer-events: none;
  z-index: 1;
}

.home-screen::before {
  left: -10.74%;
  top: 54.17%;
}

.home-screen::after {
  left: 67.58%;
  top: 0;
}

.home-layout {
  position: relative;
  z-index: 3;
  width: min(1080px, 94vw);
  display: grid;
  grid-template-columns: 1fr 1.15fr;
  gap: 44px;
  align-items: center;
}

.home-left {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 12px;
}

.home-pet-hero {
  margin: 4px 0 0;
  font-size: 64px;
  font-weight: 800;
  line-height: 1.05;
  letter-spacing: -0.02em;
}

.home-meta-row {
  display: flex;
  align-items: center;
  gap: 18px;
  font-size: 16px;
  font-weight: 600;
  color: #121628;
}

.gender-tag {
  color: #2563eb;
}

.home-desc {
  margin: 0;
  font-size: 14px;
  line-height: 1.65;
  color: #536478;
}

.home-cta-row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-top: 10px;
}

.home-enter-btn {
  height: 48px;
  padding: 0 30px;
  font-size: 15px;
}

.home-right-card {
  padding: 18px 20px 20px;
  border-radius: 30px;
  background: rgba(255, 255, 255, 0.88);
  border: 2px solid #ffffff;
  box-shadow: 0 22px 48px rgba(42, 85, 148, 0.16);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.home-dog-art {
  justify-self: center;
  width: min(34vw, 48vh);
  pointer-events: none;
}

.saved-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 14px;
  color: #121628;
}

.saved-frame {
  width: 100%;
  aspect-ratio: 16 / 9;
  border-radius: 20px;
  overflow: hidden;
  background: var(--surface-frame-blue);
}

.saved-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
