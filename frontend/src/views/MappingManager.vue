<script setup>
import { ref, onMounted, computed, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Plus, Search, View, Edit, Delete, Connection,
  Document, Refresh, FolderAdd, CircleClose, Warning,
} from '@element-plus/icons-vue'
import api, { mappingApi } from '@/api'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'
import TaskTreeNode from '@/components/TaskTreeNode.vue'

// ════════════════════════════════════════════════════════════════
// 共享：版本 + 原有测试目的逻辑（保留 legacy）
// ════════════════════════════════════════════════════════════════

const versions = ref([])
const selectedVersionId = ref(null)
const purposes = ref([])
const loading = ref(false)
const purposesLoading = ref(false)

const versionDialogVisible = ref(false)
const versionForm = ref({ version_name: '' })

const purposeDialogVisible = ref(false)
const purposeDialogTitle = ref('创建测试目的')
const isEditPurpose = ref(false)
const editPurposeId = ref(null)
const purposeForm = ref({ name: '', description: '', environment: '', taskRefsText: '' })

const discoveredTaskIds = ref([])
const discovering = ref(false)
const discoveredVersionId = ref(null)
const discoveredError = ref(null)

const statsDialogVisible = ref(false)
const statsData = ref(null)
const statsLoading = ref(false)

const taskDialogVisible = ref(false)
const taskPurposeName = ref('')
const taskPurposeId = ref(null)
const taskCreating = ref(false)

onMounted(loadVersions)

const selectedVersion = computed(() =>
  versions.value.find((v) => v.id === selectedVersionId.value) || null
)

async function loadVersions() {
  loading.value = true
  try {
    const { data } = await mappingApi.listVersions()
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
    const { data } = await mappingApi.listPurposes(selectedVersionId.value)
    purposes.value = data
  } finally {
    purposesLoading.value = false
  }
}

function handleVersionChange() {
  purposes.value = []
  trees.value = []
  loadPurposes()
  loadTrees()
}

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
    await mappingApi.createVersion(versionForm.value)
    ElMessage.success('版本已创建')
    versionDialogVisible.value = false
    loadVersions()
  } catch {}
}

async function handleDiscover() {
  if (!selectedVersionId.value) return
  discovering.value = true
  discoveredVersionId.value = selectedVersionId.value
  discoveredError.value = null
  discoveredTaskIds.value = []
  try {
    const { data } = await mappingApi.discoverTasks(selectedVersionId.value)
    discoveredTaskIds.value = data.discovered_task_ids || []
    if (data.error) discoveredError.value = data.error
  } finally {
    discovering.value = false
  }
}

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

// ════════════════════════════════════════════════════════════════
// v5：JSON 树（按轮次管理）—— 主要工作区
// ════════════════════════════════════════════════════════════════

const trees = ref([])
const treesLoading = ref(false)

// ── 追加轮次对话框 ──
const appendDialogVisible = ref(false)
const appendForm = ref({ note: '', jsonText: '' })
const appendSubmitting = ref(false)
const previewResult = ref(null)
const previewing = ref(false)

function openAppendDialog() {
  appendForm.value = { note: '', jsonText: '' }
  previewResult.value = null
  appendDialogVisible.value = true
}

async function handlePreview() {
  if (!appendForm.value.jsonText.trim()) {
    ElMessage.warning('请粘贴 JSON 文本')
    return
  }
  previewing.value = true
  previewResult.value = null
  try {
    const { data } = await mappingApi.previewTree(
      selectedVersionId.value,
      appendForm.value.jsonText,
    )
    previewResult.value = data
  } catch {} finally {
    previewing.value = false
  }
}

async function handleAppend({ alsoCreateTasks = false } = {}) {
  if (!appendForm.value.note.trim()) {
    ElMessage.warning('请输入轮次备注')
    return
  }
  if (!appendForm.value.jsonText.trim()) {
    ElMessage.warning('请粘贴 JSON 文本')
    return
  }
  appendSubmitting.value = true
  try {
    const { data } = await mappingApi.appendTree(
      selectedVersionId.value,
      appendForm.value.jsonText,
      appendForm.value.note,
    )
    ElMessage.success(`已追加轮次 #${data.round_number}（${data.total_nodes} 节点 / ${data.leaf_count} 叶子）`)
    appendDialogVisible.value = false
    await loadTrees()
    if (alsoCreateTasks) {
      await handleCreateTasksFromTree(data.round_number, { silent: true })
    }
  } catch {} finally {
    appendSubmitting.value = false
  }
}

