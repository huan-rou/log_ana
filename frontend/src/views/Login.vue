<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { authApi } from '@/api'

const router = useRouter()

const username = ref('')
const password = ref('')
const loading = ref(false)
const isLoggedIn = ref(false)
const loginUser = ref(null)

onMounted(async () => {
  // Check if already logged in (token valid)
  const token = localStorage.getItem('token')
  if (token) {
    try {
      const { data } = await authApi.me()
      isLoggedIn.value = true
      loginUser.value = data
    } catch {
      localStorage.removeItem('token')
    }
  }
})

async function handleLogin() {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    const { data } = await authApi.login(username.value, password.value)
    localStorage.setItem('token', data.token)
    localStorage.setItem('user', JSON.stringify(data.user))
    isLoggedIn.value = true
    loginUser.value = data.user
    ElMessage.success('登录成功')
    router.push('/')
  } catch {
    // error already shown by interceptor
  } finally {
    loading.value = false
  }
}

function handleLogout() {
  localStorage.removeItem('token')
  localStorage.removeItem('user')
  isLoggedIn.value = false
  loginUser.value = null
  router.push('/login')
}
</script>

<template>
  <div class="login-shell">
    <div class="login-card" v-if="!isLoggedIn">
      <h2>Log Analyzer</h2>
      <p class="login-subtitle">请登录以继续</p>
      <el-form @submit.prevent="handleLogin">
        <el-form-item>
          <el-input
            v-model="username"
            placeholder="用户名"
            prefix-icon="User"
            size="large"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="密码"
            prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          :loading="loading"
          @click="handleLogin"
          style="width: 100%"
        >
          登 录
        </el-button>
      </el-form>
      <p class="login-hint">默认账号: admin / admin123</p>
    </div>

    <div class="login-card" v-else>
      <h2>已登录</h2>
      <p class="login-subtitle">{{ loginUser?.username }} ({{ loginUser?.role }})</p>
      <el-button type="primary" size="large" @click="router.push('/')" style="width: 100%">
        进入系统
      </el-button>
      <el-button size="large" @click="handleLogout" style="width: 100%; margin-top: 12px">
        退出登录
      </el-button>
    </div>
  </div>
</template>

<style scoped>
.login-shell {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--bg-root, #f5f7fa);
}

.login-card {
  width: 380px;
  padding: 40px 36px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 20px rgba(0,0,0,0.08);
  text-align: center;
}

.login-card h2 {
  font-size: 22px;
  font-weight: 700;
  margin-bottom: 4px;
}

.login-subtitle {
  font-size: 13px;
  color: #909399;
  margin-bottom: 28px;
}

.login-hint {
  margin-top: 16px;
  font-size: 12px;
  color: #c0c4cc;
}
</style>
