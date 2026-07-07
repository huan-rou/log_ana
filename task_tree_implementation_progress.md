# Task Tree Grouping — Implementation Progress

本文件给**接手 v5 计划实现的下一个会话**用，详细记录：
- 已完成的工作（commit 列表、文件位置）
- 待办的下一步（按依赖顺序）
- 关键设计判断和已知坑

## 已完成

### Commit 列表（`feat/task-tree-grouping` 分支）
```
5c14ff3  docs: add task tree grouping implementation plan (v5)
8aaf7ec  feat(models): add TestTaskTree / TestTaskNode + tasks.tree_node_id
1ecf539  feat(services): task_tree JSON parser + unit tests
7a7b5ac  feat(services): S3 probe + 14 unit tests
859cb6f  feat(api): v5 mapping endpoints for JSON tree (6 endpoints + 14 tests)
9a99800  feat(api): v5 analysis endpoints + suite LogFile matching (11 tests)
<NEW>     docs: mark Analysis API step complete
<NEW>     feat(core): v5 logging setup + key path logger + 26 unit tests
```

### 已落地的代码

| 路径 | 状态 | 说明 |
|---|---|---|
| `backend/app/models/task_tree.py` | ✅ 新建 | `TestTaskTree` / `TestTaskNode` ORM |
| `backend/app/models/__init__.py` | ✅ 改动 | 导出新 model |
| `backend/app/models/task.py` | ✅ 改动 | `Task` 加 `tree_node_id` 字段 |
| `backend/app/database.py` | ✅ 改动 | `_apply_manual_migrations()` SQLite ALTER 兜底 |
| `backend/app/services/task_tree.py` | ✅ 新建 | `parse_task_tree` / `compute_name_key` / `check_cross_round_id_conflict` |
| `backend/tests/test_task_tree.py` | ✅ 新建 | 29 个单测，**全过** |
| `backend/tests/test_task_tree_s3.py` | ✅ 新建 | 14 个 S3 探测单测，**全过** |
| `backend/tests/__init__.py` | ✅ 新建 | 测试包初始化 |
| `backend/conftest.py` | ✅ 新建 | pytest 全局配置（用内存 SQLite） |
| `backend/app/services/task_tree_s3.py` | ✅ 新建 | S3 探测：`probe_leaf_in_s3` / `probe_leaves_in_s3_batch` |
| `backend/app/api/mapping.py` | ✅ 改动 | 8 个 v5 端点（preview/append/list/get/delete/create_tasks/auto-fetch/note）|
| `backend/app/models/task.py` | ✅ 改动 | **bug 修复**：Task.tree_node_id 之前误加在 LogFile 类，已移到 Task 类 |
| `backend/app/services/task_tree.py` | ✅ 改动 | `check_cross_round_id_conflict` 改为 async（DB 查询需要 await）|
| `backend/app/services/task_tree_aggregate.py` | ✅ 新建 | 聚合算法：`aggregate_by_name_key` / `aggregate_testcases_by_name_key` / `list_testcases_in_round` |
| `backend/app/services/summary_report.py` | ✅ 改动 | 新增 `find_suite_logfile` 5 步匹配 + `build_suite_response` |
| `backend/app/api/analysis.py` | ✅ 改动 | 5 个 v5 端点（trees/tree/aggregate/aggregate/testcases/testcases）|
| `backend/tests/test_mapping_api.py` | ✅ 新建 | 14 个 mapping 集成测试 |
| `backend/tests/test_analysis_api.py` | ✅ 新建 | 11 个 analysis 集成测试 |
| `backend/pyproject.toml` | ✅ 改动 | `[tool.pytest.ini_options] asyncio_mode = "auto"` |
| `backend/app/core/logging_setup.py` | ✅ 新建 | `setup_logging(enabled, log_file, *, force)` |
| `backend/app/config.py` | ✅ 改动 | 加 `app_debug_logging: bool = True` + `log_file: Path` |
| `backend/app/main.py` | ✅ 改动 | lifespan 启动时调 `setup_logging(settings.app_debug_logging, settings.log_file)` |
| `backend/app/services/summary_report.py` | ✅ 改动 | 关键路径加 DEBUG/WARNING logger（v5 第 9.4 节）|
| `backend/app/api/analysis.py` | ✅ 改动 | `list_analyzed_files` 加响应组装 INFO logger |
| `backend/tests/test_logging_setup.py` | ✅ 新建 | 17 个 logging_setup 单测（**全过**）|
| `backend/tests/test_logger_paths.py` | ✅ 新建 | 9 个关键路径日志存在性单测（**全过**）|