async function handleAutoFetchPlaceholder() {
  try {
    const { data } = await mappingApi.autoFetchTree(selectedVersionId.value, 'placeholder-execution-id')
    // 后端会抛 503，这里兜底
    ElMessage.warning(data?.message || 'auto-fetch 即将推出')
  } catch (e) {
    // axios interceptor 已经弹过错误提示；这里不重复弹
  }
}

// ── 加载轮次列表 ──
async function loadTrees() {
  if (!selectedVersionId.value) return
  treesLoading.value = true
  try {
    const { data } = await mappingApi.listTrees(selectedVersionId.value)
    trees.value = data
  } catch {} finally {
    treesLoading.value = false
  }
}

watch(selectedVersionId, (id) => {
  if (id) loadTrees()
})

// ── 查看树对话框 ──
const viewDialogVisible = ref(false)
const viewTree = ref(null)
const viewLoading = ref(false)
const viewIncludeS3 = ref(true)

async function openViewTree(row) {
  viewDialogVisible.value = true
  viewTree.value = null
  viewLoading.value = true
  try {
    const { data } = await mappingApi.getTree(selectedVersionId.value, row.round_number, {
      includeS3Probe: viewIncludeS3.value,
    })
    viewTree.value = data
  } catch {} finally {
    viewLoading.value = false
  }
}

// 切 S3 探测开关时重新拉
async function toggleViewS3Probe() {
  if (viewTree.value) {
    await openViewTree({ round_number: viewTree.value.round_number })
  }
}

// ── 改备注对话框 ──
const noteDialogVisible = ref(false)
const noteForm = ref({ round: null, note: '' })

function openEditNote(row) {
  noteForm.value = { round: row.round_number, note: row.note || '' }
  noteDialogVisible.value = true
}

async function handleSaveNote() {
  if (!noteForm.value.note.trim()) {
    ElMessage.warning('备注不能为空')
    return
  }
  try {
    await mappingApi.updateNote(
      selectedVersionId.value,
      noteForm.value.round,
      noteForm.value.note,
    )
    ElMessage.success('备注已更新')
    noteDialogVisible.value = false
    loadTrees()
  } catch {}
}

// ── 批量建任务 ──
const createTasksResultVisible = ref(false)
const createTasksResult = ref(null)

async function handleCreateTasksFromTree(roundNumber, { silent = false } = {}) {
  try {
    const { data } = await mappingApi.createTasksFromTree(selectedVersionId.value, roundNumber)
    createTasksResult.value = data
    const total = (data.created?.length || 0) + (data.linked?.length || 0)
    if (!silent) {
      createTasksResultVisible.value = true
    }
    ElMessage.success(
      `轮次 #${roundNumber}：新建 ${data.created?.length || 0} / 关联 ${data.linked?.length || 0} / 跳过 ${data.skipped?.length || 0}（共 ${total}）`
    )
    await loadTrees()
  } catch {}
}

async function handleDeleteTree(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除轮次 #${row.round_number}（${row.root_name}）吗？\n\n` +
      `此操作将解除该轮次节点上所有 Task 的 tree_node_id 关联，\n` +
      `Task 实体保留，节点和树记录被删除。\n\n` +
      `注意：此操作不可恢复。`,
      '删除轮次',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
    const { data } = await mappingApi.deleteTree(selectedVersionId.value, row.round_number)
    ElMessage.success(
      `轮次 #${row.round_number} 已删除（影响 ${data.affected_task_count} 个 Task）`
    )
    loadTrees()
  } catch { /* cancelled */ }
}

