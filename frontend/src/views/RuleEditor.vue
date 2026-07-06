<script setup>
import { ref, reactive, computed, onMounted, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Refresh, Plus, View, Edit, Delete, Position,
  Check, Close, VideoPlay, SwitchButton,
} from '@element-plus/icons-vue'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'
import { ruleApi } from '@/api'

// ── 当前用户角色 ──
const ROLE_RANK = { visitor: 0, analyst: 1, reviewer: 2, admin: 3 }
const currentUser = ref(null)
function loadUser() {
  try {
    const cached = localStorage.getItem('user')
    if (cached) currentUser.value = JSON.parse(cached)
  } catch {}
}
loadUser()
const userRole = computed(() => currentUser.value?.role || 'visitor')
const isAdmin = computed(() => userRole.value === 'admin')
const isAnalyst = computed(() => ROLE_RANK[userRole.value] >= ROLE_RANK.analyst)

// ── 状态 ──
const loading = ref(false)
const rules = ref([])

async function loadRules() {
  loading.value = true
  try {
    const { data } = await ruleApi.list()
    rules.value = data || []
  } catch (e) {
    // 拦截器已弹错误
  } finally {
    loading.value = false
  }
}
onMounted(loadRules)

// ── 工具 ──
const STATUS_LABEL = { draft: '草稿', published: '已发布' }
const STATUS_TYPE  = { draft: 'info', published: 'success' }
const SOURCE_LABEL = { builtin: '系统', user: '用户' }
const MATCH_LABEL  = { relevant_log: '失败块', traceback: '调用栈' }

function statusTag(s) {
  return { label: STATUS_LABEL[s] || s || '—', type: STATUS_TYPE[s] || 'info' }
}
function canModify(r) {
  if (isAdmin.value) return r.source === 'user' // 管理员只能改 user 规则
  if (!isAnalyst.value) return false
  return r.source === 'user' && r.created_by === currentUser.value?.id
}
function canEditMeta(r) {
  // 名称/备注权限：系统规则→仅admin；用户规则→本人或admin
  if (isAdmin.value) return true
  if (!isAnalyst.value) return false
  return r.source === 'user' && r.created_by === currentUser.value?.id
}
function canView(r) {
  return isAnalyst.value || isAdmin.value
}
function formatTs(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('zh-CN', { hour12: false })
}

// ── 表单（创建/编辑共用） ──
const formVisible = ref(false)
const formMode = ref('create') // create | edit
const formRef = ref(null)
const form = reactive({
  id: null,         // Rule.id（编辑用）
  rule_id: '',
  name: '',
  category: '',
  priority: 100,
  confidence: 0.8,
  match_source: 'relevant_log',
  pattern: '',
  description: '',
  version: '1.0',
})
const formRules = {
  rule_id: [
    { required: true, message: '请输入 rule_id' },
    { pattern: /^[a-z][a-z0-9_]*$/, message: '必须为 snake_case' },
  ],
  name: [{ required: true, message: '请输入规则名称' }],
  category: [{ required: true, message: '请输入分类（如 产品问题/断言失败）' }],
  priority: [{ required: true, message: '请输入优先级' }],
  confidence: [{ required: true, message: '请输入置信度' }],
  match_source: [{ required: true, message: '请选择匹配源' }],
  pattern: [
    { required: true, message: '请输入正则表达式' },
    {
      validator(_, v, cb) {
        try { new RegExp(v); cb() } catch (e) { cb(new Error('正则非法：' + e.message)) }
      },
      trigger: 'blur',
    },
  ],
}

function openCreate() {
  formMode.value = 'create'
  Object.assign(form, {
    id: null, rule_id: '', name: '', category: '',
    priority: 100, confidence: 0.8,
    match_source: 'relevant_log', pattern: '',
    description: '', version: '1.0',
  })
  formVisible.value = true
}
function openEdit(row) {
  formMode.value = 'edit'
  Object.assign(form, {
    id: row.id,
    rule_id: row.rule_id,
    name: row.name,
    category: row.category,
    priority: row.priority,
    confidence: 0.8, // 后端不在列表返回 confidence；编辑时给默认值即可
    match_source: row.match_source || 'relevant_log',
    pattern: row.pattern || '',
    description: row.description || '',
    version: row.version || '1.0',
  })
  formVisible.value = true
}

