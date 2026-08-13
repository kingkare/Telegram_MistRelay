<template>
  <section class="pc-state-panel">
    <div
      class="pc-state-panel-asset pc-illustration"
      :class="`pc-illustration-${asset}`"
      aria-hidden="true"
    ></div>
    <div class="pc-state-panel-copy">
      <h2>{{ title }}</h2>
      <p v-if="description">{{ description }}</p>
    </div>
    <el-button
      v-if="actionLabel"
      :icon="actionIcon"
      @click="emit('action')"
    >
      {{ actionLabel }}
    </el-button>
  </section>
</template>

<script setup lang="ts">
import type { Component } from 'vue'

defineProps<{
  asset: 'empty-drive' | 'connection-error' | 'download-idle'
  title: string
  description?: string
  actionLabel?: string
  actionIcon?: Component
}>()

const emit = defineEmits<{
  action: []
}>()
</script>

<style scoped>
.pc-state-panel {
  display: grid;
  place-items: center;
  align-content: center;
  gap: 12px;
  min-height: 300px;
  padding: 28px;
  border: 1px dashed var(--pc-color-border-strong);
  border-radius: var(--pc-radius-md);
  background: var(--pc-color-surface);
  text-align: center;
}

.pc-state-panel-asset {
  width: min(250px, 58vw);
}

.pc-state-panel-copy {
  display: grid;
  gap: 5px;
  max-width: 440px;
}

.pc-state-panel-copy h2,
.pc-state-panel-copy p {
  margin: 0;
}

.pc-state-panel-copy h2 {
  color: var(--pc-color-text);
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
}

.pc-state-panel-copy p {
  color: var(--pc-color-text-muted);
  font-size: 12px;
  line-height: 1.5;
}
</style>
