// Purpose execution UI mock fixtures.
// This data intentionally covers retries, warnings, blocked cases, unknown
// producer states, manual review, missing logs and same-round duplicates.

export const mockPurposeSuites = [
  {
    execution_id: 'mock-exec-1', task_id: 'mock-task-1', round_number: 1,
    feature: '基础转发', source_task_id: '3978425510246819840', node_id: 'node-01',
    task_block_id: 'boot-smoke-001', block_status: 'ready', anomaly: null,
    suite_id: 'SW_BASIC_FORWARD', suite_name: '启动与基础通信', suite_result: 'failed',
    suite_normalized_status: 'failed', success: 18, failed: 1, blocked: 0, unknown: 0,
    total: 19, suite_blocked: false, environment: null,
    logs: [
      { id: 'mock-log-suite-1', name: 'basic_forward_suite.html', file_type: 'testsuite' },
      { id: 'mock-log-case-1', name: 'TC_BOOT_001.html', file_type: 'testcase' },
    ],
  },
  {
    execution_id: 'mock-exec-1', task_id: 'mock-task-1', round_number: 1,
    feature: 'VLAN 转发', source_task_id: '3978425510246819902', node_id: 'node-03',
    task_block_id: 'vlan-forward-001', block_status: 'ready', anomaly: '1 个用例包含未知状态',
    suite_id: 'SW_VLAN_FORWARD', suite_name: 'VLAN 二三层转发', suite_result: 'failed',
    suite_normalized_status: 'failed', success: 24, failed: 2, blocked: 0, unknown: 1,
    total: 27, suite_blocked: false, environment: null,
    logs: [
      { id: 'mock-log-suite-2', name: 'vlan_forward_suite.html', file_type: 'testsuite' },
      { id: 'mock-log-case-2', name: 'TC_VLAN_027.html', file_type: 'testcase' },
    ],
  },
  {
    execution_id: 'mock-exec-1', task_id: 'mock-task-1', round_number: 1,
    feature: '堆叠组网', source_task_id: '3978425510246820118', node_id: 'node-07',
    task_block_id: 'stack-recovery-001', block_status: 'ready', anomaly: null,
    suite_id: 'SW_STACK_RECOVERY', suite_name: '堆叠故障恢复', suite_result: 'blocked',
    suite_normalized_status: 'blocked', success: 0, failed: 0, blocked: 8, unknown: 0,
    total: 8, suite_blocked: true, environment: null, logs: [],
  },
  {
    execution_id: 'mock-exec-2', task_id: 'mock-task-2', round_number: 2,
    feature: '基础转发', source_task_id: '3978516097834578120', node_id: 'node-02',
    task_block_id: 'boot-smoke-003', block_status: 'ready', anomaly: null,
    suite_id: 'SW_BASIC_FORWARD', suite_name: '启动与基础通信', suite_result: 'success',
    suite_normalized_status: 'success', success: 20, failed: 0, blocked: 0, unknown: 0,
    total: 20, suite_blocked: false, environment: null,
    logs: [{ id: 'mock-log-suite-3', name: 'basic_forward_suite_r2.html', file_type: 'testsuite' }],
  },
  {
    execution_id: 'mock-exec-2', task_id: 'mock-task-2', round_number: 2,
    feature: 'VLAN 转发', source_task_id: '3978516097834578294', node_id: 'node-04',
    task_block_id: 'vlan-forward-004', block_status: 'ready', anomaly: null,
    suite_id: 'SW_VLAN_FORWARD', suite_name: 'VLAN 二三层转发', suite_result: 'failed',
    suite_normalized_status: 'failed', success: 26, failed: 1, blocked: 0, unknown: 0,
    total: 27, suite_blocked: false, environment: null,
    logs: [{ id: 'mock-log-case-4', name: 'TC_VLAN_027_r2.html', file_type: 'testcase' }],
  },
  {
    execution_id: 'mock-exec-2', task_id: 'mock-task-2', round_number: 2,
    feature: '大规格路由', source_task_id: '3978516097834578461', node_id: 'node-06',
    task_block_id: 'route-scale-002', block_status: 'multiple_suites',
    anomaly: '每个任务块必须且只能包含一个 testsuite，实际为 2',
    suite_id: null, suite_name: null, suite_result: null, suite_normalized_status: null,
    success: 0, failed: 0, blocked: 0, unknown: 0, total: 0, suite_blocked: false,
    environment: null,
    logs: [{ id: 'mock-log-unmatched', name: 'route_scale_unmatched.html', file_type: 'testsuite' }],
  },
  {
    execution_id: 'mock-exec-3', task_id: 'mock-task-3', round_number: 3,
    feature: 'VLAN 转发', source_task_id: '3978643154019021764', node_id: 'node-02',
    task_block_id: 'vlan-forward-007', block_status: 'ready', anomaly: null,
    suite_id: 'SW_VLAN_FORWARD', suite_name: 'VLAN 二三层转发', suite_result: 'success',
    suite_normalized_status: 'success', success: 28, failed: 0, blocked: 0, unknown: 0,
    total: 28, suite_blocked: false, environment: null,
    logs: [{ id: 'mock-log-suite-5', name: 'vlan_forward_suite_r3.html', file_type: 'testsuite' }],
  },
]