// 提交
async function submitForm() {
  if (!formRef.value) return
  await formRef.value.validate(async (ok) => {
    if (!ok) return
    const payload = {
      rule_id: form.rule_id,
      name: form.name,
      category: form.category,
      description: form.description || null,
      priority: Number(form.priority),
      confidence: Number(form.confidence),
      match_source: form.match_source,
      pattern: form.pattern,
      version: form.version,
    }
    try {
      if (formMode.value === 'create') {
        await ruleApi.create(payload)
        ElMessage.success('已创建（草稿）')
      } else {
        await ruleApi.update(form.rule_id, payload)
        ElMessage.success('已保存，状态回到草稿，需重新发布才生效')
      }
      formVisible.value = false
      await loadRules()
    } catch (e) { /* interceptor */ }
  })
}

// ── 预览代码 ──
const previewSrc = ref('')
function buildPreview() {
  if (!form.pattern) { previewSrc.value = ''; return }
  const rid = form.rule_id || 'demo_rule'
  const escaped = form.pattern.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
  const cls = (rid.split('_').filter(Boolean).map(p => p[0].toUpperCase() + p.slice(1)).join('')) + 'UserRule'
  previewSrc.value = `from rules.base import BaseRule, RuleContext, RuleResult
import re

MATCH_SOURCE = "${form.match_source}"
PATTERN = re.compile(r"${escaped}", re.IGNORECASE)

class ${cls}(BaseRule):
    @property
    def rule_id(self): return "${rid}"
    @property
    def name(self): return "${form.name || rid}"
    @property
    def category(self): return "${form.category || '未分类'}"
    @property
    def priority(self): return ${form.priority}
    @property
    def version(self): return "${form.version || '1.0'}"

    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        fe = ctx.failure_event or {}
        block = (fe.get("relevant_log") or ctx.traceback or "") if MATCH_SOURCE != "traceback" else (ctx.traceback or "")
        if not block: return RuleResult.no_match()
        hit_line = next((ln.strip() for ln in block.split("\\n") if PATTERN.search(ln)), None)
        if hit_line is None:
            m = PATTERN.search(block)
            if m is None: return RuleResult.no_match()
            hit_line = m.group(0)
        return RuleResult.match(category=self.category, confidence=${form.confidence},
            evidence=hit_line[:512],
            line_start=fe.get("line_start"), line_end=fe.get("line_end"))
`
}
watch(() => [form.rule_id, form.name, form.category, form.priority,
  form.confidence, form.match_source, form.pattern, form.version],
  buildPreview, { deep: true, immediate: false })

// ── 详情抽屉 ──
const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const detailTab = ref('code') // code | audit

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detailTab.value = 'code'
  try {
    const { data } = await ruleApi.get(row.rule_id)
    detail.value = data
  } catch (e) {
    detail.value = null
  } finally {
    detailLoading.value = false
  }
}

function parseAuditJson(s) {
  if (!s) return null
  try { return JSON.parse(s) } catch { return s }
}

// ── 状态机操作 ──
async function publishRule(row) {
  try {
    await ElMessageBox.confirm(`发布规则 "${row.name}" 后将参与匹配，是否继续？`, '发布确认', { type: 'info' })
  } catch { return }
  try {
    await ruleApi.publish(row.rule_id)
    ElMessage.success('已发布')
    await loadRules()
  } catch {}
}
async function unpublishRule(row) {
  try {
    await ElMessageBox.confirm(`撤销发布后规则将不再参与匹配，是否继续？`, '撤销确认', { type: 'warning' })
  } catch { return }
  try {
    await ruleApi.unpublish(row.rule_id)
    ElMessage.success('已撤销')
    await loadRules()
  } catch {}
}
async function toggleEnabled(row) {
  try {
    await ruleApi.toggleEnabled(row.rule_id, !row.enabled)
    ElMessage.success(row.enabled ? '已禁用' : '已启用')
    await loadRules()
  } catch {}
}
async function deleteRule(row) {
  try {
    await ElMessageBox.confirm(`删除规则 "${row.name}" 后将不可恢复，是否继续？`, '删除确认', { type: 'error' })
  } catch { return }
  try {
    await ruleApi.delete(row.rule_id)
    ElMessage.success('已删除')
    await loadRules()
  } catch {}
}

// 详情抽屉的 audit 时间线颜色辅助
function auditType(action) {
  const map = {
    create: 'primary', update: 'warning', publish: 'success',
    unpublish: 'info', enable: 'success', disable: 'warning', delete: 'danger',
    meta_update: 'primary',
  }
  return map[action] || 'primary'
}