### 关键 API 已就绪

```python
# backend/app/services/task_tree.py
parse_task_tree(raw_json: str) -> dict
# 返回 { tree, nodes, leaves, extra_fields_seen }；任何错误抛 ValueError

compute_name_key(name: str) -> str
# 规则：name.rsplit('_', 1)[0]
# 已知误伤：BGP0_reRun6458 → BGP0（按 v3.2 计划原意接受）

check_cross_round_id_conflict(db, version_id, new_leaf_ids) -> list[dict]
# 返回 [{ node_id, conflicting_round, conflicting_tree_node_id }] 冲突列表；空 = 无冲突

# backend/app/core/logging_setup.py
setup_logging(enabled: bool, log_file: Optional[Path] = None, *, force: bool = False) -> None
# enabled=True:  root=INFO, app.*=DEBUG；输出 stdout + 可选 log_file
# enabled=False: root=WARNING, app.*=WARNING
# 幂等：重复调用不重复装 handler
# 与 audit_logger 互不干扰

teardown_logging() -> None
# 仅测试用：清掉 setup_logging 装的 handler
```

### 单测结果
```bash
$ D:\log_analyzer\backend\.venv\Scripts\python.exe -m pytest tests/
======================= 94 passed, 43 warnings in 9.01s ======================
# 68 解析器/S3/mapping/analysis + 17 logging_setup + 9 logger_paths = 94
```

## 待办（按依赖顺序）

### 第 4 步 — S3 探测 ✅
- 路径：`backend/app/services/task_tree_s3.py`（新建）
- 作用：探测 `s3://<bucket>/<prefix>/<version_name>/<leaf_id>/` 下是否有任意子条目
- 接口：
  ```python
  async def probe_leaf_in_s3(version_name: str, leaf_id: str, *, timeout: float = 5.0) -> bool
  ```
- 实现：调 `provider_manager.list_dir("s3", f"{version_name}/{leaf_id}/")`，返回非空算匹配
- 并发探测：用 `asyncio.gather` 并发跑多个 leaf
- 关键 logger：`logger.debug("[s3.probe] version=%s leaf=%s has_data=%s", ...)`

### 第 5 步 — Mapping API ✅
- 路径：`backend/app/api/mapping.py`（现有文件加端点）
- 现有 mapping.py 有 `TestVersion` / `TestPurpose` / `TaskReference` 管理端点；v5 在同一文件加 JSON 树管理端点
- 新增端点：
  - `POST /api/mapping/versions/{version_id}/tree?mode=preview` — 预览（不写库）
  - `POST /api/mapping/versions/{version_id}/tree?mode=append` — 追加（写库 + 跨 round 冲突检查）→ 实际路由：`/tree/append`
  - `GET /api/mapping/versions/{version_id}/trees` — 列所有轮次
  - `GET /api/mapping/versions/{version_id}/trees/{round_number}` — 拉取指定轮次
  - `DELETE /api/mapping/versions/{version_id}/trees/{round_number}` — 删除
  - `POST /api/mapping/versions/{version_id}/trees/{round_number}/create_tasks` — 批量建任务
  - `POST /api/mapping/versions/{version_id}/tree/auto-fetch` — 占位（503）
  - `PUT /api/mapping/versions/{version_id}/trees/{round_number}/note` — 改备注
- round 分配：事务内 `SELECT MAX(round_number) WHERE version_id=?` + 1；UNIQUE 约束兜底
- 删除 round：先 `UPDATE tasks SET tree_node_id=NULL WHERE tree_node_id IN (...)` 再删节点和树

### 第 6 步 — Analysis API ✅
- 路径：`backend/app/api/analysis.py`（现有文件加端点）
- 现有端点：`POST /:task_id/run`、`GET /:task_id/files`、`GET /files/:file_id`、`GET /:task_id/results` 等
- 新增端点：
  - `GET /api/analysis/{task_id}/trees` — 列所有轮次
  - `GET /api/analysis/{task_id}/tree?round={n}` — 拉取指定轮次的树
  - `GET /api/analysis/{task_id}/aggregate?tree_node_id=...` — 节点元信息（含 missing_rounds）
  - `GET /api/analysis/{task_id}/aggregate/testcases?tree_node_id=...` — 跨 round 聚合的 TestCase 行
  - `GET /api/analysis/{task_id}/testcases?round_filter={n}&tree_node_id=...` — 单 round 的 TestCase 行
  - `GET /api/analysis/{task_id}/files` 扩展：支持 `round_filter` + `tree_node_id`
