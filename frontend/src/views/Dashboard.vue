<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { PieChart, BarChart } from 'echarts/charts'
import { TitleComponent, TooltipComponent, LegendComponent, GridComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

use([CanvasRenderer, PieChart, BarChart, TitleComponent, TooltipComponent, LegendComponent, GridComponent])

import { taskApi, analysisApi } from '@/api'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'

const router = useRouter()

const tasks = ref([])
const loading = ref(true)
const selectedTaskId = ref(null)
const dashboard = ref(null)
const report = ref(null)

onMounted(async () => {
  try {
    const { data } = await taskApi.list({ limit: 50 })
    tasks.value = data
    if (data.length > 0) {
      selectedTaskId.value = data[0].id
      await loadDashboard(data[0].id)
    }
  } finally {
    loading.value = false
  }
})

async function loadDashboard(taskId) {
  try {
    const { data } = await taskApi.summary(taskId)
    try {
      const dashResp = await analysisApi.dashboard(taskId)
      dashboard.value = dashResp.data
    } catch {
      dashboard.value = { ...data, category_distribution: data.category_breakdown || {} }
    }
    try {
      const reportResp = await analysisApi.report(taskId)
      report.value = reportResp.data
    } catch {
      report.value = null
    }
  } catch {
    dashboard.value = null
    report.value = null
  }
}

async function handleTaskChange(taskId) {
  selectedTaskId.value = taskId
  await loadDashboard(taskId)
}

const pieOption = computed(() => {
  if (!dashboard.value) return {}
  const dist = dashboard.value.category_distribution || {}
  const data = Object.entries(dist).map(([name, value]) => ({
    name: name || '未分类',
    value,
  }))
  return {
    tooltip: { trigger: 'item' },
    legend: { orient: 'vertical', left: 'left' },
    series: [{
      type: 'pie',
      radius: ['40%', '70%'],
      avoidLabelOverlap: false,
      itemStyle: { borderRadius: 4, borderColor: '#fff', borderWidth: 2 },
      label: { show: true, formatter: '{b}: {c}' },
      data: data.length > 0 ? data : [{ name: '暂无数据', value: 0 }],
    }],
  }
})

const barOption = computed(() => {
  if (!dashboard.value) return {}
  const d = dashboard.value
  return {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: ['总数', '已分类', '未识别'] },
    yAxis: { type: 'value' },
    series: [{
      type: 'bar',
      data: [
        { value: d.total_failures || 0, itemStyle: { color: '#409eff' } },
        { value: d.classified || 0, itemStyle: { color: '#67c23a' } },
        { value: d.unrecognized || 0, itemStyle: { color: '#e6a23c' } },
      ],
      itemStyle: { borderRadius: [4, 4, 0, 0] },
    }],
  }
})

const statusTag = (status) => {
  const map = {
    pending: 'info',
    parsing: 'warning',
    analyzing: 'warning',
    completed: 'success',
    failed: 'danger',
  }
  return map[status] || 'info'
}

function navigateToTask(taskId) {
  router.push(`/tasks/${taskId}`)
}
</script>