export const mockPurposeTestcases = [
  {
    case_id: 'TC_BOOT_001', first_feature: '基础转发', last_suite: '启动与基础通信',
    execution_count: 2, last_result: 'success', last_normalized_status: 'success',
    final_root_cause: '启动时序 / 服务初始化超时', review_status: 'confirmed',
    latest_occurrence_id: 'occ-boot-2', latest_round: 2,
    latest_task_block: 'boot-smoke-003', log_file_id: 'mock-log-boot-2',
  },
  {
    case_id: 'TC_VLAN_014', first_feature: 'VLAN 转发', last_suite: 'VLAN 二三层转发',
    execution_count: 3, last_result: 'success', last_normalized_status: 'success',
    final_root_cause: '配置下发 / VLAN 接口未就绪', review_status: 'overridden',
    latest_occurrence_id: 'occ-vlan-14-3', latest_round: 3,
    latest_task_block: 'vlan-forward-007', log_file_id: 'mock-log-vlan-14-3',
  },
  {
    case_id: 'TC_VLAN_027', first_feature: 'VLAN 转发', last_suite: 'VLAN 二三层转发',
    execution_count: 3, last_result: 'success', last_normalized_status: 'success',
    final_root_cause: '转发表 / MAC 表项同步延迟', review_status: 'confirmed',
    latest_occurrence_id: 'occ-vlan-27-3', latest_round: 3,
    latest_task_block: 'vlan-forward-007', log_file_id: 'mock-log-vlan-27-3',
  },
  {
    case_id: 'TC_STACK_003', first_feature: '堆叠组网', last_suite: '堆叠故障恢复',
    execution_count: 1, last_result: 'blocked', last_normalized_status: 'blocked',
    final_root_cause: '测试套阻塞', review_status: null,
    latest_occurrence_id: 'occ-stack-1', latest_round: 1,
    latest_task_block: 'stack-recovery-001', log_file_id: null,
  },
  {
    case_id: 'TC_SCALE_042', first_feature: 'VLAN 转发', last_suite: 'VLAN 二三层转发',
    execution_count: 1, last_result: 'infra_error', last_normalized_status: 'unknown',
    final_root_cause: null, review_status: 'pending', latest_occurrence_id: 'occ-scale-1',
    latest_round: 1, latest_task_block: 'vlan-forward-001', log_file_id: 'mock-log-scale-1',
  },
  {
    case_id: 'TC_AUTH_006', first_feature: '基础转发', last_suite: '启动与基础通信',
    execution_count: 1, last_result: 'success', last_normalized_status: 'success',
    final_root_cause: null, review_status: null, latest_occurrence_id: 'occ-auth-1',
    latest_round: 2, latest_task_block: 'boot-smoke-003', log_file_id: null,
  },
  {
    case_id: 'TC_DUP_101', first_feature: 'VLAN 转发', last_suite: 'VLAN 二三层转发',
    execution_count: 2, last_result: 'failed', last_normalized_status: 'failed',
    final_root_cause: '流量校验 / 丢包超过阈值', review_status: 'pending',
    latest_occurrence_id: 'occ-dup-2', latest_round: 2,
    latest_task_block: 'vlan-forward-004', log_file_id: 'mock-log-dup-2',
  },
]

