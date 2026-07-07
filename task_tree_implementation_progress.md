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
0cf1cff  docs: mark Analysis API step complete
018057e  feat(core): v5 logging setup + key path logger + 26 unit tests
f32dca4  feat(frontend): v5 API client methods + smoke test (72 assertions)
e988a35  feat(frontend): v5 MappingManager — JSON 树按轮次管理主区块
<NEW>     feat(frontend): v5 TaskDetail — JSON 树视图（单轮次/整体）
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

### 第 8 步 — 前端 API 客户端 ✅
- 路径：`frontend/src/api/index.js`
- 新增方法（mappingApi 8 个 + analysisApi 5 个）：
  ```js
  mapping.previewTree(versionId, jsonText)             // POST /tree?mode=preview, 120s timeout
  mapping.appendTree(versionId, jsonText, note)        // POST /tree/append?note=, 60s timeout
  mapping.updateNote(versionId, round, note)           // PUT /trees/{r}/note
  mapping.listTrees(versionId)                         // GET /trees
  mapping.getTree(versionId, round, {includeS3Probe})  // GET /trees/{r}?include_s3_probe=
  mapping.deleteTree(versionId, round)                 // DELETE /trees/{r}
  mapping.createTasksFromTree(versionId, round)        // POST /trees/{r}/create_tasks, 120s
  mapping.autoFetchTree(versionId, executionId)        // POST /tree/auto-fetch?execution_id=

  analysis.getTaskTrees(taskId)                        // GET /analysis/{t}/trees
  analysis.getTaskTree(taskId, round=null)             // GET /analysis/{t}/tree (round 缺省)
  analysis.getAggregate(taskId, treeNodeId)            // GET /analysis/{t}/aggregate
  analysis.getAggregateTestcases(taskId, treeNodeId)   // GET /analysis/{t}/aggregate/testcases
  analysis.getTestcases(taskId, {treeNodeId})          // GET /analysis/{t}/testcases
  ```
- **`analysis.files` 向后兼容**：保留 v3.1 现有参数（review_status / file_type / category_id / is_fallback / summary_result），新增 `treeNodeId` 和 `roundFilter` 两个 camelCase 入参，内部映射成 snake_case query
- **input validation** 在 API 边界做：previewTree/appendTree/updateNote 拒绝空 jsonText/空 note；getAggregate/getAggregateTestcases 拒绝空 treeNodeId
- **timeout 分级**：previewTree 120s（8 并发 S3 探测）/ appendTree 60s / createTasksFromTree 120s / getTree 60s（开 S3 时）/ 默认 30s
- **`frontend/test-api-v5.cjs`**：esbuild bundle + axios mock 烟雾测试，**72 个断言全过**（28 shape + 44 behavioral）
- 全部 94 backend 单测 + 72 frontend 烟雾测试 = **166 通过**

### 第 9 步 — MappingManager.vue ✅
- 路径：`frontend/src/views/MappingManager.vue`（662 行新增）
- **改造**：右侧主区域从单 section（TestPurpose）变成双 section
  - **JSON 树（按轮次管理）**（primary，置顶）：轮次表 + 追加/查看/备注/建任务/删除
  - **测试目的**（legacy，下方保留）：顶部加 `<el-alert>` 推荐改用上方 JSON 树
- **轮次表**（7 列 + 操作）：轮次 #N / 根名 / 根节点 ID / 节点·叶子 / 备注 / 创建时间 / 操作
- **追加执行轮次弹窗**（780px）：
  - 备注（必填，200 字限）
  - JSON 粘贴框（10 行，等宽字体）
  - 解析预览按钮 → 调用 `mappingApi.previewTree`，展示节点·叶子·冲突·S3 匹配 4 个 tag + 折叠详情
  - 占位按钮「按执行 ID 自动获取」（走 `autoFetchTree`，后端返 503 兜底提示）
  - 「仅追加」+「追加并创建任务」两个按钮（冲突时禁用）
