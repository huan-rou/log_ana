<script setup>
defineProps({
  version: { type: String, default: 'v0.1' },
})
</script>

<template>
  <footer class="statusbar">
    <div class="statusbar-left">
      <span class="status-item">Log Analyzer {{ version }}</span>
      <span class="status-sep">·</span>
      <slot name="left" />
    </div>
    <div class="statusbar-right">
      <slot name="right">
        <span class="status-item status-item--muted">Ready</span>
      </slot>
    </div>
  </footer>
</template>

<style scoped>
.statusbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--statusbar-h);
  padding: 0 var(--space-xl);
  background: var(--bg-statusbar);
  border-top: 1px solid var(--border-light);
  font-size: var(--text-tiny);
  color: var(--text-secondary);
  flex-shrink: 0;
  user-select: none;
  gap: var(--space-md);
}
.statusbar-left,
.statusbar-right {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  min-width: 0;
}
.statusbar-right {
  justify-content: flex-end;
}
.status-item--muted {
  color: var(--text-muted);
}
.status-sep {
  color: var(--border-color);
}
</style>
