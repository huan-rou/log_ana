import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { guest: true, title: '登录' },
  },
  {
    path: '/browse',
    name: 'Browser',
    component: () => import('@/views/Browser.vue'),
    meta: { title: '日志浏览', breadcrumb: '日志浏览' },
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
    meta: { title: '看板', breadcrumb: '看板' },
  },
  {
    path: '/tasks',
    name: 'TaskList',
    component: () => import('@/views/TaskList.vue'),
    meta: { title: '任务列表', breadcrumb: '任务' },
  },
  {
    path: '/tasks/:id',
    name: 'TaskDetail',
    component: () => import('@/views/TaskDetail.vue'),
    meta: { title: '任务详情', breadcrumb: '任务详情' },
  },
  {
    path: '/review',
    name: 'ReviewDashboard',
    component: () => import('@/views/ReviewDashboard.vue'),
    meta: { title: '审核看板', breadcrumb: '审核' },
  },
  {
    path: '/reports',
    name: 'OverallReport',
    component: () => import('@/views/OverallReport.vue'),
    meta: { title: '整体报表', breadcrumb: '整体报表' },
  },
  {
    path: '/users',
    name: 'UserManager',
    component: () => import('@/views/UserManager.vue'),
    meta: { title: '用户管理', breadcrumb: '用户' },
  },
  {
    path: '/mapping',
    name: 'MappingManager',
    component: () => import('@/views/MappingManager.vue'),
    meta: { title: '映射管理', breadcrumb: '映射' },
  },
  {
    path: '/rules/editor',
    name: 'RuleEditor',
    component: () => import('@/views/RuleEditor.vue'),
    meta: {
      title: '规则编辑',
      breadcrumb: [{ label: '规则' }, { label: '规则编辑' }],
      icon: 'SetUp',
      requiresRole: 'analyst', // analyst / admin
    },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.guest) {
    next()
    return
  }
  if (!token) {
    next('/login')
    return
  }
  next()
})

export default router