export const mockPurposeHistories = {
  TC_BOOT_001: [
    { occurrence_id: 'occ-boot-1', round_number: 1, end_time: '2026-07-18 09:42:16', feature: '基础转发', suite: '启动与基础通信', task_block_id: 'boot-smoke-001', raw_result: 'failed', normalized_status: 'failed', analysis_conclusion: '启动时序 / 服务初始化超时', review_status: 'confirmed', log_file_id: 'mock-log-boot-1' },
    { occurrence_id: 'occ-boot-2', round_number: 2, end_time: '2026-07-19 14:08:31', feature: '基础转发', suite: '启动与基础通信', task_block_id: 'boot-smoke-003', raw_result: 'success', normalized_status: 'success', analysis_conclusion: '启动时序 / 服务初始化超时', review_status: 'confirmed', log_file_id: 'mock-log-boot-2' },
  ],
  TC_VLAN_014: [
    { occurrence_id: 'occ-vlan-14-1', round_number: 1, end_time: '2026-07-18 10:16:08', feature: 'VLAN 转发', suite: 'VLAN 二三层转发', task_block_id: 'vlan-forward-001', raw_result: 'failed', normalized_status: 'failed', analysis_conclusion: '配置下发 / VLAN 接口未就绪', review_status: 'overridden', log_file_id: 'mock-log-vlan-14-1' },
    { occurrence_id: 'occ-vlan-14-2', round_number: 2, end_time: '2026-07-19 14:37:52', feature: 'VLAN 转发', suite: 'VLAN 二三层转发', task_block_id: 'vlan-forward-004', raw_result: 'success', normalized_status: 'success', analysis_conclusion: '配置下发 / VLAN 接口未就绪', review_status: 'overridden', log_file_id: 'mock-log-vlan-14-2' },
    { occurrence_id: 'occ-vlan-14-3', round_number: 3, end_time: '2026-07-20 11:05:44', feature: 'VLAN 转发', suite: 'VLAN 二三层转发', task_block_id: 'vlan-forward-007', raw_result: 'success', normalized_status: 'success', analysis_conclusion: '配置下发 / VLAN 接口未就绪', review_status: 'overridden', log_file_id: 'mock-log-vlan-14-3' },
  ],
  TC_VLAN_027: [
    { occurrence_id: 'occ-vlan-27-1', round_number: 1, end_time: '2026-07-18 10:21:54', feature: 'VLAN 转发', suite: 'VLAN 二三层转发', task_block_id: 'vlan-forward-001', raw_result: 'failed', normalized_status: 'failed', analysis_conclusion: '转发表 / MAC 表项同步延迟', review_status: 'confirmed', log_file_id: 'mock-log-vlan-27-1' },
    { occurrence_id: 'occ-vlan-27-2', round_number: 2, end_time: '2026-07-19 14:44:07', feature: 'VLAN 转发', suite: 'VLAN 二三层转发', task_block_id: 'vlan-forward-004', raw_result: 'failed', normalized_status: 'failed', analysis_conclusion: '转发表 / MAC 表项同步延迟', review_status: 'confirmed', log_file_id: 'mock-log-vlan-27-2' },
    { occurrence_id: 'occ-vlan-27-3', round_number: 3, end_time: '2026-07-20 11:12:19', feature: 'VLAN 转发', suite: 'VLAN 二三层转发', task_block_id: 'vlan-forward-007', raw_result: 'success', normalized_status: 'success', analysis_conclusion: '转发表 / MAC 表项同步延迟', review_status: 'confirmed', log_file_id: 'mock-log-vlan-27-3' },
  ],
  TC_DUP_101: [
    { occurrence_id: 'occ-dup-1', round_number: 2, end_time: '2026-07-19 14:50:02', feature: 'VLAN 转发', suite: 'VLAN 二三层转发', task_block_id: 'vlan-forward-004', raw_result: 'success', normalized_status: 'success', analysis_conclusion: null, review_status: 'pending', log_file_id: 'mock-log-dup-1' },
    { occurrence_id: 'occ-dup-2', round_number: 2, end_time: '2026-07-19 14:52:46', feature: 'VLAN 转发', suite: 'VLAN 二三层转发', task_block_id: 'vlan-forward-004', raw_result: 'failed', normalized_status: 'failed', analysis_conclusion: '流量校验 / 丢包超过阈值', review_status: 'pending', log_file_id: 'mock-log-dup-2' },
  ],
}

export const mockPurposeExecutionData = {
  suites: mockPurposeSuites,
  testcases: mockPurposeTestcases,
  histories: mockPurposeHistories,
}