<template>
  <div class="page dashboard">
    <AppPageHeader
      title="分析看板"
      subtitle="按任务查看日志量、失败分布、分类准确率与人工审核情况"
    >
      <template #actions>
        <el-select
          v-model="selectedTaskId"
          placeholder="选择任务"
          @change="handleTaskChange"
          style="width: 320px"
          :loading="loading"
        >
          <el-option
            v-for="task in tasks"
            :key="task.id"
            :label="task.name"
            :value="task.id"
          >
            <span class="option-name">{{ task.name }}</span>
            <el-tag :type="statusTag(task.status)" size="small" style="margin-left: 8px">
              {{ task.status }}
            </el-tag>
          </el-option>
        </el-select>
      </template>
    </AppPageHeader>

    <div v-if="!selectedTaskId" class="empty-state">
      <el-empty description="暂无任务，请先创建任务" />
    </div>

    <template v-else-if="dashboard">
      <AppSection title="任务概览" hint="本任务全部日志行的统计">
        <el-row :gutter="16" class="stat-row">
          <el-col :span="6">
            <div class="stat-card">
              <div class="stat-label">总日志行数</div>
              <div class="stat-value">{{ (dashboard.total_entries || 0).toLocaleString() }}</div>
              <div class="stat-meta">所有解析到的行</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-card stat-card--err">
              <div class="stat-label">失败事件</div>
              <div class="stat-value danger">{{ (dashboard.total_failures || 0).toLocaleString() }}</div>
              <div class="stat-meta">被规则识别为失败</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-card stat-card--ok">
              <div class="stat-label">已分类</div>
              <div class="stat-value success">{{ (dashboard.classified || 0).toLocaleString() }}</div>
              <div class="stat-meta">归入已知根因</div>
            </div>
          </el-col>
          <el-col :span="6">
            <div class="stat-card stat-card--warn">
              <div class="stat-label">未识别</div>
              <div class="stat-value warning">{{ (dashboard.unrecognized || 0).toLocaleString() }}</div>
              <div class="stat-meta">需要关注</div>
            </div>
          </el-col>
        </el-row>
      </AppSection>

      <AppSection
        v-if="report"
        title="分析报告"
        hint="按测试目的维度聚合，跨任务对比"
      >
        <div class="report-grid">
          <div class="report-stat">
            <span class="report-num">{{ report.total_testsuite_files }}</span>
            <span class="report-label">测试套文件</span>
          </div>
          <div class="report-stat">
            <span class="report-num">{{ report.total_testcase_files }}</span>
            <span class="report-label">测试用例文件</span>
          </div>
          <div class="report-stat">
            <span class="report-num success">{{ report.auto_analyzed }}</span>
            <span class="report-label">自动分析</span>
            <span class="report-pct">{{ report.auto_analyzed_pct }}%</span>
          </div>
          <div class="report-stat">
            <span class="report-num primary">{{ report.human_reviewed }}</span>
            <span class="report-label">人工已审核</span>
          </div>
          <div class="report-stat">
            <span class="report-num warning">{{ report.human_overridden }}</span>
            <span class="report-label">人工已覆盖</span>
          </div>
          <div class="report-stat">
            <span class="report-num danger">{{ report.remaining_unreviewed }}</span>
            <span class="report-label">尚未审核</span>
          </div>
        </div>
      </AppSection>

      <AppSection title="失败分类分布" hint="按根因维度拆分失败事件">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-card shadow="never" class="chart-card">
              <template #header>分类占比</template>
              <VChart :option="pieOption" style="height: 320px" autoresize />
            </el-card>
          </el-col>
          <el-col :span="12">
            <el-card shadow="never" class="chart-card">
              <template #header>分类计数</template>
              <VChart :option="barOption" style="height: 320px" autoresize />
            </el-card>
          </el-col>
        </el-row>
      </AppSection>

      <AppSection
        v-if="dashboard.feedback_total > 0"
        title="反馈准确率"
        hint="基于历史人工修正回灌的样本统计"
      >
        <el-card shadow="never" class="accuracy-card">
          <div class="accuracy-display">
            <el-progress
              type="dashboard"
              :percentage="Math.round(dashboard.feedback_accuracy || 0)"
              :color="(dashboard.feedback_accuracy || 0) >= 80 ? '#67c23a' : '#e6a23c'"
            />
            <div class="accuracy-detail">
              共 {{ dashboard.feedback_total }} 条反馈，{{ dashboard.feedback_correct }} 条正确
            </div>
          </div>
        </el-card>
      </AppSection>
    </template>

    <div v-else class="empty-state">
      <el-empty description="加载看板数据失败" />
    </div>
  </div>
</template>

<style scoped>
.dashboard {
  max-width: 1400px;
}

.option-name {
  display: inline-block;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}

.empty-state {
  margin-top: 80px;
}

/* ── Stat cards ── */
.stat-row {
  margin: 0;
}
.stat-card {
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--space-xl) var(--space-lg);
  text-align: left;
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  height: 100%;
  transition: box-shadow 0.15s;
}
.stat-card:hover {
  box-shadow: var(--shadow-hover);
}
.stat-card--err   { border-left: 3px solid var(--color-error); }
.stat-card--ok    { border-left: 3px solid var(--color-success); }
.stat-card--warn  { border-left: 3px solid var(--color-warning); }

.stat-label {
  font-size: var(--text-small);
  color: var(--text-secondary);
}
.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
}
.stat-value.danger  { color: var(--color-error); }
.stat-value.success { color: var(--color-success); }
.stat-value.warning { color: var(--color-warning); }
.stat-meta {
  font-size: var(--text-tiny);
  color: var(--text-muted);
}

/* ── Report ── */
.report-grid {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: var(--space-md);
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
  padding: var(--space-lg);
}
.report-stat {
  text-align: center;
  padding: var(--space-sm);
}
.report-num {
  display: block;
  font-size: 22px;
  font-weight: 700;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.report-num.success { color: var(--color-success); }
.report-num.primary { color: var(--color-primary); }
.report-num.warning { color: var(--color-warning); }
.report-num.danger  { color: var(--color-error); }
.report-label {
  display: block;
  font-size: var(--text-small);
  color: var(--text-secondary);
  margin-top: var(--space-xs);
}
.report-pct {
  display: block;
  font-size: var(--text-tiny);
  color: var(--color-success);
  margin-top: 2px;
}

/* ── Chart & accuracy ── */
.chart-card :deep(.el-card__header) {
  padding: var(--space-md) var(--space-lg);
  font-size: var(--text-h3);
  font-weight: var(--weight-h);
}
.accuracy-card :deep(.el-card__body) {
  padding: var(--space-xl);
}
.accuracy-display {
  text-align: center;
}
.accuracy-detail {
  margin-top: var(--space-lg);
  font-size: var(--text-small);
  color: var(--text-secondary);
}
</style>
