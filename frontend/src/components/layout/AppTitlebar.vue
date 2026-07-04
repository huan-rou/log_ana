<script setup>
import AppBreadcrumb from './AppBreadcrumb.vue'
</script>

<template>
  <header class="titlebar">
    <div class="titlebar-left">
      <slot name="prefix" />
      <AppBreadcrumb />
    </div>
    <div class="titlebar-right">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--toolbar-h);
  padding: 0 var(--space-xl);
  background: var(--bg-titlebar);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
  gap: var(--space-lg);
  user-select: none;
}
.titlebar-left {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  min-width: 0;
  flex: 1;
  overflow: hidden;
}
.titlebar-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-shrink: 0;
}
</style>