// ── 工具 ──
function fmtTime(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

const totalLeavesAcrossRounds = computed(() =>
  trees.value.reduce((sum, t) => sum + (t.leaf_count || 0), 0)
)

// ── 预览面板：折叠默认展开项 ──
const previewCollapse = ref(['tree'])

// ── 工具 ──
function s3MatchedCount(probe) {
  if (!probe) return 0
  return Object.values(probe).filter((v) => v === true).length
}
function s3MissingCount(probe) {
  if (!probe) return 0
  return Object.values(probe).filter((v) => v === false).length
}

// ── 任务树渲染由独立组件 @/components/TaskTreeNode.vue 处理 ──
// 这里不再保留 inline 定义
</script>

<template>
  <div class="page mapping-manager">
    <AppPageHeader
      title="任务映射管理"
      subtitle="按测试版本与测试目的批量管理 S3 分析任务"
    >
      <template #actions>
        <el-button type="primary" @click="openCreateVersion">
          <el-icon><Plus /></el-icon> 创建版本
        </el-button>
      </template>
    </AppPageHeader>

    <el-row :gutter="16">
      <el-col :span="5">
        <AppSection title="测试版本" hint="点击切换">
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
        </AppSection>
      </el-col>

      <el-col :span="19">
        <!-- ───── v5 主区块：JSON 树（按轮次管理） ───── -->
        <AppSection
          v-if="selectedVersion"
          :title="`JSON 树（按轮次管理） — ${selectedVersion.version_name}`"
          :hint="trees.length ? `共 ${trees.length} 个轮次 / ${totalLeavesAcrossRounds} 个叶子` : '点击「追加执行轮次」开始'"
        >
          <template #header>
            <div class="tree-actions">
              <el-button size="small" @click="loadTrees" :loading="treesLoading">
                <el-icon><Refresh /></el-icon> 刷新
              </el-button>
              <el-button size="small" type="primary" @click="openAppendDialog">
                <el-icon><Plus /></el-icon> 追加执行轮次
              </el-button>
            </div>
          </template>

          <el-table
            :data="trees"
            v-loading="treesLoading"
            stripe
            empty-text="暂无轮次，点击右上角「追加执行轮次」开始"
            class="data-table"
          >
            <el-table-column label="轮次" width="80" align="center">
              <template #default="{ row }">
                <el-tag type="primary" effect="plain" size="small">#{{ row.round_number }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="root_name" label="根节点" min-width="160" show-overflow-tooltip />
            <el-table-column prop="root_id" label="根节点 ID" min-width="140" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="num">{{ row.root_id }}</span>
              </template>
            </el-table-column>
            <el-table-column label="节点 / 叶子" width="110" align="center">
              <template #default="{ row }">
                <span class="num">{{ row.total_nodes }}</span>
                <span class="text-muted"> / </span>
                <span class="num strong">{{ row.leaf_count }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="note" label="备注" min-width="200" show-overflow-tooltip />
            <el-table-column label="创建时间" width="170" align="center">
              <template #default="{ row }">
                <span class="num">{{ fmtTime(row.created_at) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="320" fixed="right" align="center">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openViewTree(row)">
                  <el-icon><View /></el-icon> 查看
                </el-button>
                <el-button link type="primary" size="small" @click="openEditNote(row)">
                  <el-icon><Edit /></el-icon> 备注
                </el-button>
                <el-button link type="success" size="small" @click="handleCreateTasksFromTree(row.round_number)">
                  <el-icon><FolderAdd /></el-icon> 建任务
                </el-button>
                <el-button link type="danger" size="small" @click="handleDeleteTree(row)">
                  <el-icon><Delete /></el-icon> 删除
                </el-button>
              </template>
            </el-table-column>
          </el-table>
        </AppSection>

        <!-- ───── legacy 区块：测试目的 ───── -->
        <AppSection
          v-if="selectedVersion"
          :title="`测试目的 — ${selectedVersion.version_name}`"
          hint="legacy 管理方式，建议改用上方 JSON 树轮次管理"
        >
          <template #header>
            <div class="purpose-actions">
              <el-button size="small" @click="handleDiscover" :loading="discovering">
                <el-icon><Search /></el-icon> 发现 S3 任务
              </el-button>
              <el-button size="small" type="primary" @click="openCreatePurpose">
                <el-icon><Plus /></el-icon> 创建目的
              </el-button>
            </div>
          </template>

          <el-alert
            v-if="trees.length === 0"
            type="info"
            :closable="false"
            style="margin-bottom: 12px"
          >
            推荐使用上方「JSON 树（按轮次管理）」：粘贴任务树 JSON → 预览 → 追加 → 按轮次批量建任务。
          </el-alert>

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

          <el-table :data="purposes" v-loading="purposesLoading" stripe empty-text="暂无测试目的" class="data-table">
            <el-table-column label="测试目的" min-width="180" show-overflow-tooltip>
              <template #default="{ row }">
                <span class="strong">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column prop="environment" label="执行环境" min-width="140" show-overflow-tooltip />
            <el-table-column label="关联任务数" width="100" align="center">
              <template #default="{ row }">
                <el-tag size="small">{{ (row.task_refs || []).length }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="轮次范围" width="120" align="center">
              <template #default="{ row }">
                <template v-if="row.task_refs && row.task_refs.length">
                  <span class="num">
                    #{{ Math.min(...row.task_refs.map((t) => t.round_number)) }}
                    ~
                    #{{ Math.max(...row.task_refs.map((t) => t.round_number)) }}
                  </span>
                </template>
                <span v-else class="text-muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="TASK ID 列表" min-width="280" show-overflow-tooltip>
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
                  <span v-if="!row.task_refs || !row.task_refs.length" class="text-muted">—</span>
                </div>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="220" fixed="right" align="center">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openEditPurpose(row)">编辑</el-button>
                <el-button link type="success" size="small" @click="openCreateTask(row)">创建任务</el-button>
                <el-button link type="primary" size="small" @click="handleStats(row)">统计</el-button>
                <el-button link type="danger" size="small" @click="handleDeletePurpose(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </AppSection>

        <AppSection v-else title="" hint="请选择或创建一个测试版本" />
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
            <el-col :span="6"><div class="s-stat"><span class="s-num success">{{ statsData.auto_analyzed }}</span><span class="s-label">自动分析 {{ statsData.auto_analyzed_pct }}%</span></div></el-col>
            <el-col :span="6"><div class="s-stat"><span class="s-num primary">{{ statsData.human_reviewed }}</span><span class="s-label">人工已审核</span></div></el-col>
          </el-row>
          <el-row :gutter="14" style="margin-bottom: 16px">
            <el-col :span="6"><div class="s-stat"><span class="s-num warning">{{ statsData.human_overridden }}</span><span class="s-label">人工已覆盖</span></div></el-col>
            <el-col :span="6"><div class="s-stat"><span class="s-num danger">{{ statsData.remaining_unreviewed }}</span><span class="s-label">尚未审核</span></div></el-col>
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

    <!-- ═══ v5：追加执行轮次 ═══ -->
    <el-dialog v-model="appendDialogVisible" title="追加执行轮次" width="780px" :close-on-click-modal="false">
      <el-form :model="appendForm" label-width="80px">
        <el-form-item label="轮次备注" required>
          <el-input
            v-model="appendForm.note"
            placeholder="如: 2026-07-07 修复轮次"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
        <el-form-item label="任务树 JSON">
          <el-input
            v-model="appendForm.jsonText"
            type="textarea"
            :rows="10"
            placeholder='粘贴 task_result.json 内容，例如：&#10;{&#10;  "Name": "S1-10G-8S28/R45_B2B_part1",&#10;  "Id": "3806765545196879872",&#10;  "child_tasks": [...]&#10;}'
            class="json-textarea"
            spellcheck="false"
          />
          <div class="form-hint">
            顶层必须是对象，节点必填 Id。叶子 = child_tasks 为空数组/缺失/null。
          </div>
        </el-form-item>
        <el-form-item>
          <el-button @click="handlePreview" :loading="previewing">
            <el-icon><Document /></el-icon> 解析预览
          </el-button>
          <el-button @click="handleAutoFetchPlaceholder">
            <el-icon><Connection /></el-icon> 按执行 ID 自动获取
          </el-button>
        </el-form-item>
      </el-form>

      <!-- 预览结果面板 -->
      <div v-if="previewResult" class="preview-panel">
        <div class="preview-summary">
          <el-tag type="info" size="small">{{ previewResult.total_nodes }} 节点</el-tag>
          <el-tag type="success" size="small">{{ previewResult.leaf_count }} 叶子</el-tag>
          <el-tag
            :type="previewResult.conflicts.length > 0 ? 'danger' : 'success'"
            size="small"
          >
            跨 round 冲突 {{ previewResult.conflicts.length }}
          </el-tag>
          <el-tag
            :type="s3MatchedCount(previewResult.s3_probe) === previewResult.leaf_count && previewResult.leaf_count > 0 ? 'success' : 'warning'"
            size="small"
          >
            S3 匹配 {{ s3MatchedCount(previewResult.s3_probe) }} / {{ previewResult.leaf_count }}
          </el-tag>
          <el-tag
            v-if="previewResult.extra_fields_seen.length"
            size="small"
          >
            extra: {{ previewResult.extra_fields_seen.join(', ') }}
          </el-tag>
        </div>

        <el-collapse v-model="previewCollapse">
          <el-collapse-item title="树形预览" name="tree">
            <div class="tree-preview">
              <TaskTreeNode :node="previewResult.tree" :depth="0" />
            </div>
          </el-collapse-item>
          <el-collapse-item
            v-if="previewResult.conflicts.length"
            title="跨 round 冲突（追加会被拒绝）"
            name="conflicts"
          >
            <el-alert type="error" :closable="false" style="margin-bottom: 8px">
              以下 Id 已在本 version 的其他轮次存在，追加将被拒绝。请修改 JSON 中的 Id 后重试。
            </el-alert>
            <el-table :data="previewResult.conflicts" size="small" max-height="200">
              <el-table-column prop="node_id" label="冲突 ID" min-width="200" />
              <el-table-column prop="conflicting_round" label="所在轮次" width="100" align="center">
                <template #default="{ row }">#{{ row.conflicting_round }}</template>
              </el-table-column>
            </el-table>
          </el-collapse-item>
          <el-collapse-item
            v-if="s3MissingCount(previewResult.s3_probe) > 0"
            title="S3 未匹配的叶子（追加后该叶子将无法创建任务）"
            name="s3-missing"
          >
            <div class="s3-missing">
              <el-tag
                v-for="(ok, leafId) in previewResult.s3_probe"
                :key="leafId"
                v-show="!ok"
                size="small"
                type="warning"
                style="margin: 2px"
              >
                {{ leafId }}
              </el-tag>
            </div>
          </el-collapse-item>
        </el-collapse>
      </div>

      <template #footer>
        <el-button @click="appendDialogVisible = false">取消</el-button>
        <el-button @click="handleAppend()" :loading="appendSubmitting" :disabled="!!previewResult && previewResult.conflicts.length > 0">
          仅追加
        </el-button>
        <el-button
          type="primary"
          :loading="appendSubmitting"
          :disabled="!!previewResult && previewResult.conflicts.length > 0"
          @click="handleAppend({ alsoCreateTasks: true })"
        >
          追加并创建任务
        </el-button>
      </template>
    </el-dialog>

    <!-- ═══ v5：查看树形 ═══ -->
    <el-dialog
      v-model="viewDialogVisible"
      :title="viewTree ? `查看树 — 轮次 #${viewTree.round_number} ${viewTree.root_name}` : '加载中...'"
      width="780px"
      :close-on-click-modal="false"
    >
      <div v-loading="viewLoading">
        <template v-if="viewTree">
          <el-row :gutter="12" style="margin-bottom: 12px">
            <el-col :span="6"><div class="s-stat"><span class="s-num">{{ viewTree.total_nodes }}</span><span class="s-label">总节点</span></div></el-col>
            <el-col :span="6"><div class="s-stat"><span class="s-num primary">{{ viewTree.leaf_count }}</span><span class="s-label">叶子</span></div></el-col>
            <el-col :span="12">
              <div class="s-stat">
                <span class="s-label">S3 探测</span>
                <el-switch
                  v-model="viewIncludeS3"
                  size="small"
                  inline-prompt
                  active-text="开启"
                  inactive-text="关闭"
                  style="margin-top: 4px"
                  @change="toggleViewS3Probe"
                />
              </div>
            </el-col>
          </el-row>
          <el-alert
            v-if="viewTree.note"
            :title="`备注：${viewTree.note}`"
            type="info"
            :closable="false"
            style="margin-bottom: 12px"
          />
          <div class="view-tree-panel">
            <TaskTreeNode :node="viewTree.tree" :depth="0" :show-s3="viewIncludeS3" />
          </div>
        </template>
      </div>
    </el-dialog>

    <!-- ═══ v5：改备注 ═══ -->
    <el-dialog v-model="noteDialogVisible" :title="`改备注 — 轮次 #${noteForm.round}`" width="480px">
      <el-form :model="noteForm" label-width="60px">
        <el-form-item label="备注" required>
          <el-input
            v-model="noteForm.note"
            type="textarea"
            :rows="3"
            maxlength="200"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="noteDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveNote">保存</el-button>
      </template>
    </el-dialog>

    <!-- ═══ v5：批量建任务结果 ═══ -->
    <el-dialog v-model="createTasksResultVisible" title="批量建任务结果" width="640px">
      <template v-if="createTasksResult">
        <el-row :gutter="12" style="margin-bottom: 12px">
          <el-col :span="8">
            <div class="s-stat">
              <span class="s-num success">{{ createTasksResult.created?.length || 0 }}</span>
              <span class="s-label">新建 Task</span>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="s-stat">
              <span class="s-num primary">{{ createTasksResult.linked?.length || 0 }}</span>
              <span class="s-label">关联已有 Task</span>
            </div>
          </el-col>
          <el-col :span="8">
            <div class="s-stat">
              <span class="s-num warning">{{ createTasksResult.skipped?.length || 0 }}</span>
              <span class="s-label">跳过（S3 无数据）</span>
            </div>
          </el-col>
        </el-row>

        <template v-if="createTasksResult.skipped?.length">
          <h4 class="result-section-title">
            <el-icon><Warning /></el-icon> 跳过的叶子（S3 路径不存在或无数据）
          </h4>
          <div class="skipped-tags">
            <el-tag
              v-for="item in createTasksResult.skipped"
              :key="item.leaf_id"
              size="small"
              type="warning"
              style="margin: 2px"
            >
              {{ item.leaf_id }} ({{ item.name }})
            </el-tag>
          </div>
        </template>

        <template v-if="createTasksResult.created?.length">
          <h4 class="result-section-title">新建 Task</h4>
          <el-table :data="createTasksResult.created" size="small" max-height="200">
            <el-table-column prop="name" label="名称" min-width="220" show-overflow-tooltip />
            <el-table-column prop="leaf_id" label="Leaf ID" min-width="160" />
          </el-table>
        </template>
      </template>
      <template #footer>
        <el-button type="primary" @click="createTasksResultVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.mapping-manager {
  max-width: 1400px;
}

.version-list {
  min-height: 200px;
  max-height: 600px;
  overflow-y: auto;
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--space-sm);
}
.version-item {
  padding: var(--space-md) var(--space-lg);
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: var(--space-md);
  margin-bottom: 2px;
  transition: background 0.1s;
}
.version-item:hover {
  background: var(--bg-hover);
}
.version-item.active {
  background: var(--color-primary);
  color: var(--text-inverse);
}
.version-name {
  font-size: var(--text-body);
  font-weight: 500;
}

.purpose-actions {
  display: flex;
  gap: var(--space-sm);
}

.data-table :deep(.el-table__row) {
  height: var(--table-row-h);
}
.data-table :deep(.el-table__cell) {
  padding-block: var(--table-cell-py);
}

.strong { font-weight: 500; color: var(--text-primary); }
.num { font-family: var(--font-mono); font-size: var(--text-small); }
.text-muted { color: var(--text-muted); }

.discovered-box {
  background: #f0f9eb;
  border: 1px solid #e1f3d8;
  border-radius: var(--radius-md);
  padding: var(--space-md) var(--space-lg);
  margin-bottom: var(--space-lg);
}
.discovered-title {
  font-size: var(--text-body);
  color: var(--color-success);
  margin-bottom: var(--space-md);
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
  font-size: var(--text-tiny);
  color: var(--text-muted);
  margin-top: var(--space-xs);
}

.s-stat {
  text-align: center;
  padding: var(--space-md) var(--space-xs);
  background: var(--bg-input);
  border-radius: var(--radius-md);
}
.s-num {
  display: block;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.s-label {
  display: block;
  font-size: var(--text-tiny);
  color: var(--text-secondary);
  margin-top: 2px;
}
.s-num.success { color: var(--color-success); }
.s-num.primary { color: var(--color-primary); }
.s-num.warning { color: var(--color-warning); }
.s-num.danger  { color: var(--color-error); }

/* ── v5 JSON 树区块 ── */
.tree-actions {
  display: flex;
  gap: var(--space-sm);
}

.json-textarea :deep(textarea) {
  font-family: var(--font-mono);
  font-size: var(--text-small);
  line-height: 1.5;
}

.preview-panel {
  background: var(--bg-input);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--space-md);
  margin-top: var(--space-md);
}
.preview-summary {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-md);
}
.tree-preview,
.view-tree-panel {
  max-height: 360px;
  overflow-y: auto;
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: var(--space-sm);
}

.s3-missing {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}
.skipped-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
  max-height: 120px;
  overflow-y: auto;
}
.result-section-title {
  font-size: var(--text-small);
  color: var(--text-secondary);
  margin: var(--space-md) 0 var(--space-xs);
  display: flex;
  align-items: center;
  gap: 4px;
}

/* TaskTreeNode 样式已迁到 @/components/TaskTreeNode.vue */
</style>