- 关键算法：
  - `aggregate_by_name_key`（v3.2 设计 + name_key 重写后）：跨 round 按 name_key 聚合
  - `aggregate_testcases_by_name_key`：按 `LogFile.testcase_name` 分组聚合（**不是 TestCase 表**）
  - `list_testcases_in_round`：单 round 的 TestCase 行（按 LogFile.testcase_name 分组）
  - **`find_suite_logfile`**（v4 新增）：5 步启发式匹配 suite.id/desc/name 与 testsuite LogFile.name
- 复用现有 `summary_for_file`（`backend/app/services/summary_report.py`）返回 `summary_report` 字段
- **suite 信息从 summary_report.yaml 拿**——`case_rec["suite"]` 已有父 suite 引用

### 第 7 步 — 日志设施 ✅
- 路径：`backend/app/core/logging_setup.py`（新建）
- 改动：`backend/app/config.py` 加 `app_debug_logging: bool = True` 和 `log_file: Path`
- 改动：`backend/app/main.py` lifespan 启动时调 `setup_logging(settings.app_debug_logging, settings.log_file)`
- **与现有 audit_logger 协作**：
  - audit_logger（`app/core/audit_logger.py`）保持：分析流水线结构化审计（按 task_id 维度，JSONL）
  - 新 logger：覆盖 JSON 树、聚合、S3 探测、API 响应等路径（按时间维度，文本）
- enabled=True → root=INFO, app.*=DEBUG
- enabled=False → 全 WARNING
- 格式：`%(asctime)s [%(levelname)s] %(name)s: %(message)s`
- 输出：stdout + 可选 log_file
- 关键路径日志清单见 v5 计划第 9.4 节（已全部覆盖）

### 第 8 步 — 前端 API 客户端
- 路径：`frontend/src/api/index.js`
- 新增方法：
  ```js
  mapping.previewTree(versionId, jsonText)
  mapping.appendTree(versionId, jsonText, note)
  mapping.updateNote(versionId, round, note)
  mapping.listTrees(versionId)
  mapping.getTree(versionId, round)
  mapping.deleteTree(versionId, round)
  mapping.createTasksFromTree(versionId, round)
  mapping.autoFetchTree(versionId, executionId)
  analysis.getTaskTrees(taskId)
  analysis.getTaskTree(taskId, round)
  analysis.getAggregate(taskId, treeNodeId)
  analysis.getAggregateTestcases(taskId, treeNodeId)
  analysis.getTestcases(taskId, { tree_node_id, round_filter })
  analysis.files(taskId, { ..., tree_node_id, round_filter })  // 扩展
  ```
- **保持 `analysis.files` 现有参数向后兼容**（v3.1 已有 `summary_result` 参数）

### 第 9 步 — MappingManager.vue
- 路径：`frontend/src/views/MappingManager.vue`
- 当前：版本列表 + 目的列表 + 轮次发现
- 改造：加"JSON 树（按轮次管理）"区块
  - 顶部摘要：所有轮次列表（每行：轮次 N + 根名 + 节点数 + 叶子数 + 备注 + 创建时间 + 操作按钮）
  - "追加执行轮次" 主按钮：弹窗
    - 备注（必填）
    - JSON 粘贴框
    - 解析预览（实时）：树形 + 叶子数 + S3 匹配 + 跨 round 冲突检查
    - 占位按钮 "按执行 ID 自动获取"（503 + "即将推出"提示）
    - 确认追加并创建任务按钮
  - 已有轮次操作：[查看] [改备注] [按此次批量建任务] [删除]
- TestPurpose 区域保留为 legacy，顶部加提示

### 第 10 步 — TaskDetail.vue
- 路径：`frontend/src/views/TaskDetail.vue`
- 改造：在 `分析详情` Tab 内加 "单轮次" / "整体" 内嵌 Tab
- 单轮次 Tab：
  - 顶部轮次选择器（默认 = 当前 Task 所在 round）
  - 左树右表布局
  - 右表 = TestCase 行（按 LogFile.testcase_name 分组），每行带 suite 信息
- 整体 Tab：
  - 顶部缺失告警条（"X 个节点在 Y 个 round 存在日志缺失"）
  - 左树 = round=1 树 + 节点元信息（已执行 N 次 / 最新轮次 M / 缺失告警）
  - 右表 = 跨 round 聚合的 TestCase 行（含 name_key 聚合维度）
- 现有 `分析结果 / 原始日志 / 日志浏览 / 失败事件` Tab 保留；只改造"分析详情"
- 老任务兼容：`Task.tree_node_id IS NULL` 时显示"未关联 JSON 树"提示