- **查看树弹窗**：节点数·叶子数·S3 探测开关 + 内嵌 TaskTreeNode 渲染树
- **改备注弹窗**：纯文本（200 字限）
- **批量建任务结果弹窗**：3 列统计（新建/关联/跳过）+ 跳过叶子清单 + 新建 Task 表
- **每行操作**：查看 / 备注 / 建任务 / 删除（确认对话框显示影响 task 数 + 警告不可恢复）
- **内联 TaskTreeNode 组件**：脚本内定义，支持递归自引用，叶子节点蓝色 + 可选 S3 匹配 tag
- **TestPurpose 区域保留**：所有原功能不动；新增 `<el-alert type="info">` 推荐用户改用上方 JSON 树
- **切换 version**：同时清空轮次列表 + 重新加载（`handleVersionChange` 加 `loadTrees()`）
- **响应式空态**：轮次表 empty-text 引导用户「点击右上角追加执行轮次开始」
- vite build 验证：`MappingManager-BJ087RPb.js` + `MappingManager-DqVB3HnU.css` 输出正常
- 样式 token 全部走 CSS 变量（`--space-*` / `--text-*` / `--color-*` / `--bg-*`），与全站统一

### 第 10 步 — TaskDetail.vue ✅
- 路径：`frontend/src/views/TaskDetail.vue`（+736 行）
- **改造**：在「分析详情」AppSection 顶部新增顶级 Tab「JSON 树视图」，含 2 个内嵌 Tab [单轮次 / 整体]
- **现有 4 个 Tab 完全不动**（分析结果 / 原始日志 / 日志浏览 / 失败事件）
- **老任务兼容**：`task.tree_node_id IS NULL` 时显示空态 + 「前往任务映射管理」按钮
- **新顶级 Tab：JSON 树视图**
  - 单轮次 Tab：
    - 顶部：轮次选择器（默认 = task 所在 round，通过 `getTaskTree(taskId, null)` 让后端推）+ 节点/叶子/备注 tag
    - 左：TaskTreeNodeView 递归渲染，左树节点可点击 highlight
    - 右：当前 task 的 TestCase 行表（失败数 / 日志文件 / 审核状态 / 日志·审核操作）
  - 整体 Tab：
    - 顶部缺失告警条：`X 个轮次存在日志缺失`（执行 N 次 / 最新轮次 M / 缺失列表）
    - 工具栏：聚合基准 = Round #1
    - 左：Round #1 树（带聚合元信息 tag：执行 N/M + 缺 X/Y/Z），点击叶子节点触发聚合
    - 右：选中节点的 4 列统计（已执行次数 / 最新轮次 / 最新轮日志数 / 缺失轮次数）+ 跨 round 聚合 TestCase 行表（执行次数 / 已执行轮次 chips / 缺失轮次 chips / 最新轮次 / 审核状态 / 最新日志跳转）
- **新增组件 TaskTreeNodeView**（脚本内 inline plain object）：递归自引用，支持选中态 + 聚合 tag badge
- **API 集成**：9 个 `analysisApi.*` 调用（getTaskTrees / getTaskTree / getTestcases / getAggregate / getAggregateTestcases）
- **响应式联动**：`watch(() => task.value?.tree_node_id)` — task 数据刷新时若在 tree tab 自动重载
- **Tab 切换缓存**：`treeViewLoaded` 标记首次加载后保留数据，重复切回不重拉
- **grid 布局**：左树 32% / 右表 68%，`min-height: 540px`，`max-height: 500px` 表格滚动
- **样式 token 统一**：全部走 `--space-*` / `--text-*` / `--color-*` / `--bg-*` / `--radius-*`，与全站一致
- **selected 态**：选中节点蓝色背景 + 白字 + 反色 tag
- **验证**：vite build EXIT=0；backend 94 测试仍全过；frontend API 72 断言仍全过

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
- ✅ 日志设施（`logging_setup.py` + `app_debug_logging` + 17 单测 + 9 关键路径验证）
- ✅ 前端 API 客户端（mappingApi +8 / analysisApi +5 + analysis.files 扩展 + 72 烟雾断言）
- ✅ MappingManager.vue（轮次表 + 4 个新弹窗 + 内联 TaskTreeNode）
- ✅ TaskDetail.vue（JSON 树视图 Tab + 单轮次/整体 内嵌 Tab + 老任务空态 + 内联 TaskTreeNodeView）—— **第 10 步完成**
- ⏳ 集成测试 —— **下一步**
