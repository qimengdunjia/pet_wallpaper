<script setup lang="ts">
import { computed } from "vue";
import { hotzoneLabel } from "@/lib/hotzone";
import { playerState } from "@/stores/playerStore";
import { type CutoutStrategy, type MockPreset, systemState } from "@/stores/systemStore";

const mockEnabled = computed(() => Boolean(systemState.config?.mock_controls_enabled));

const presets: Array<{ value: MockPreset; title: string; desc: string }> = [
  { value: "fast", title: "标准快速 (2 秒)", desc: "模拟生成在 2 秒内完成" },
  { value: "over10s", title: "超过 10 秒循环 (12 秒)", desc: "验收 3 秒先导 + 仅循环 7 秒追逐段" },
  { value: "staggered", title: "双宠错峰 (猫 2 秒 / 狗 14 秒)", desc: "首套先进入壁纸，另一只列表显示生成中" },
  { value: "fail", title: "模拟生成失败", desc: "验收首次失败引导与已有壁纸回退" },
];

const cutoutOptions: Array<{ value: CutoutStrategy; label: string }> = [
  { value: "after_first_round", label: "首轮 10 秒完整后切出 (默认)" },
  { value: "immediate", label: "就绪即切出" },
];
</script>

<template>
  <aside
    v-if="systemState.drawerOpen"
    class="demo-drawer glass-panel"
    data-testid="demo-control-drawer"
    @click.stop
  >
    <div class="drawer-header">
      <div>
        <h3>演示验收与素材规格</h3>
        <span class="sub">当前供应商：{{ systemState.config?.provider || "mock" }}</span>
      </div>
      <button class="btn btn-soft btn-sm" @click="systemState.drawerOpen = false">关闭</button>
    </div>

    <section v-if="mockEnabled" class="drawer-section">
      <h4>模拟生成预设</h4>
      <div class="preset-list">
        <button
          v-for="item in presets"
          :key="item.value"
          class="preset-btn"
          :class="{ active: systemState.mockPreset === item.value }"
          :data-testid="`mock-preset-${item.value}`"
          @click="systemState.mockPreset = item.value"
        >
          <strong>{{ item.title }}</strong>
          <span>{{ item.desc }}</span>
        </button>
      </div>
    </section>

    <section class="drawer-section">
      <h4>过场切出策略</h4>
      <div class="strategy-group">
        <button
          v-for="opt in cutoutOptions"
          :key="opt.value"
          class="btn btn-sm"
          :class="systemState.cutoutStrategy === opt.value ? 'btn-black' : 'btn-soft'"
          :data-testid="`cutout-strategy-${opt.value}`"
          @click="systemState.cutoutStrategy = opt.value"
        >
          {{ opt.label }}
        </button>
      </div>
    </section>

    <section class="drawer-section">
      <h4>交互与回退辅助开关</h4>
      <label class="switch-row">
        <input
          v-model="systemState.showHotzoneGuides"
          type="checkbox"
          data-testid="toggle-hotzone-guides"
        />
        <span>显示 16:9 左/中/右热区边界线 (34% / 66%)</span>
      </label>
      <label class="switch-row">
        <input
          v-model="systemState.simulateNextSwitchFailure"
          type="checkbox"
          data-testid="toggle-switch-failure"
        />
        <span>下次切换宠物模拟资源加载失败</span>
      </label>
    </section>

    <section v-if="playerState.currentAssets" class="drawer-section">
      <h4>当前壁纸素材规格</h4>
      <div class="spec-grid">
        <div class="spec-item">
          <span>待机首帧</span>
          <strong>
            {{ playerState.currentAssets.idle_image.width }}×{{ playerState.currentAssets.idle_image.height }}
            · {{ playerState.currentAssets.idle_image.format.toUpperCase() }}
          </strong>
        </div>
        <div v-if="playerState.currentAssets.idle_video" class="spec-item">
          <span>待机动效</span>
          <strong>
            {{ playerState.currentAssets.idle_video.width }}×{{ playerState.currentAssets.idle_video.height }}
            · {{ playerState.currentAssets.idle_video.fps }} fps ·
            {{ playerState.currentAssets.idle_video.duration }}s
          </strong>
        </div>
        <div
          v-for="slot in (['left', 'center', 'right'] as const)"
          :key="slot"
          class="spec-item"
        >
          <span>{{ hotzoneLabel(slot) }}</span>
          <strong>
            {{ playerState.currentAssets.actions[slot].width }}×{{ playerState.currentAssets.actions[slot].height }}
            · {{ playerState.currentAssets.actions[slot].fps }} fps ·
            {{ playerState.currentAssets.actions[slot].duration }}s
          </strong>
        </div>
        <div v-if="playerState.lastTriggered" class="spec-item highlight">
          <span>最近命中热区</span>
          <strong data-testid="last-hotzone-spec">
            x={{ (playerState.lastTriggered.ratioX * 100).toFixed(1) }}% →
            {{ hotzoneLabel(playerState.lastTriggered.slot) }}
          </strong>
        </div>
      </div>
    </section>
  </aside>
</template>

<style scoped>
.demo-drawer {
  position: fixed;
  top: 52px;
  right: 18px;
  width: min(390px, 92vw);
  max-height: calc(100vh - 104px);
  z-index: 80;
  border-radius: 24px;
  padding: 18px 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: rgba(248, 251, 255, 0.94);
  color: #121628;
}

.drawer-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.drawer-header h3 {
  margin: 0;
  font-size: 16px;
}

.sub {
  font-size: 12px;
  color: var(--text-secondary);
}

.drawer-section h4 {
  margin: 0 0 8px;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}

.preset-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.preset-btn {
  text-align: left;
  padding: 9px 12px;
  border-radius: 14px;
  border: 1.5px solid rgba(18, 22, 40, 0.08);
  background: #eff3fa;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.preset-btn strong {
  font-size: 13px;
  color: #121628;
}

.preset-btn span {
  font-size: 12px;
  color: var(--text-secondary);
}

.preset-btn.active {
  background: #e2eeff;
  border-color: #4981f2;
}

.strategy-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.switch-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: var(--text-primary);
  margin-bottom: 6px;
  cursor: pointer;
}

.spec-grid {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.spec-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 10px;
  background: #eff3fa;
}

.spec-item span {
  color: var(--text-secondary);
}

.spec-item.highlight {
  background: #ebff9a;
}
</style>
