<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from '@/api'

const route = useRoute()
const router = useRouter()

const currentUser = ref(null)

const navItems = [
  { path: '/browse',    label: '浏览', icon: 'FolderOpened' },
  { path: '/',           label: '看板', icon: 'DataAnalysis' },
  { path: '/tasks',      label: '任务', icon: 'List' },
  { path: '/review',     label: '审核', icon: 'Checked' },
]

// Admin-only nav items
const adminNavItems = [
  { path: '/users',      label: '用户', icon: 'User' },
  { path: '/mapping',    label: '映射', icon: 'Connection' },
]

const activeNav = computed(() => {
  if (route.path.startsWith('/review')) return '/review'
  if (route.path.startsWith('/tasks')) return '/tasks'
  if (route.path.startsWith('/browse')) return '/browse'
  if (route.path.startsWith('/users')) return '/users'
  if (route.path.startsWith('/mapping')) return '/mapping'
  return route.path
})

const isAdmin = computed(() => currentUser.value?.role === 'admin')
const userLabel = computed(() => {
  if (!currentUser.value) return ''
  const roleMap = { visitor: '游客', analyst: '分析员', reviewer: '审核员', admin: '管理员' }
  return `${currentUser.value.username} (${roleMap[currentUser.value.role] || currentUser.value.role})`
})

onMounted(async () => {
  try {
    const { data } = await authApi.me()
    currentUser.value = data
    localStorage.setItem('user', JSON.stringify(data))
  } catch {
    currentUser.value = null
  }
})

function handleLogout() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  currentUser.value = null
  router.push('/login')
}
</script>

<template>
  <div class="app-shell">
    <!-- Title bar -->
    <div class="titlebar">
      <span class="titlebar-text">Log Analyzer</span>
      <div class="titlebar-actions">
        <span class="titlebar-dot"></span>
        <span class="titlebar-dot"></span>
        <span class="titlebar-dot close"></span>
      </div>
    </div>

    <div class="app-body">
      <!-- Sidebar -->
      <nav class="sidebar">
        <router-link
          v-for="item in navItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: activeNav === item.path }"
          :title="item.label"
        >
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
        </router-link>

        <router-link
          v-for="item in adminNavItems"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: activeNav === item.path }"
          :title="item.label"
          v-if="isAdmin"
        >
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
        </router-link>

        <div class="sidebar-spacer"></div>

        <div class="sidebar-user" v-if="currentUser" :title="userLabel">
          <span class="user-avatar">{{ currentUser.username[0]?.toUpperCase() }}</span>
        </div>
        <div class="nav-item muted" title="退出登录" @click="handleLogout" v-if="currentUser">
          <el-icon :size="16"><SwitchButton /></el-icon>
        </div>
      </nav>

      <!-- Main -->
      <main class="main-area">
        <div class="view-scroll">
          <router-view />
        </div>
      </main>
    </div>

    <!-- Status bar -->
    <div class="statusbar">
      <span>Log Analyzer v0.1</span>
      <span class="statusbar-right">Ready</span>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* ── Title bar ── */
.titlebar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--toolbar-h);
  padding: 0 var(--space-lg);
  background: var(--bg-titlebar);
  border-bottom: 1px solid var(--border-light);
  user-select: none;
  flex-shrink: 0;
}
.titlebar-text {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  letter-spacing: 0.5px;
}
.titlebar-actions {
  display: flex;
  gap: 6px;
}
.titlebar-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: var(--border-color);
}
.titlebar-dot.close {
  background: var(--color-error);
  opacity: 0.7;
}

/* ── Body ── */
.app-body {
  display: flex;
  flex: 1;
  overflow: hidden;
}

/* ── Sidebar ── */
.sidebar {
  display: flex;
  flex-direction: column;
  align-items: center;
  width: var(--sidebar-w);
  padding: var(--space-sm) 0;
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-light);
  flex-shrink: 0;
}
.nav-item {
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  text-decoration: none;
  margin-bottom: 2px;
  transition: background 0.1s;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.nav-item.active {
  background: var(--color-primary);
  color: var(--text-inverse);
}
.nav-item.muted {
  color: var(--text-muted);
  margin-top: 0;
  margin-bottom: 0;
}
.sidebar-spacer {
  flex: 1;
}

/* ── User area ── */
.sidebar-user {
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 4px;
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  font-size: 12px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: default;
}

/* ── Main area ── */
.main-area {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: var(--bg-root);
}
.view-scroll {
  flex: 1;
  overflow-y: auto;
}

/* ── Status bar ── */
.statusbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: var(--statusbar-h);
  padding: 0 var(--space-lg);
  background: var(--bg-statusbar);
  border-top: 1px solid var(--border-light);
  font-size: 11px;
  color: var(--text-muted);
  flex-shrink: 0;
  user-select: none;
}
.statusbar-right {
  color: var(--text-secondary);
}
</style>
