<script setup>
import { ref, onMounted, computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import api from '@/api'

const versions = ref([])
const selectedVersionId = ref(null)
const purposes = ref([])
const loading = ref(false)
const purposesLoading = ref(false)

// ── Version dialog ──
const versionDialogVisible = ref(false)
const versionForm = ref({ version_name: '' })

// ── Purpose dialog ──
const purposeDialogVisible = ref(false)
const purposeDialogTitle = ref('创建测试目的')
const isEditPurpose = ref(false)
const editPurposeId = ref(null)
const purposeForm = ref({ name: '', description: '', environment: '', taskRefsText: '' })

// ── Discovered tasks ──
const discoveredTaskIds = ref([])
const discovering = ref(false)
const discoveredVersionId = ref(null)
const discoveredError = ref(null)

// ── Stats dialog ──
const statsDialogVisible = ref(false)
const statsData = ref(null)
const statsLoading = ref(false)

onMounted(loadVersions)

const selectedVersion = computed(() =>
  versions.value.find((v) => v.id === selectedVersionId.value) || null
)

async function loadVersions() {
  loading.value = true
  try {
    const { data } = await api.get('/mapping/versions')
    versions.value = data
    if (data.length > 0 && !selectedVersionId.value) {
      selectedVersionId.value = data[0].id
    }
    if (selectedVersionId.value) loadPurposes()
  } finally {
    loading.value = false
  }
}

async function loadPurposes() {
  if (!selectedVersionId.value) return
  purposesLoading.value = true
  try {
    const { data } = await api.get('/mapping/purposes', {
      params: { version_id: selectedVersionId.value }
    })
    purposes.value = data
  } finally {
    purposesLoading.value = false
  }
}

function handleVersionChange() {
  purposes.value = []
  loadPurposes()
}

// ── Version CRUD ──
function openCreateVersion() {
  versionForm.value = { version_name: '' }
  versionDialogVisible.value = true
}

async function handleCreateVersion() {
  if (!versionForm.value.version_name) {
    ElMessage.warning('请输入版本名称')
    return
  }
  try {
    await api.post('/mapping/versions', versionForm.value)
    ElMessage.success('版本已创建')
    versionDialogVisible.value = false
    loadVersions()
  } catch {}
}

// ── S3 Discover ──
async function handleDiscover() {
  if (!selectedVersionId.value) return
  discovering.value = true
  discoveredVersionId.value = selectedVersionId.value
  discoveredError.value = null
  discoveredTaskIds.value = []
  try {
    const { data } = await api.post(`/mapping/versions/${selectedVersionId.value}/discover`)
    discoveredTaskIds.value = data.discovered_task_ids || []
    if (data.error) discoveredError.value = data.error
  } finally {
    discovering.value = false
  }
}

// ── Purpose CRUD ──
function openCreatePurpose() {
  isEditPurpose.value = false
  purposeDialogTitle.value = '创建测试目的'
  editPurposeId.value = null
  purposeForm.value = { name: '', description: '', environment: '', taskRefsText: '' }
  purposeDialogVisible.value = true
}

function openEditPurpose(purpose) {
  isEditPurpose.value = true
  purposeDialogTitle.value = '编辑测试目的'
  editPurposeId.value = purpose.id
  purposeForm.value = {
    name: purpose.name,
    description: purpose.description || '',
    environment: purpose.environment || '',
    taskRefsText: (purpose.task_refs || []).map((tr) => `${tr.task_id}:${tr.round_number}`).join('\n'),
  }
  purposeDialogVisible.value = true
}

async function handleSavePurpose() {
  if (!purposeForm.value.name) {
    ElMessage.warning('请输入测试目的名称')
    return
  }

  // Parse taskRefs from text: "task_id:round" per line, or just "task_id"
  const taskRefs = purposeForm.value.taskRefsText
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(':')
      return {
        task_id: parts[0].trim(),
        round_number: parts.length > 1 ? parseInt(parts[1]) || 1 : 1,
      }
    })

  try {
    if (isEditPurpose.value) {
      await api.put(`/mapping/purposes/${editPurposeId.value}`, {
        name: purposeForm.value.name,
        description: purposeForm.value.description || null,
        environment: purposeForm.value.environment || null,
        task_refs: taskRefs,
      })
      ElMessage.success('已更新')
    } else {
      await api.post('/mapping/purposes', {
        version_id: selectedVersionId.value,
        name: purposeForm.value.name,
        description: purposeForm.value.description || null,
        environment: purposeForm.value.environment || null,
        task_refs: taskRefs,
      })
      ElMessage.success('已创建')
    }
    purposeDialogVisible.value = false
    loadPurposes()
  } catch {}
}

