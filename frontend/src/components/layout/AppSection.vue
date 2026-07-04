<script setup>
defineProps({
  title: { type: String, default: '' },
  hint: { type: String, default: '' },
  collapsible: { type: Boolean, default: false },
  defaultCollapsed: { type: Boolean, default: false },
  flush: { type: Boolean, default: false },
})
</script>

<template>
  <section class="section" :class="{ 'is-flush': flush }">
    <header v-if="title || $slots.header" class="section__header">
      <div class="section__title-wrap">
        <h2 v-if="title" class="section__title">{{ title }}</h2>
        <span v-if="hint" class="section__hint">{{ hint }}</span>
      </div>
      <div v-if="$slots.header" class="section__actions">
        <slot name="header" />
      </div>
    </header>
    <div class="section__body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.section {
  display: flex;
  flex-direction: column;
  gap: var(--space-card);
}
.section__header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-md);
  min-height: 22px;
}
.section__title-wrap {
  display: flex;
  align-items: baseline;
  gap: var(--space-md);
  min-width: 0;
}
.section__title {
  font-size: var(--text-h2);
  font-weight: var(--weight-h);
  color: var(--text-primary);
}
.section__hint {
  font-size: var(--text-tiny);
  color: var(--text-muted);
}
.section__actions {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  flex-shrink: 0;
}
.section__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-card);
}
.section.is-flush .section__body {
  gap: 0;
}
</style>
