<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const trail = computed(() => {
  const matched = route.matched
    .filter((m) => m.meta && (m.meta.title || m.meta.breadcrumb))
  return matched.map((m) => ({
    title: m.meta.breadcrumb || m.meta.title,
    path: m.path || m.redirect || '',
  })).filter((b) => b.title)
})

function go(item) {
  if (item.path && item.path !== route.path) {
    router.push(item.path)
  }
}
</script>

<template>
  <nav v-if="trail.length" class="breadcrumb" aria-label="breadcrumb">
    <template v-for="(item, idx) in trail" :key="item.path + idx">
      <a
        v-if="idx < trail.length - 1 && item.path"
        class="crumb crumb--link"
        @click="go(item)"
      >{{ item.title }}</a>
      <span v-else class="crumb crumb--current">{{ item.title }}</span>
      <span v-if="idx < trail.length - 1" class="crumb-sep">/</span>
    </template>
  </nav>
</template>

<style scoped>
.breadcrumb {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--text-small);
  color: var(--text-muted);
  min-width: 0;
  overflow: hidden;
}
.crumb {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.crumb--link {
  cursor: pointer;
  color: var(--text-secondary);
  transition: color 0.1s;
}
.crumb--link:hover {
  color: var(--color-primary);
}
.crumb--current {
  color: var(--text-primary);
  font-weight: 500;
}
.crumb-sep {
  color: var(--border-color);
  user-select: none;
}
</style>
