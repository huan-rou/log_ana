import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { guest: true },
  },
  {
    path: '/browse',
    name: 'Browser',
    component: () => import('@/views/Browser.vue'),
  },
  {
    path: '/',
    name: 'Dashboard',
    component: () => import('@/views/Dashboard.vue'),
  },
  {
    path: '/tasks',
    name: 'TaskList',
    component: () => import('@/views/TaskList.vue'),
  },
  {
    path: '/tasks/:id',
    name: 'TaskDetail',
    component: () => import('@/views/TaskDetail.vue'),
  },
  {
    path: '/review',
    name: 'ReviewDashboard',
    component: () => import('@/views/ReviewDashboard.vue'),
  },
  {
    path: '/users',
    name: 'UserManager',
    component: () => import('@/views/UserManager.vue'),
  },
  {
    path: '/mapping',
    name: 'MappingManager',
    component: () => import('@/views/MappingManager.vue'),
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to, _from, next) => {
  const token = localStorage.getItem('token')
  if (to.meta.guest) {
    // Login page — if already logged in, skip
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