### 第 11 步 — 集成测试
- 路径：`backend/tests/test_task_tree_api.py`（新建）
- 覆盖：
  - POST /tree?mode=preview 不写库
  - POST /tree?mode=append 跨 round 冲突回滚
  - POST /tree/auto-fetch 503
  - PUT /trees/{round}/note
  - GET /aggregate?tree_node_id=... 返回 execution_count / latest_round / missing_rounds
  - GET /aggregate/testcases?tree_node_id=... 返回 TestCase 维度数据
  - GET /testcases?tree_node_id=...&round_filter=N 返回单 round 的 TestCase 行
- 前端手动验证：见 v5 计划第 8.3 节

## 关键设计判断（避免重复踩坑）

### 1. name_key 规则
- **当前实现**：`name.rsplit('_', 1)[0]`
- **已知误伤**：`BGP0_reRun6458` → `BGP0`
- **接受这个误伤**——v3.2 计划原意如此
- 单测 `test_known_misbehavior_bgp0` 显式标注，未来可加"测试系统后缀白名单"改进

### 2. TestCase 行 = LogFile 行
- **HTML 报告里的"测试用例"实际是落到 `LogFile` 上的**（`file_type='testcase'`, `testcase_name=<方法名>`）
- `TestCase` 表基本为空
- 所以"TestCase 行"的真实数据源 = `LogFile.testcase_name` 字段
- **不查 `TestCase` 表**——按 `LogFile.testcase_name` 分组聚合

### 3. suite 关联源 = summary_report.yaml
- 用户确认"正常日志包一定提供 summary_report"
- `summary_report.py:117-128` 已构建 `case_rec["suite"]`
- **不**给 `LogFile` 加 `suite_name` 字段
- 关联在 API 响应时动态计算：`find_suite_logfile` 5 步启发式匹配
- 匹配算法要点：按 suite.id/desc/name 的 stem 与 LogFile.name 的 stem 比对

### 4. audit_logger 与新 logger 协作
- **audit_logger 保持**（分析流水线结构化审计，按 task_id 维度，JSONL）
- **新 logger 覆盖**：JSON 树、聚合、S3 探测、API 响应等路径（按时间维度，文本）
- **不重复**：分析流水线已有 audit_logger 的路径不再加 logger
- **setup_logging 幂等**：handler 带 `_app_logging_setup_done` 标记，重复调用不重复装；teardown 只清自己装的
- **测试隔离**：`conftest.py` 设 `LA_APP_DEBUG_LOGGING=false` → 新加 logger.info/debug 不会污染测试输出

### 5. TestSuite LogFile 匹配失败的处理
- 当前 S3 目录 `artifacts/testsuite/` 下文件名（如 `testsuename.html`）可能跟 suite.id 不一致
- 5 步启发式匹配可能失败
- **降级策略**：`suite.logfile_id=null`，UI 显示 suite 名字信息但链接缺失
- **`find_suite_logfile` 找不到时记 WARNING**（含 suite_id / suite_desc / candidate 数），便于排查
- `rustfs-folder-design.md` 可加一条命名建议：testsuite HTML 文件名用 `TS_id.html` 格式

## 启动时环境

```bash
# 跑全部单测
cd D:\log_analyzer\backend
.venv\Scripts\python.exe -m pytest tests/

# 跑特定模块
.venv\Scripts\python.exe -m pytest tests/test_logging_setup.py -v
.venv\Scripts\python.exe -m pytest tests/test_logger_paths.py -v

# 启动后端（默认开 logging 到 stdout；通过 LA_LOG_FILE 改写到文件）
.venv\Scripts\python.exe -m uvicorn app.main:app --reload
# 发布：关 debug logging
LA_APP_DEBUG_LOGGING=false .venv\Scripts\python.exe -m uvicorn app.main:app

# 启动前端
cd D:\log_analyzer\frontend
npm run dev
```

## 当前进度

- ✅ 数据模型（建表 + ALTER 兜底）
- ✅ 解析器（29 个单测全过）
- ✅ S3 探测（14 个单测全过；`probe_leaf_in_s3` / `probe_leaves_in_s3_batch`）
- ✅ Mapping API（8 个端点 + 14 个集成测试全过）
- ✅ Analysis API（5 个端点 + suite 匹配 + 11 个集成测试全过）
- ✅ 日志设施（`logging_setup.py` + `app_debug_logging` + 17 单测 + 9 关键路径验证）—— **第 7 步完成**
- ⏳ 前端 API 客户端 —— **下一步**
- ⏳ MappingManager.vue
- ⏳ TaskDetail.vue
- ⏳ 集成测试
