<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { authApi } from '@/api'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'

const users = ref([])
const loading = ref(false)

// ── Create / Edit dialog ──
const dialogVisible = ref(false)
const dialogTitle = ref('创建用户')
const isEdit = ref(false)
const form = ref({ username: '', password: '', role: 'visitor' })
const editUserId = ref(null)

const roleOptions = [
  { value: 'visitor', label: '游客 (只能浏览)' },
  { value: 'analyst', label: '分析人员 (可审核分析结果)' },
  { value: 'reviewer', label: '审核人员 (审核+启动任务)' },
  { value: 'admin', label: '管理员 (全部权限)' },
]

const roleLabel = (r) => roleOptions.find((o) => o.value === r)?.label || r

onMounted(loadUsers)

async function loadUsers() {
  loading.value = true
  try {
    const { data } = await authApi.listUsers()
    users.value = data
  } finally {
    loading.value = false
  }
}

function openCreate() {
  isEdit.value = false
  dialogTitle.value = '创建用户'
  form.value = { username: '', password: '', role: 'visitor' }
  editUserId.value = null
  dialogVisible.value = true
}

function openEdit(user) {
  isEdit.value = true
  dialogTitle.value = '编辑用户'
  form.value = { username: user.username, password: '', role: user.role }
  editUserId.value = user.id
  dialogVisible.value = true
}

async function handleSubmit() {
  if (!form.value.username) {
    ElMessage.warning('请输入用户名')
    return
  }
  try {
    if (isEdit.value) {
      await authApi.updateUser(editUserId.value, form.value)
      ElMessage.success('用户已更新')
    } else {
      if (!form.value.password) {
        ElMessage.warning('请输入密码')
        return
      }
      await authApi.createUser(form.value)
      ElMessage.success('用户已创建')
    }
    dialogVisible.value = false
    loadUsers()
  } catch {
    // error shown by interceptor
  }
}

async function handleDelete(user) {
  try {
    await ElMessageBox.confirm(`确定要删除用户 "${user.username}" 吗？`, '删除确认', { type: 'warning' })
    await authApi.deleteUser(user.id)
    ElMessage.success('已删除')
    loadUsers()
  } catch { /* cancelled */ }
}
</script>

<template>
  <div class="page user-manager">
    <AppPageHeader
      title="用户管理"
      subtitle="管理系统用户、分配角色权限"
    >
      <template #actions>
        <el-button type="primary" @click="openCreate">
          <el-icon><Plus /></el-icon> 创建用户
        </el-button>
      </template>
    </AppPageHeader>

    <AppSection title="用户列表" :hint="`共 ${users.length} 人`">
      <el-table :data="users" v-loading="loading" stripe class="data-table">
        <el-table-column prop="username" label="用户名" min-width="160" show-overflow-tooltip />
        <el-table-column label="角色" min-width="280">
          <template #default="{ row }">
            <el-tag :type="row.role === 'admin' ? 'danger' : row.role === 'reviewer' ? '' : 'info'">
              {{ roleLabel(row.role) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" fixed="right" width="180" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </AppSection>

    <!-- Create / Edit Dialog -->
    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="440px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="用户名">
          <el-input v-model="form.username" :disabled="isEdit" placeholder="输入用户名" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="form.password" type="password" :placeholder="isEdit ? '留空则不修改密码' : '输入密码'" show-password />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role" style="width: 100%">
            <el-option
              v-for="opt in roleOptions"
              :key="opt.value"
              :label="opt.label"
              :value="opt.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSubmit">{{ isEdit ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.user-manager {
  max-width: 1080px;
}
.data-table :deep(.el-table__row) {
  height: var(--table-row-h);
}
.data-table :deep(.el-table__cell) {
  padding-block: var(--table-cell-py);
}
</style>