async function handleDeletePurpose(purpose) {
  try {
    await ElMessageBox.confirm(
      `确定删除测试目的 "${purpose.name}" 吗？`,
      '删除确认',
      { type: 'warning' }
    )
    await api.delete(`/mapping/purposes/${purpose.id}`)
    ElMessage.success('已删除')
    loadPurposes()
  } catch { /* cancelled */ }
}

async function handleStats(purpose) {
  statsDialogVisible.value = true
  statsData.value = null
  statsLoading.value = true
  try {
    const { data } = await api.get(`/mapping/purposes/${purpose.id}/stats`)
    statsData.value = data
  } finally {
    statsLoading.value = false
  }
}

// ── Create task from purpose ──
const taskDialogVisible = ref(false)
const taskPurposeName = ref('')
const taskPurposeId = ref(null)
const taskCreating = ref(false)

function openCreateTask(purpose) {
  taskPurposeName.value = purpose.name
  taskPurposeId.value = purpose.id
  taskDialogVisible.value = true
}

async function handleCreateTask() {
  taskCreating.value = true
  try {
    const formData = new FormData()
    formData.append('name', taskPurposeName.value)
    formData.append('source_type', 's3')
    formData.append('parser_type', 'html')
    formData.append('purpose_id', taskPurposeId.value)
    const { data } = await api.post('/tasks/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    const count = data.tasks ? data.tasks.length : 0
    ElMessage.success(`已创建 ${count} 个分析任务`)
    taskDialogVisible.value = false
  } catch {} finally {
    taskCreating.value = false
  }
}
</script>

<template>
  <div class="mapping-manager">
    <div class="page-header">
      <h2>任务映射管理</h2>
      <el-button type="primary" @click="openCreateVersion">
        <el-icon><Plus /></el-icon> 创建版本
      </el-button>
    </div>

    <el-row :gutter="16">
      <!-- Version sidebar -->
      <el-col :span="5">
        <el-card>
          <template #header>
            <span>测试版本</span>
          </template>
          <div class="version-list" v-loading="loading">
            <div
              v-for="ver in versions"
              :key="ver.id"
              class="version-item"
              :class="{ active: ver.id === selectedVersionId }"
              @click="selectedVersionId = ver.id; handleVersionChange()"
            >
              <span class="version-name">{{ ver.version_name }}</span>
            </div>
            <el-empty v-if="!versions.length" description="暂无版本" :image-size="40" />
          </div>
        </el-card>
      </el-col>

      <!-- Purposes -->
      <el-col :span="19">
        <el-card v-if="selectedVersion">
          <template #header>
            <div class="purpose-header">
              <span>测试目的 — {{ selectedVersion.version_name }}</span>
              <div>
                <el-button size="small" @click="handleDiscover" :loading="discovering">
                  <el-icon><Search /></el-icon> 发现 S3 任务
                </el-button>
                <el-button size="small" type="primary" @click="openCreatePurpose">
                  <el-icon><Plus /></el-icon> 创建目的
                </el-button>
              </div>
            </div>
          </template>

          <!-- Discovered task IDs -->
          <div v-if="discoveredVersionId === selectedVersion.id" class="discovered-box">
            <template v-if="discoveredError">
              <el-alert :title="discoveredError" type="warning" closable style="margin-bottom: 12px" />
            </template>
            <template v-if="discoveredTaskIds.length > 0">
              <div class="discovered-title">
                发现 {{ discoveredTaskIds.length }} 个 S3 任务 ID（{{ selectedVersion.version_name }}）：
              </div>
              <div class="discovered-tags">
                <el-tag
                  v-for="tid in discoveredTaskIds"
                  :key="tid"
                  size="small"
                  style="margin: 2px"
                  @click="purposeForm.taskRefsText += (purposeForm.taskRefsText ? '\n' : '') + tid + ':1'; purposeDialogVisible = true"
                  title="点击加入新建测试目的"
                >
                  {{ tid }}
                </el-tag>
              </div>
            </template>
            <template v-else-if="!discoveredError">
              <div class="discovered-title" style="color: #e6a23c">未发现任何任务 ID</div>
            </template>
          </div>

          <!-- Purposes table -->
          <el-table :data="purposes" v-loading="purposesLoading" stripe empty-text="暂无测试目的">
            <el-table-column prop="name" label="测试目的" min-width="200" show-overflow-tooltip />
            <el-table-column prop="environment" label="执行环境" width="160" show-overflow-tooltip />
            <el-table-column label="关联任务数" width="100" align="center">
              <template #default="{ row }">
                <el-tag size="small">{{ (row.task_refs || []).length }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="轮次范围" width="120" align="center">
              <template #default="{ row }">
                <template v-if="row.task_refs && row.task_refs.length">
                  <span style="font-size: 12px">
                    #{{ Math.min(...row.task_refs.map((t) => t.round_number)) }}
                    ~
                    #{{ Math.max(...row.task_refs.map((t) => t.round_number)) }}
                  </span>
                </template>
                <span v-else style="color: #c0c4cc">—</span>
              </template>
            </el-table-column>
            <el-table-column label="TASK ID 列表" min-width="280">
              <template #default="{ row }">
                <div class="task-refs-cell">
                  <el-tag
                    v-for="tr in row.task_refs"
                    :key="tr.id"
                    size="small"
                    style="margin: 2px"
                    type="info"
                  >
                    {{ tr.task_id }} <template v-if="tr.round_number > 1">(#{{ tr.round_number }})</template>
                  </el-tag>
                  <span v-if="!row.task_refs || !row.task_refs.length" style="color: #c0c4cc">—</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="140" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openEditPurpose(row)">编辑</el-button>
                <el-button link type="success" size="small" @click="openCreateTask(row)">创建任务</el-button>
                <el-button link type="primary" size="small" @click="handleStats(row)">统计</el-button>
                <el-button link type="danger" size="small" @click="handleDeletePurpose(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-card>

        <el-empty v-else description="请选择或创建一个版本" style="margin-top: 80px" />
      </el-col>
    </el-row>

    <!-- Version Dialog -->
    <el-dialog v-model="versionDialogVisible" title="创建测试版本" width="420px">
      <el-form :model="versionForm" label-width="80px">
        <el-form-item label="版本名称" required>
          <el-input v-model="versionForm.version_name" placeholder="如: 1.2.3" />
        </el-form-item>
        <div class="form-hint" style="margin-bottom: 12px">S3 Bucket/Prefix 从系统配置自动读取</div>
      </el-form>
      <template #footer>
        <el-button @click="versionDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateVersion">创建</el-button>
      </template>
    </el-dialog>

    <!-- Purpose Dialog -->
    <el-dialog v-model="purposeDialogVisible" :title="purposeDialogTitle" width="560px">
      <el-form :model="purposeForm" label-width="100px">
        <el-form-item label="测试目的" required>
          <el-input v-model="purposeForm.name" placeholder="如: 双机热备场景" />
        </el-form-item>
        <el-form-item label="执行环境">
          <el-input v-model="purposeForm.environment" placeholder="如: CentOS7 + Python3.9" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="purposeForm.description" type="textarea" :rows="2" placeholder="这个测试目的是什么" />
        </el-form-item>
        <el-form-item label="关联任务">
          <el-input
            v-model="purposeForm.taskRefsText"
            type="textarea"
            :rows="5"
            placeholder="每行一个：task_id:轮次&#10;如:&#10;nightly_regression:1&#10;nightly_regression_rerun:2"
          />
          <div class="form-hint">格式：task_id:轮次（每行一个）</div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="purposeDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSavePurpose">{{ isEditPurpose ? '保存' : '创建' }}</el-button>
      </template>
    </el-dialog>

    <!-- Stats Dialog -->
    <el-dialog v-model="statsDialogVisible" :title="statsData ? '聚合统计 — ' + statsData.purpose_name : '加载中...'" width="700px">
      <div v-loading="statsLoading">
        <template v-if="statsData">
          <el-row :gutter="14" style="margin-bottom: 16px">
            <el-col :span="6"><div class="s-stat"><span class="s-num">{{ statsData.total_testsuite_files }}</span><span class="s-label">测试套文件</span></div></el-col>
            <el-col :span="6"><div class="s-stat"><span class="s-num">{{ statsData.total_testcase_files }}</span><span class="s-label">测试用例文件</span></div></el-col>
            <el-col :span="6"><div class="s-stat"><span class="s-num" style="color:#67c23a">{{ statsData.auto_analyzed }}</span><span class="s-label">自动分析 {{ statsData.auto_analyzed_pct }}%</span></div></el-col>
            <el-col :span="6"><div class="s-stat"><span class="s-num" style="color:#409eff">{{ statsData.human_reviewed }}</span><span class="s-label">人工已审核</span></div></el-col>
          </el-row>
          <el-row :gutter="14" style="margin-bottom: 16px">
            <el-col :span="6"><div class="s-stat"><span class="s-num" style="color:#e6a23c">{{ statsData.human_overridden }}</span><span class="s-label">人工已覆盖</span></div></el-col>
            <el-col :span="6"><div class="s-stat"><span class="s-num" style="color:#f56c6c">{{ statsData.remaining_unreviewed }}</span><span class="s-label">尚未审核</span></div></el-col>
            <el-col :span="6"><div class="s-stat"><span class="s-num">{{ statsData.task_count }}</span><span class="s-label">关联任务</span></div></el-col>
          </el-row>

          <div v-if="statsData.tasks && statsData.tasks.length" style="margin-top: 16px">
            <h4 style="font-size: 14px; margin-bottom: 8px">各任务明细</h4>
            <el-table :data="statsData.tasks" stripe size="small" max-height="300">
              <el-table-column prop="s3_task_id" label="S3 Task ID" min-width="180" show-overflow-tooltip />
              <el-table-column prop="status" label="状态" width="80">
                <template #default="{ row }">
                  <el-tag :type="row.status === 'completed' ? 'success' : row.status === 'failed' ? 'danger' : 'info'" size="small">{{ row.status }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column prop="files" label="文件数" width="72" align="center" />
              <el-table-column prop="failures" label="失败" width="60" align="center" />
              <el-table-column prop="classified" label="已分类" width="72" align="center" />
              <el-table-column prop="unrecognized" label="未识别" width="72" align="center" />
            </el-table>
          </div>
          <el-empty v-else description="尚未创建分析任务" :image-size="48" />
        </template>
      </div>
    </el-dialog>

    <!-- Create Task Dialog -->
    <el-dialog v-model="taskDialogVisible" title="创建分析任务" width="440px">
      <p style="margin-bottom: 12px">
        将为测试目的 <strong>{{ taskPurposeName }}</strong> 下所有的关联 S3 Task ID 创建分析任务。
      </p>
      <template #footer>
        <el-button @click="taskDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="taskCreating" @click="handleCreateTask">确认创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mapping-manager {
  max-width: 1400px;
  padding: var(--space-xl);
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}
.page-header h2 {
  font-size: 20px;
  font-weight: 600;
}

.version-list {
  min-height: 200px;
  max-height: 600px;
  overflow-y: auto;
}
.version-item {
  padding: 10px 12px;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 2px;
  transition: background 0.1s;
}
.version-item:hover {
  background: #f0f2f5;
}
.version-item.active {
  background: var(--color-primary);
  color: #fff;
}
.version-name {
  font-size: 13px;
  font-weight: 500;
}
.version-badge {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(255,255,255,0.3);
}
.version-item.active .version-badge {
  background: rgba(255,255,255,0.3);
  color: #fff;
}

.purpose-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.discovered-box {
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 14px;
}
.discovered-title {
  font-size: 13px;
  color: #67c23a;
  margin-bottom: 8px;
  font-weight: 500;
}
.discovered-tags {
  max-height: 100px;
  overflow-y: auto;
}

.task-refs-cell {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.form-hint {
  font-size: 11px;
  color: #c0c4cc;
  margin-top: 4px;
}

.s-stat {
  text-align: center;
  padding: 10px 4px;
  background: #f8f9fa;
  border-radius: 6px;
}
.s-num {
  display: block;
  font-size: 22px;
  font-weight: 700;
  color: #303133;
}
.s-label {
  display: block;
  font-size: 11px;
  color: #909399;
  margin-top: 2px;
}
</style>
