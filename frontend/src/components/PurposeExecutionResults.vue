<script setup>
import { computed, onMounted, ref } from 'vue'
import { purposeExecutionApi } from '@/api'

const props = defineProps({
  executionId: { type: String, required: true },
  mockData: { type: Object, default: null },
})
const emit = defineEmits(['open-log', 'open-review'])

const activeDimension = ref('suites')
const loading = ref(false)
const errorMessage = ref('')
const suites = ref([])
const testcases = ref([])
const histories = ref({})
const historyLoading = ref({})
const historyErrors = ref({})
const filters = ref({ status: '', feature: '', suite: '', case_id: '' })

const unknownCount = computed(() => {
  if (activeDimension.value === 'suites') {
    return suites.value.reduce((total, row) => total + (row.unknown || 0), 0)
  }
  return testcases.value.filter((row) => row.last_normalized_status === 'unknown').length
})

function queryParams(includeCase = false) {
  const params = {}
  for (const key of ['status', 'feature', 'suite']) {
    if (filters.value[key]) params[key] = filters.value[key]
  }
  if (includeCase && filters.value.case_id) params.case_id = filters.value.case_id
  return params
}

function contains(value, keyword) {
  return String(value || '').toLowerCase().includes(String(keyword || '').trim().toLowerCase())
}

function mockSuiteRows() {
  return (props.mockData?.suites || []).filter((row) => {
    if (filters.value.status && row.block_status !== filters.value.status && row.suite_normalized_status !== filters.value.status) return false
    if (filters.value.feature && !contains(row.feature, filters.value.feature)) return false
    if (filters.value.suite && !contains(row.suite_name, filters.value.suite)) return false
    return true
  })
}

function mockTestcaseRows() {
  return (props.mockData?.testcases || []).filter((row) => {
    if (filters.value.status && row.last_normalized_status !== filters.value.status) return false
    if (filters.value.feature && !contains(row.first_feature, filters.value.feature)) return false
    if (filters.value.suite && !contains(row.last_suite, filters.value.suite)) return false
    if (filters.value.case_id && !contains(row.case_id, filters.value.case_id)) return false
    return true
  })
}

async function loadResults() {
  loading.value = true
  errorMessage.value = ''
  try {
    if (props.mockData) {
      await new Promise((resolve) => setTimeout(resolve, 120))
      if (activeDimension.value === 'suites') suites.value = mockSuiteRows()
      else testcases.value = mockTestcaseRows()
      return
    }
    if (activeDimension.value === 'suites') {
      const { data } = await purposeExecutionApi.suites(props.executionId, queryParams())
      suites.value = Array.isArray(data) ? data : []
    } else {
      const { data } = await purposeExecutionApi.testcases(props.executionId, queryParams(true))
      testcases.value = Array.isArray(data) ? data : []
    }
  } catch (error) {
    errorMessage.value = error.response?.data?.detail || error.message || '分析结果加载失败'
  } finally {
    loading.value = false
  }
}

async function handleExpand(row, expandedRows) {
  if (row.execution_count <= 1) return
  if (!expandedRows.some((item) => item.case_id === row.case_id) || histories.value[row.case_id]) return
  historyLoading.value[row.case_id] = true
  historyErrors.value[row.case_id] = ''
  try {
    if (props.mockData) {
      await new Promise((resolve) => setTimeout(resolve, 100))
      histories.value[row.case_id] = props.mockData.histories?.[row.case_id] || []
      return
    }
    const { data } = await purposeExecutionApi.testcaseHistory(props.executionId, row.case_id)
    histories.value[row.case_id] = Array.isArray(data) ? data : []
  } catch (error) {
    historyErrors.value[row.case_id] = error.response?.data?.detail || error.message || '执行历史加载失败'
  } finally {
    historyLoading.value[row.case_id] = false
  }
}

function testcaseRowClass({ row }) {
  return row.execution_count > 1 ? '' : 'single-execution'
}

function resultTag(status) {
  return { success: 'success', failed: 'danger', blocked: 'warning', unknown: 'info' }[status] || 'info'
}

function reviewText(status) {
  return { pending: '待审核', confirmed: '已采纳', overridden: '未采纳' }[status] || '无日志'
}

function reviewTag(status) {
  return { confirmed: 'success', overridden: 'warning', pending: 'info' }[status] || 'info'
}

function resetFilters() {
  filters.value = { status: '', feature: '', suite: '', case_id: '' }
  loadResults()
}

onMounted(loadResults)
</script>

