<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { authApi } from '@/api'

const route = useRoute()
const router = useRouter()

const STORAGE_KEY = 'ux.sidebar.collapsed'

const collapsed = ref(false)
const currentUser = ref(null)
const userMenuOpen = ref(false)

onMounted(() => {
  collapsed.value = localStorage.getItem(STORAGE_KEY) === '1'
  try {
    const cached = localStorage.getItem('user')
    if (cached) currentUser.value = JSON.parse(cached)
  } catch {}
  if (!route.meta.guest) refreshUser()
})

async function refreshUser() {
  try {
    const { data } = await authApi.me()
    currentUser.value = data
    localStorage.setItem('user', JSON.stringify(data))
  } catch {
    currentUser.value = null
  }
}

watch(collapsed, (v) => localStorage.setItem(STORAGE_KEY, v ? '1' : '0'))

const navItems = [
  { path: '/browse',  label: '浏览', icon: 'FolderOpened' },
  { path: '/',         label: '看板', icon: 'DataAnalysis' },
  { path: '/tasks',    label: '任务', icon: 'List' },
  { path: '/review',   label: '审核', icon: 'Checked' },
  { path: '/rules/editor', label: '规则编辑', icon: 'SetUp', minRole: 'analyst' },
]
const adminNavItems = [
  { path: '/users',   label: '用户', icon: 'User' },
  { path: '/mapping', label: '映射', icon: 'Connection' },
  { path: '/reports', label: '整体报表', icon: 'DataBoard' },
]

const activePath = computed(() => {
  const p = route.path
  if (p.startsWith('/review')) return '/review'
  if (p.startsWith('/reports')) return '/reports'
  if (p.startsWith('/tasks'))  return '/tasks'
  if (p.startsWith('/browse')) return '/browse'
  if (p.startsWith('/rules'))  return '/rules/editor'
  if (p.startsWith('/users'))  return '/users'
  if (p.startsWith('/mapping')) return '/mapping'
  return p === '/' ? '/' : p
})

const isAdmin = computed(() => currentUser.value?.role === 'admin')

const ROLE_RANK = { visitor: 0, analyst: 1, reviewer: 2, admin: 3 }
function roleAtLeast(minRole) {
  if (!minRole) return true
  const cur = ROLE_RANK[currentUser.value?.role] ?? -1
  return cur >= (ROLE_RANK[minRole] ?? 99)
}
const roleLabel = computed(() => {
  const map = { visitor: '游客', analyst: '分析员', reviewer: '审核员', admin: '管理员' }
  return map[currentUser.value?.role] || currentUser.value?.role || ''
})
const userInitial = computed(() =>
  (currentUser.value?.username || '?').slice(0, 1).toUpperCase()
)

function handleLogout() {
  userMenuOpen.value = false
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  currentUser.value = null
  router.push('/login')
}

function toggle() {
  collapsed.value = !collapsed.value
}
</script>

<template>
  <aside class="sidebar" :class="{ 'is-collapsed': collapsed }">
    <div class="sidebar-brand" :title="collapsed ? 'Log Analyzer' : ''">
      <div class="sidebar-logo">LA</div>
      <span v-if="!collapsed" class="sidebar-brand-text">Log Analyzer</span>
    </div>

    <div class="sidebar-group" v-for="(group, gi) in [
      { items: navItems },
      { items: adminNavItems, admin: true },
    ]" :key="gi">
      <template v-if="!group.admin || isAdmin">
        <router-link
          v-for="item in group.items"
          v-show="!item.minRole || roleAtLeast(item.minRole)"
          :key="item.path"
          :to="item.path"
          class="nav-item"
          :class="{ active: activePath === item.path }"
          :title="collapsed ? item.label : ''"
        >
          <el-icon :size="18"><component :is="item.icon" /></el-icon>
          <span v-if="!collapsed" class="nav-label">{{ item.label }}</span>
        </router-link>
      </template>
    </div>

    <div class="sidebar-spacer" />

    <button
      class="sidebar-toggle"
      :title="collapsed ? '展开侧边栏' : '折叠侧边栏'"
      @click="toggle"
    >
      <el-icon :size="14">
        <component :is="collapsed ? 'Expand' : 'Fold'" />
      </el-icon>
      <span v-if="!collapsed" class="nav-label">折叠</span>
    </button>

    <div class="sidebar-user" v-if="currentUser">
      <div class="user-trigger" @click="userMenuOpen = !userMenuOpen">
        <span class="user-avatar">{{ userInitial }}</span>
        <span v-if="!collapsed" class="user-meta">
          <span class="user-name">{{ currentUser.username }}</span>
          <span class="user-role">{{ roleLabel }}</span>
        </span>
      </div>
      <transition name="user-menu">
        <div v-if="userMenuOpen && !collapsed" class="user-menu" @click.stop>
          <div class="user-menu__header">
            <strong>{{ currentUser.username }}</strong>
            <el-tag size="small" effect="plain" type="info">{{ roleLabel }}</el-tag>
          </div>
          <button class="user-menu__item" @click="handleLogout">
            <el-icon :size="14"><SwitchButton /></el-icon>
            <span>退出登录</span>
          </button>
        </div>
      </transition>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: var(--sidebar-w);
  background: var(--bg-sidebar);
  border-right: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width 0.18s ease;
  position: relative;
  overflow: visible;
}
.sidebar.is-collapsed {
  width: var(--sidebar-w-collapsed);
}

