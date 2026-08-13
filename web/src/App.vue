<template>
  <div id="app">
    <router-view v-if="route.meta.public || route.meta.pc" />
    <AppLayout v-else />
  </div>
</template>

<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/layout/app-layout.vue'

const route = useRoute()

watch(
  () => Boolean(route.meta.pc),
  (isPcRoute) => document.body.classList.toggle('pc-mode', isPcRoute),
  { immediate: true },
)

onBeforeUnmount(() => document.body.classList.remove('pc-mode'))
</script>
