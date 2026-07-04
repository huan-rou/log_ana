<script setup>
import AppSidebar from '@/components/layout/AppSidebar.vue'
import AppTitlebar from '@/components/layout/AppTitlebar.vue'
import AppStatusbar from '@/components/layout/AppStatusbar.vue'
</script>

<template>
  <div class="app-shell">
    <AppTitlebar>
      <template #actions>
        <span class="titlebar-hint" title="当前为浅色主题">主题</span>
        <span class="titlebar-hint" title="帮助">帮助</span>
      </template>
    </AppTitlebar>

    <div class="app-body">
      <AppSidebar />
      <main class="main-area">
        <div class="view-scroll">
          <router-view />
        </div>
      </main>
    </div>

    <AppStatusbar>
      <template #left>
        <span>前端重构预演 · 导航与布局壳</span>
      </template>
      <template #right>
        <span class="status-item--muted">Ready</span>
      </template>
    </AppStatusbar>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
  min-height: 0;
}

.main-area {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--bg-root);
  min-width: 0;
}
.view-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
}

.titlebar-hint {
  font-size: var(--text-tiny);
  color: var(--text-muted);
  padding: 2px var(--space-sm);
  border-radius: var(--radius-sm);
  cursor: default;
  user-select: none;
}
.titlebar-hint:hover {
  background: var(--bg-hover);
  color: var(--text-secondary);
}

.status-item--muted {
  color: var(--text-muted);
}
</style>