// ── 名称/备注 局部编辑 ──
const metaDialogVisible = ref(false)
const metaFormRef = ref(null)
const metaForm = reactive({
  rule_id: '',
  name: '',
  description: '',
})
const metaFormRules = {
  name: [{ required: true, message: '请输入名称' }],
}
function openMetaDialog(row) {
  metaForm.rule_id = row.rule_id
  metaForm.name = row.name || ''
  metaForm.description = row.description || ''
  metaDialogVisible.value = true
}
async function submitMeta() {
  if (!metaFormRef.value) return
  await metaFormRef.value.validate(async (ok) => {
    if (!ok) return
    try {
      await ruleApi.updateMeta(metaForm.rule_id, {
        name: metaForm.name,
        description: metaForm.description,
      })
      ElMessage.success('已保存名称/备注')
      metaDialogVisible.value = false
      await loadRules()
      // 如果详情抽屉打开着，刷新
      if (detailVisible.value && detail.value && detail.value.rule_id === metaForm.rule_id) {
        const { data } = await ruleApi.get(metaForm.rule_id)
        detail.value = data
      }
    } catch (e) { /* interceptor */ }
  })
}
</script>

<template>
  <AppPageHeader title="规则编辑" subtitle="可视化创建 / 编辑 / 发布 / 启用 / 删除分析规则；所有操作记录在操作历史中">
    <template #actions>
      <el-button :icon="Refresh" @click="loadRules" :loading="loading">刷新</el-button>
      <el-button
        v-if="isAnalyst"
        type="primary" :icon="Plus" @click="openCreate"
      >新建规则</el-button>
    </template>
  </AppPageHeader>

  <!-- 非 analyst/admin -->
  <div v-if="!isAnalyst && !isAdmin" class="empty">
    <el-empty description="需要分析员 / 管理员权限才能访问规则编辑器" />
  </div>

  <template v-else>
    <AppSection title="规则列表" :hint="`共 ${rules.length} 条`">
      <el-table
        :data="rules" v-loading="loading" size="default" stripe
        row-key="id" class="rules-table" :empty-text="'暂无规则'"
      >
        <el-table-column prop="rule_id" label="rule_id" min-width="160">
          <template #default="{ row }">
            <code class="mono">{{ row.rule_id }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="180" show-overflow-tooltip />
        <el-table-column prop="category" label="分类" min-width="160" show-overflow-tooltip />
        <el-table-column prop="priority" label="优先级" width="84" sortable />
        <el-table-column prop="hit_count" label="命中" width="80" align="right">
          <template #default="{ row }">
            <el-tag v-if="row.hit_count > 0" type="success" size="small">{{ row.hit_count }}</el-tag>
            <span v-else class="muted">0</span>
          </template>
        </el-table-column>
        <el-table-column label="匹配源" width="92">
          <template #default="{ row }">
            <span v-if="row.match_source">{{ MATCH_LABEL[row.match_source] || row.match_source }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="96">
          <template #default="{ row }">
            <el-tag
              v-if="row.status"
              :type="statusTag(row.status).type" size="small"
            >{{ statusTag(row.status).label }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="启用" width="72" align="center">
          <template #default="{ row }">
            <el-switch
              v-if="row.status === 'published' && canModify(row)"
              :model-value="row.enabled"
              @change="toggleEnabled(row)"
            />
            <span v-else-if="row.status === 'published'">{{ row.enabled ? '是' : '否' }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="来源" width="76">
          <template #default="{ row }">
            <el-tag size="small" :type="row.source === 'user' ? 'warning' : 'info'" effect="plain">
              {{ SOURCE_LABEL[row.source] || row.source }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建人" min-width="100">
          <template #default="{ row }">
            <span v-if="row.created_by_username">{{ row.created_by_username }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="320" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link :icon="View" @click="openDetail(row)">查看</el-button>
            <template v-if="row.source === 'user' && canModify(row)">
              <el-button
                v-if="row.status === 'draft'"
                size="small" link :icon="Edit" @click="openEdit(row)"
              >编辑</el-button>
              <el-button
                v-if="row.status === 'draft'"
                size="small" link type="primary" :icon="VideoPlay"
                @click="publishRule(row)"
              >发布</el-button>
              <el-button
                v-if="row.status === 'published'"
                size="small" link type="warning"
                @click="unpublishRule(row)"
              >撤销</el-button>
              <el-button
                v-if="(isAdmin || row.status === 'draft')"
                size="small" link type="danger" :icon="Delete"
                @click="deleteRule(row)"
              >删除</el-button>
            </template>
            <span v-else-if="!canModify(row) && row.source === 'user'" class="muted hint">他人规则</span>
          </template>
        </el-table-column>
      </el-table>
    </AppSection>
  </template>

  <!-- 创建/编辑抽屉 -->
  <el-drawer
    v-model="formVisible"
    :title="formMode === 'create' ? '新建规则' : `编辑规则：${form.rule_id}`"
    direction="rtl" size="640px" destroy-on-close
  >
    <el-form ref="formRef" :model="form" :rules="formRules" label-width="92px" size="default">
      <el-form-item label="rule_id" prop="rule_id">
        <el-input v-model="form.rule_id" :disabled="formMode === 'edit'" placeholder="snake_case，唯一" />
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input v-model="form.name" placeholder="如：AssertionError 检测" />
      </el-form-item>
      <el-form-item label="分类" prop="category">
        <el-input v-model="form.category" placeholder="支持 大类/子类（如 产品问题/断言失败）" />
      </el-form-item>
      <el-form-item label="匹配源" prop="match_source">
        <el-radio-group v-model="form.match_source">
          <el-radio value="relevant_log">失败块 (relevant_log)</el-radio>
          <el-radio value="traceback">调用栈 (traceback)</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="正则" prop="pattern">
        <el-input
          v-model="form.pattern" type="textarea" :rows="3" resize="vertical"
          placeholder="Python re 语法；支持 (?i) 等内联标志"
        />
      </el-form-item>
      <el-form-item label="优先级" prop="priority">
        <el-input-number v-model="form.priority" :min="0" :max="1000" :step="1" />
        <span class="muted hint">数值越小越优先（0~1000）</span>
      </el-form-item>
      <el-form-item label="置信度" prop="confidence">
        <el-input-number v-model="form.confidence" :min="0" :max="1" :step="0.05" :precision="2" />
        <span class="muted hint">0.0 ~ 1.0</span>
      </el-form-item>
      <el-form-item label="版本">
        <el-input v-model="form.version" placeholder="如 1.0" />
      </el-form-item>
      <el-form-item label="描述">
        <el-input v-model="form.description" type="textarea" :rows="2" placeholder="可选" />
      </el-form-item>

      <el-divider content-position="left">生成预览（.py 全文）</el-divider>
      <pre v-if="previewSrc" class="code-preview">{{ previewSrc }}</pre>
      <div v-else class="muted hint">填写 rule_id + 正则后将自动生成</div>
    </el-form>
    <template #footer>
      <el-button @click="formVisible = false">取消</el-button>
      <el-button type="primary" @click="submitForm">
        {{ formMode === 'create' ? '保存为草稿' : '保存（回到草稿）' }}
      </el-button>
    </template>
  </el-drawer>

  <!-- 详情抽屉 -->
  <el-drawer
    v-model="detailVisible"
    :title="detail ? `规则详情：${detail.name}` : '规则详情'"
    direction="rtl" size="720px" destroy-on-close
  >
    <div v-loading="detailLoading">
      <template v-if="detail">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="rule_id">{{ detail.rule_id }}</el-descriptions-item>
          <el-descriptions-item label="名称">{{ detail.name }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ detail.category || '—' }}</el-descriptions-item>
          <el-descriptions-item label="优先级">{{ detail.priority }}</el-descriptions-item>
          <el-descriptions-item label="状态">
            <el-tag v-if="detail.status" :type="statusTag(detail.status).type" size="small">
              {{ statusTag(detail.status).label }}
            </el-tag>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="启用">{{ detail.enabled ? '是' : '否' }}</el-descriptions-item>
          <el-descriptions-item label="来源">
            <el-tag size="small" :type="detail.source === 'user' ? 'warning' : 'info'" effect="plain">
              {{ SOURCE_LABEL[detail.source] || detail.source }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="创建人">
            {{ detail.created_by_username || '—' }}
          </el-descriptions-item>
          <el-descriptions-item label="创建时间" :span="2">{{ formatTs(detail.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="发布时间">{{ formatTs(detail.published_at) }}</el-descriptions-item>
          <el-descriptions-item label="最近修改">{{ formatTs(detail.updated_at) }}</el-descriptions-item>
          <el-descriptions-item label="匹配源" :span="2">
            <span v-if="detail.match_source">{{ MATCH_LABEL[detail.match_source] || detail.match_source }}</span>
            <span v-else>—</span>
          </el-descriptions-item>
          <el-descriptions-item label="正则" :span="2">
            <code v-if="detail.pattern" class="mono">{{ detail.pattern }}</code>
            <span v-else class="muted">—</span>
          </el-descriptions-item>
          <el-descriptions-item label="命中次数">{{ detail.hit_count || 0 }}</el-descriptions-item>
          <el-descriptions-item label="版本">{{ detail.version }}</el-descriptions-item>
          <el-descriptions-item v-if="detail.description" label="备注" :span="2">
            <span class="desc-text">{{ detail.description }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="canEditMeta(detail)" class="detail-actions">
          <el-button :icon="Edit" size="small" @click="openMetaDialog(detail)">
            编辑名称/备注
          </el-button>
        </div>

        <el-tabs v-model="detailTab" class="detail-tabs">
          <el-tab-pane v-if="detail.source === 'user'" label="生成的 .py" name="code">
            <pre v-if="detail.source_code" class="code-preview">{{ detail.source_code }}</pre>
            <el-empty v-else description="源文件已删除或不存在" :image-size="60" />
          </el-tab-pane>
          <el-tab-pane label="操作历史" name="audit">
            <el-timeline v-if="detail.audits && detail.audits.length">
              <el-timeline-item
                v-for="a in detail.audits" :key="a.id"
                :type="auditType(a.action)"
                :timestamp="formatTs(a.created_at)"
                placement="top"
              >
                <div class="audit-row">
                  <span class="audit-action">{{ a.action }}</span>
                  <span class="audit-actor">by {{ a.actor_username }}</span>
                  <span v-if="a.ip" class="audit-ip muted">{{ a.ip }}</span>
                </div>
                <div v-if="a.before || a.after" class="audit-diff">
                  <div v-if="a.before" class="diff-block">
                    <div class="diff-label">before</div>
                    <pre>{{ parseAuditJson(a.before) }}</pre>
                  </div>
                  <div v-if="a.after" class="diff-block">
                    <div class="diff-label">after</div>
                    <pre>{{ parseAuditJson(a.after) }}</pre>
                  </div>
                </div>
              </el-timeline-item>
            </el-timeline>
            <el-empty v-else description="暂无操作历史" :image-size="60" />
          </el-tab-pane>
        </el-tabs>
      </template>
    </div>
  </el-drawer>

  <!-- 名称/备注编辑 -->
  <el-dialog
    v-model="metaDialogVisible"
    :title="`编辑名称/备注：${metaForm.rule_id}`"
    width="520px" destroy-on-close
  >
    <el-form ref="metaFormRef" :model="metaForm" :rules="metaFormRules" label-width="72px">
      <el-form-item label="rule_id">
        <el-input v-model="metaForm.rule_id" disabled />
      </el-form-item>
      <el-form-item label="名称" prop="name">
        <el-input v-model="metaForm.name" placeholder="可读名称" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input
          v-model="metaForm.description" type="textarea" :rows="4"
          resize="vertical" placeholder="自定义说明，对所有角色可见"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="metaDialogVisible = false">取消</el-button>
      <el-button type="primary" @click="submitMeta">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.empty { padding: 40px 0; }
.mono {
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  color: var(--text-primary);
}
.muted { color: var(--text-muted); }
.hint { margin-left: 8px; font-size: 12px; color: var(--text-muted); }

.rules-table :deep(.el-table__cell) {
  padding: 6px 0;
}
.code-preview {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 12px 14px;
  border-radius: 6px;
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  line-height: 1.5;
  max-height: 420px;
  overflow: auto;
  white-space: pre;
  margin: 0;
}
.detail-tabs { margin-top: 16px; }
.detail-actions { margin-top: 12px; text-align: right; }
.desc-text { white-space: pre-wrap; word-break: break-all; }
.audit-row {
  display: flex; align-items: center; gap: 12px;
  font-size: 13px;
}
.audit-action {
  font-weight: 600;
  color: var(--text-primary);
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.5px;
}
.audit-actor { color: var(--text-secondary); }
.audit-ip { font-size: 11px; }
.audit-diff {
  display: flex; gap: 8px; margin-top: 6px;
  flex-wrap: wrap;
}
.diff-block {
  flex: 1 1 280px;
  background: var(--bg-soft, #f5f5f7);
  border: 1px solid var(--border-light);
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 11px;
  font-family: var(--font-mono, monospace);
}
.diff-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
}
.diff-block pre {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--text-primary);
}
</style>