.sidebar-brand {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  height: var(--toolbar-h);
  padding: 0 var(--space-lg);
  border-bottom: 1px solid var(--border-light);
  flex-shrink: 0;
}
.sidebar.is-collapsed .sidebar-brand {
  padding: 0;
  justify-content: center;
}
.sidebar-logo {
  width: 24px;
  height: 24px;
  border-radius: var(--radius-md);
  background: var(--color-primary);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  letter-spacing: 0.5px;
  flex-shrink: 0;
}
.sidebar-brand-text {
  font-size: var(--text-small);
  font-weight: 600;
  color: var(--text-primary);
  letter-spacing: 0.3px;
  white-space: nowrap;
}

.sidebar-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--space-md) var(--space-sm);
}

.nav-item {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  height: 32px;
  padding: 0 var(--space-md);
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: var(--text-body);
  white-space: nowrap;
  overflow: hidden;
}
.sidebar.is-collapsed .nav-item {
  padding: 0;
  justify-content: center;
}
.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}
.nav-item.active {
  background: var(--color-primary);
  color: var(--text-inverse);
}
.nav-item.active:hover {
  background: var(--color-primary);
}
.nav-label {
  font-weight: 500;
}

.sidebar-spacer {
  flex: 1;
}

.sidebar-toggle {
  display: flex;
  align-items: center;
  gap: var(--space-lg);
  height: 28px;
  margin: var(--space-sm);
  padding: 0 var(--space-md);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--text-secondary);
  font-size: var(--text-small);
  cursor: pointer;
}
.sidebar.is-collapsed .sidebar-toggle {
  margin: var(--space-sm) auto;
  padding: 0;
  width: 32px;
  justify-content: center;
}
.sidebar-toggle:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.sidebar-user {
  position: relative;
  border-top: 1px solid var(--border-light);
  padding: var(--space-sm);
}
.user-trigger {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-sm);
  border-radius: var(--radius-md);
  cursor: pointer;
  user-select: none;
}
.sidebar.is-collapsed .user-trigger {
  padding: 0;
  justify-content: center;
}
.user-trigger:hover {
  background: var(--bg-hover);
}
.user-avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  font-size: var(--text-small);
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.user-meta {
  display: flex;
  flex-direction: column;
  line-height: 1.2;
  overflow: hidden;
}
.user-name {
  font-size: var(--text-body);
  color: var(--text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.user-role {
  font-size: var(--text-tiny);
  color: var(--text-muted);
}

.user-menu {
  position: absolute;
  left: calc(100% + 8px);
  bottom: 0;
  min-width: 200px;
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
  padding: var(--space-sm);
  z-index: 50;
}
.user-menu__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border-light);
  margin-bottom: var(--space-sm);
}
.user-menu__header strong {
  font-size: var(--text-body);
  color: var(--text-primary);
}
.user-menu__item {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  width: 100%;
  padding: var(--space-sm) var(--space-md);
  border: none;
  background: transparent;
  color: var(--text-primary);
  font-size: var(--text-body);
  text-align: left;
  border-radius: var(--radius-sm);
  cursor: pointer;
}
.user-menu__item:hover {
  background: var(--bg-hover);
  color: var(--color-error);
}

.user-menu-enter-active,
.user-menu-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.user-menu-enter-from,
.user-menu-leave-to {
  opacity: 0;
  transform: translateX(-4px);
}
</style>
