<script setup>
import { ElMessage } from 'element-plus'
import AppPageHeader from '@/components/layout/AppPageHeader.vue'
import AppSection from '@/components/layout/AppSection.vue'
import PurposeExecutionResults from '@/components/PurposeExecutionResults.vue'
import { mockPurposeExecutionData } from '@/api/purpose-execution.fixtures'

function showMockAction(kind, id) {
  ElMessage.info(`Mock ${kind}：${id}`)
}
</script>

<template>
  <div class="page page--scroll purpose-execution-mock">
    <AppPageHeader
      title="交换机回归测试"
      subtitle="R45_B2B 稳定性验证，展示同一测试目的下三轮执行的最新分析结果"
    >
      <template #meta>
        <span class="meta-item">目的：版本发布前回归</span>
        <span class="meta-item">外部任务：<code>EXT-20260720-0842</code></span>
        <span class="meta-item">完成：2026-07-20 11:16:08</span>
      </template>
      <template #actions>
        <el-tag type="warning" effect="light">完成但有告警</el-tag>
      </template>
    </AppPageHeader>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      title="UI Mock 模式"
      description="当前页面使用前端样例数据，不访问后端。筛选、维度切换和用例历史展开均可交互。"
    />

    <el-alert
      type="warning"
      :closable="false"
      show-icon
      title="2 项数据质量告警"
      description="第 2 轮大规格路由任务块包含多个测试套；第 1 轮有 1 个用例返回未识别状态 infra_error。"
    />

    <AppSection title="执行概览" hint="按 case_id 取最后一次执行结果">
      <div class="metric-strip" aria-label="执行结果概览">
        <div class="metric-item">
          <span>执行轮次</span>
          <strong>3</strong>
        </div>
        <div class="metric-item">
          <span>测试用例</span>
          <strong>7</strong>
        </div>
        <div class="metric-item is-success">
          <span>成功</span>
          <strong>4</strong>
        </div>
        <div class="metric-item is-danger">
          <span>失败</span>
          <strong>1</strong>
        </div>
        <div class="metric-item is-warning">
          <span>阻塞</span>
          <strong>1</strong>
        </div>
        <div class="metric-item is-muted">
          <span>未知</span>
          <strong>1</strong>
        </div>
      </div>
    </AppSection>

    <AppSection title="分析结果" hint="测试套逐任务块展示，用例按编号折叠">
      <PurposeExecutionResults
        execution-id="mock-purpose-execution"
        :mock-data="mockPurposeExecutionData"
        @open-log="(id) => showMockAction('日志', id)"
        @open-review="(id) => showMockAction('审核', id)"
      />
    </AppSection>
  </div>
</template>

<style scoped>
.purpose-execution-mock {
  max-width: 1680px;
  margin: 0 auto;
}

.meta-item code {
  font-family: var(--font-mono);
  color: var(--text-primary);
  background: var(--bg-input);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 1px 4px;
}

.metric-strip {
  display: grid;
  grid-template-columns: repeat(6, minmax(92px, 1fr));
  background: var(--bg-panel);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-md);
}

.metric-item {
  min-width: 0;
  padding: 12px 14px;
  border-right: 1px solid var(--border-light);
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-md);
}

.metric-item:last-child {
  border-right: 0;
}

.metric-item span {
  color: var(--text-secondary);
  font-size: var(--text-small);
  white-space: nowrap;
}

.metric-item strong {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-size: 20px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.metric-item.is-success strong { color: var(--color-success); }
.metric-item.is-danger strong { color: var(--color-error); }
.metric-item.is-warning strong { color: var(--color-warning); }
.metric-item.is-muted strong { color: var(--text-secondary); }

@media (max-width: 1100px) {
  .metric-strip { grid-template-columns: repeat(3, 1fr); }
  .metric-item:nth-child(3) { border-right: 0; }
  .metric-item:nth-child(-n + 3) { border-bottom: 1px solid var(--border-light); }
}

@media (max-width: 680px) {
  .metric-strip { grid-template-columns: repeat(2, 1fr); }
  .metric-item:nth-child(3) { border-right: 1px solid var(--border-light); }
  .metric-item:nth-child(even) { border-right: 0; }
  .metric-item:nth-child(-n + 4) { border-bottom: 1px solid var(--border-light); }
}
</style>
