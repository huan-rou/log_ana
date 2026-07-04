<script setup>
defineProps({
  title: { type: String, required: true },
  subtitle: { type: String, default: '' },
  dense: { type: Boolean, default: false },
})
</script>

<template>
  <header class="page-header" :class="{ 'is-dense': dense }">
    <div class="page-header__main">
      <h1 class="page-header__title">{{ title }}</h1>
      <p v-if="subtitle" class="page-header__subtitle">{{ subtitle }}</p>
      <div v-if="$slots.meta" class="page-header__meta">
        <slot name="meta" />
      </div>
    </div>
    <div v-if="$slots.actions" class="page-header__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-xl);
  padding: 0 0 var(--space-lg);
  border-bottom: 1px solid var(--border-light);
  margin-bottom: var(--space-section);
}
.page-header.is-dense {
  padding-bottom: var(--space-md);
  margin-bottom: var(--space-md);
}
.page-header__main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.page-header__title {
  font-size: var(--text-h1);
  font-weight: var(--weight-h);
  color: var(--text-primary);
  line-height: 1.3;
}
.page-header__subtitle {
  font-size: var(--text-small);
  color: var(--text-secondary);
  line-height: 1.5;
}
.page-header__meta {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  margin-top: var(--space-sm);
  font-size: var(--text-small);
  color: var(--text-secondary);
  flex-wrap: wrap;
}
.page-header__actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