<template>
  <div class="purpose-results">
    <el-tabs v-model="activeDimension" class="dimension-tabs" @tab-change="loadResults">
      <el-tab-pane label="测试套维度" name="suites" />
      <el-tab-pane label="测试用例维度" name="testcases" />
    </el-tabs>

    <div class="filters" role="search" aria-label="分析结果筛选">
      <el-select v-model="filters.status" clearable placeholder="结果状态" class="filter-control" @change="loadResults">
        <el-option label="成功" value="success" />
        <el-option label="失败" value="failed" />
        <el-option label="阻塞" value="blocked" />
        <el-option label="未知" value="unknown" />
      </el-select>
      <el-input v-model="filters.feature" clearable placeholder="特性名称" class="filter-control" @keyup.enter="loadResults" />
      <el-input v-model="filters.suite" clearable placeholder="测试套" class="filter-control" @keyup.enter="loadResults" />
      <el-input
        v-if="activeDimension === 'testcases'"
        v-model="filters.case_id"
        clearable
        placeholder="用例编号"
        class="filter-control"
        @keyup.enter="loadResults"
      />
      <el-button type="primary" @click="loadResults">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
    </div>

    <el-alert
      v-if="unknownCount"
      type="warning"
      :closable="false"
      show-icon
      class="quality-alert"
      :title="`发现 ${unknownCount} 条未知原始状态，未计入成功、失败或阻塞统计`"
    />
    <el-alert v-if="errorMessage" type="error" :closable="false" show-icon class="quality-alert" :title="errorMessage" />

    <el-table
      v-if="activeDimension === 'suites'"
      v-loading="loading"
      :data="suites"
      stripe
      max-height="620"
      empty-text="暂无测试套执行记录"
      class="result-table"
    >
      <el-table-column prop="round_number" label="轮次" width="72" align="center">
        <template #default="{ row }"><span class="number">#{{ row.round_number }}</span></template>
      </el-table-column>
      <el-table-column prop="feature" label="首次特性" min-width="150" show-overflow-tooltip />
      <el-table-column prop="source_task_id" label="Task ID" min-width="155" show-overflow-tooltip>
        <template #default="{ row }"><span class="mono">{{ row.source_task_id }}</span></template>
      </el-table-column>
      <el-table-column prop="task_block_id" label="任务块" min-width="150" show-overflow-tooltip>
        <template #default="{ row }"><span class="mono">{{ row.task_block_id }}</span></template>
      </el-table-column>
      <el-table-column prop="suite_name" label="测试套" min-width="150" show-overflow-tooltip>
        <template #default="{ row }">
          <span v-if="row.suite_name">{{ row.suite_name }}</span>
          <el-tag v-else type="danger" size="small" effect="plain">未归组</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="通过" width="68" align="right"><template #default="{ row }"><span class="number ok">{{ row.success }}</span></template></el-table-column>
      <el-table-column label="失败" width="68" align="right"><template #default="{ row }"><span class="number danger">{{ row.failed }}</span></template></el-table-column>
      <el-table-column label="阻塞" width="76" align="right">
        <template #default="{ row }">
          <el-tooltip v-if="row.suite_blocked" content="该任务块内全部用例均明确为 blocked" placement="top">
            <el-tag type="warning" size="small">{{ row.blocked }}</el-tag>
          </el-tooltip>
          <span v-else class="number warning">{{ row.blocked }}</span>
        </template>
      </el-table-column>
      <el-table-column label="环境" width="90" align="center">
        <template #default="{ row }"><span class="muted">{{ row.environment || '待接入' }}</span></template>
      </el-table-column>
      <el-table-column label="异常" min-width="160" show-overflow-tooltip>
        <template #default="{ row }"><span :class="row.anomaly ? 'danger' : 'muted'">{{ row.anomaly || '无' }}</span></template>
      </el-table-column>
      <el-table-column label="日志" width="92" fixed="right" align="center">
        <template #default="{ row }">
          <el-dropdown v-if="row.logs.length" trigger="click" @command="(id) => emit('open-log', id)">
            <el-button link type="primary">日志 {{ row.logs.length }}</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item v-for="log in row.logs" :key="log.id" :command="log.id">{{ log.name }}</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span v-else class="muted">无日志</span>
        </template>
      </el-table-column>
    </el-table>

    <el-table
      v-else
      v-loading="loading"
      :data="testcases"
      row-key="case_id"
      stripe
      max-height="620"
      empty-text="暂无测试用例执行记录"
      class="result-table"
      :row-class-name="testcaseRowClass"
      @expand-change="handleExpand"
    >
      <el-table-column type="expand" width="44">
        <template #default="{ row }">
          <div class="history-wrap" v-loading="historyLoading[row.case_id]">
            <el-alert
              v-if="historyErrors[row.case_id]"
              type="error"
              :closable="false"
              show-icon
              class="history-error"
              :title="historyErrors[row.case_id]"
            />
            <el-table :data="histories[row.case_id] || []" size="small" empty-text="暂无执行历史">
              <el-table-column prop="round_number" label="轮次" width="68"><template #default="{ row: item }">#{{ item.round_number }}</template></el-table-column>
              <el-table-column prop="end_time" label="结束时间" min-width="150"><template #default="{ row: item }">{{ item.end_time || '未记录' }}</template></el-table-column>
              <el-table-column prop="feature" label="特性" min-width="130" show-overflow-tooltip />
              <el-table-column prop="suite" label="测试套" min-width="130" show-overflow-tooltip />
              <el-table-column prop="task_block_id" label="任务块" min-width="130" show-overflow-tooltip />
              <el-table-column label="原始结果" width="92"><template #default="{ row: item }"><el-tag :type="resultTag(item.normalized_status)" size="small">{{ item.raw_result || '未知' }}</el-tag></template></el-table-column>
              <el-table-column prop="analysis_conclusion" label="分析结论" min-width="150" show-overflow-tooltip><template #default="{ row: item }">{{ item.analysis_conclusion || '暂无结论' }}</template></el-table-column>
              <el-table-column label="审核" width="90"><template #default="{ row: item }"><el-tag :type="reviewTag(item.review_status)" size="small" effect="plain">{{ reviewText(item.review_status) }}</el-tag></template></el-table-column>
              <el-table-column label="操作" width="118" fixed="right">
                <template #default="{ row: item }">
                  <el-button v-if="item.log_file_id" link type="primary" @click="emit('open-log', item.log_file_id)">日志</el-button>
                  <el-button v-if="item.log_file_id" link type="primary" @click="emit('open-review', item.log_file_id)">审核</el-button>
                  <span v-if="!item.log_file_id" class="muted">无日志</span>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="case_id" label="用例编号" min-width="180" show-overflow-tooltip><template #default="{ row }"><span class="mono">{{ row.case_id }}</span></template></el-table-column>
      <el-table-column prop="first_feature" label="首次特性" min-width="140" show-overflow-tooltip />
      <el-table-column prop="last_suite" label="最后所属套件" min-width="150" show-overflow-tooltip />
      <el-table-column prop="execution_count" label="执行次数" width="88" align="right"><template #default="{ row }"><span class="number">{{ row.execution_count }}</span></template></el-table-column>
      <el-table-column label="最后原始结果" width="118" align="center"><template #default="{ row }"><el-tag :type="resultTag(row.last_normalized_status)" size="small">{{ row.last_result || '未知' }}</el-tag></template></el-table-column>
      <el-table-column prop="final_root_cause" label="最终根因" min-width="170" show-overflow-tooltip><template #default="{ row }">{{ row.final_root_cause || '暂无结论' }}</template></el-table-column>
      <el-table-column label="审核状态" width="100" align="center"><template #default="{ row }"><el-tag :type="reviewTag(row.review_status)" size="small" effect="plain">{{ reviewText(row.review_status) }}</el-tag></template></el-table-column>
      <el-table-column label="操作" width="118" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.log_file_id" link type="primary" @click="emit('open-log', row.log_file_id)">日志</el-button>
          <el-button v-if="row.log_file_id" link type="primary" @click="emit('open-review', row.log_file_id)">审核</el-button>
          <span v-if="!row.log_file_id" class="muted">无日志</span>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.purpose-results { min-width: 0; }
.dimension-tabs { margin-bottom: 2px; }
.filters { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; align-items: center; }
.filter-control { width: 150px; }
.quality-alert { margin-bottom: 12px; }
.result-table { width: 100%; }
.history-wrap { padding: 12px 18px 16px; background: var(--bg-root); border-left: 3px solid var(--color-primary); }
.history-error { margin-bottom: 10px; }
.result-table :deep(.single-execution .el-table__expand-icon) { visibility: hidden; pointer-events: none; }
.number, .mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; }
.ok { color: var(--color-success); }
.danger { color: var(--color-error); }
.warning { color: var(--color-warning); }
.muted { color: var(--text-secondary); }
@media (max-width: 900px) {
  .filter-control { width: calc(50% - 4px); }
}
</style>
