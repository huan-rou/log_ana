# UI Improvement Plan v5: 按 JSON 树分组 + 追加多轮次 + 双 Tab TestCase 行（带测试套属性）+ 数据缺失告警 + 关键步骤日志

## 背景

`S3://<bucket>/<prefix>/<package_version>/<task_id>/<node_id>/<task_block_id>/upload/`
路径中 `task_id`（即 `Task.automation_task_id`）对应测试系统的最细粒度执行单元。但在
测试运维视角下：

1. **多个最细粒度任务共同构成一个"实际测试任务"**（例如"双机热备场景 / 4 小时压测
   / 三轮回归"），而 S3 路径本身不携带这个上层概念。
2. **同一组用例可能因环境因素阻塞需要重测**：原始执行结果作废，重测时填入另一份
   JSON 任务描述，**重复执行若干次**。需要保留历史轮次，并在详情页能横向对比"同一
   用例在不同轮次"的执行情况。
3. **节点重复执行 ≠ 节点内所有用例都重复执行**：重测时可能只跑了部分用例，所以"执
   行次数"必须按**实际从任务块里识别出的用例 / LogFile 数**来算。
4. **重复执行时测试系统会在节点名称后追加随机后缀**（例如 `TC_id_1` → `TC_id_1_a8b3c`），
   严格按 name 相等做聚合会失败，需要**按前缀匹配**聚合。
5. **节点存在但 S3 上没数据 = 日志缺失**——必须告警提示用户，避免漏看。
6. **用户更关心具体用例（TestCase）信息而非单个日志文件**——详情页两个 tab 的右表都用
   "TestCase 行"（一行一个用例），而不是 LogFile 行。
7. **测试套（testsuite）不单独成行**，而是作为测试用例的**属性**——每个 TestCase 行
   展示其所属测试套（套名 / 套 ID / 套结果 / 套日志文件链接）；关联源 = `summary_report.yaml`（v4 关键决定）。
8. **1 个测试套对应 N 个测试用例**（N 通常 > 1）——每条 TestCase 行独立展示所属套信息，套在多行里重复出现。
9. **关键步骤增加日志打印**——v3/v4 引入的新关键路径（JSON 树管理、suite 关联、聚合算法、S3 探测、
   API 响应组装）目前**没有日志**，出问题时定位难。需要：
   - **默认打开**（dev / 调试阶段）
   - **发布版本关闭**（通过配置开关切换）
   - 复用现有 `audit_logger`（结构化审计）和 Python `logging`（通用日志）两套机制

为补齐这九层：
1. 引入"运行测试系统"的任务运行 id 树（一份 JSON）作为用例逻辑分组。
2. 一个 TestVersion 下**支持多棵 JSON 树**（每棵对应一次执行 = 一个"轮次"），**轮次号自动递增**。
3. **只追加、不覆盖**——追加的轮次可单独删除。
4. 任务映射配置界面提供**"追加执行轮次"专门按钮**：粘贴 JSON → 解析预览 → 输入备注 → 确认追加并触发日志分析刷新。
5. 创建任务时以该 JSON 为基准，用叶子 Id 探测 S3 路径并批量建任务。
6. 在 TaskDetail 详情页提供**两个 TestCase 维度视图**：
   - **单轮次视图**（默认）：左树 + 顶部轮次选择器 + 右表 = **当前 round 的 TestCase 行**
   - **整体视图**：左树（round=1 骨架）+ 右表 = **跨 round 聚合的 TestCase 行**（每行带执行次数 / 参与轮次 / 最新结果）
   - 两个 tab 都有数据缺失告警
7. **聚合键 = name 去掉最后一段（下划线分割）**——`TC_id_1_a8b3c` 归到 `TC_id_1`
8. JSON 节点除 `Name` / `Id` / `child_tasks` 外的其他属性**保留下来**（存 `extra` 字段）
9. 预留"按执行 ID 自动获取 JSON"的占位接口

> **重要修正（v3.3）**：经查 `backend/app/services/log_parser.py:381-396`，HTML 报告里的"测试
> 用例"实际是落到 `LogFile` 上的（`file_type='testcase'`, `testcase_name=<方法名>`），`TestCase`
> 表基本为空。所以"TestCase 行"的实际数据来源是 `LogFile.testcase_name` 字段，不是
> `TestCase` 表。本计划按此修订。
>
> **v4 关键决定（用户确认）**：正常日志包**一定提供** `metadata/summary_report.yaml`，所
> 以"测试套 ↔ 测试用例"的关联源 = `summary_report.yaml`（`testsuites[].testcases[]`）。
> `summary_report.py:117-128` 已经在 `case_rec["suite"]` 里构建了父 suite 引用，本计划
> 直接复用。`LogFile` 模型**不**加 `suite_name` 字段——关联在响应时动态计算。

> 本计划对应仓库根目录的 `example_task_result.json` / `example_task_result2.json`。

## 关键设计决策

| # | 决策 | 状态 |
|---|---|---|
| 1 | JSON 里只有**叶子节点**（`child_tasks == []` 或缺失）的 Id 对应 S3 任务编号 | ✅ |
| 2 | JSON 可以只有一层（顶层即叶子），也支持多层递归 | ✅ |
| 3 | 一个 TestVersion 下支持**多棵** JSON 树；`round_number` 自动递增 | ✅ |
| 4 | 物理上每个叶子 Id 建一条 `Task`；`Task.tree_node_id` 关联 `TestTaskNode.id` | 设计判断 |
| 5 | 同一 leaf name 在不同 round 是不同的 `TestTaskNode` 记录 | ✅ |
| 6 | **不覆盖**——只追加，追加的轮次可删除 | ✅ |
| 7 | **跨 round 冲突 Id 直接 400 报错**（不 relink），整次 append 回滚 | ✅ |
| 8 | TaskDetail 两个 TestCase 维度视图：单轮次（当前 round 的 TestCase 行） vs 整体（跨 round 聚合的 TestCase 行） | ✅ v3.3 修正 |
| 9 | 整体视图：round=1 树为骨架，其他 round 不按 round 单独展示，融合到节点 / 用例元信息 | ✅ |
| 10 | **执行次数（节点级）= 该节点对应 Task 在多少 round 下 logfile_count > 0** | ✅ |
| 11 | **执行次数（用例级）= 该 testcase_name 在多少 round 的 Task 里出现过** | ✅ v3.3 修正 |
| 12 | **聚合键 = `name.rsplit('_', 1)[0]`**——按"_"分割取前面部分作为 `name_key` | ✅ |
| 13 | 整体视图右表 = **TestCase 行**（每行一个用例 + 跨 round 执行次数） | ✅ |
| 14 | **单轮次视图右表 = 当前 round 的 TestCase 行**（与整体 tab 一致，差别在列和聚合范围） | ✅ v3.3 修正 |
| 15 | **数据缺失告警**：节点元信息 + 整体视图顶部 + 右表 TestCase 行三级告警 | ✅ |
| 16 | 追加轮次时必须输入备注 | ✅ |
| 17 | JSON 节点其他属性保存到 `test_task_nodes.extra` | ✅ |
| 18 | 预留"按执行 ID 自动获取 JSON"占位接口 | ✅ |
| 19 | 粘贴时提供解析预览 | ✅ |
| 20 | JSON 内容含中文——存储/展示全程 UTF-8 | ✅ |
| 21 | 粘贴了 JSON 之后，任务创建走 JSON 路径；未粘贴时保留 `TestPurpose` 老路径 | ✅ |
| 22 | 字段大小写不敏感解析 | 设计判断 |
| 23 | JSON 解析失败 → API 返回 400 | 设计判断 |
| 24 | S3 探测不到的叶子 → 跳过创建任务但在响应里报告 | 设计判断 |
| 25 | 创建任务时 `node_id` / `task_block_id` 默认 `*` | 设计判断 |
| 26 | **删除某轮次** 时 Task 实体保留，`tree_node_id` 置 NULL | 设计判断 |
| 27 | "追加执行轮次"按钮是唯一入口（不暴露 `mode=replace`） | ✅ |
| 28 | 路由不变：`/tasks/:id` 不变；"单轮次" / "整体" 作为 Tab 切换 | 设计判断 |
| 29 | **测试套不单独成行**，只作为 TestCase 行的属性（v4 新增） | ✅ |
| 30 | **关联源 = `summary_report.yaml`**（用户确认：正常日志包一定有 YAML）；`LogFile` 模型不加 `suite_name` 字段，关联在响应时动态计算（v4 新增） | ✅ |
| 31 | **每个 TestCase 行**都展示其所属测试套：套名 / 套 ID / 套结果 / 套结果时间 / 套日志链接（v4 新增） | ✅ |
| 32 | **测试套日志链接**：响应时动态查该 Task 下 `file_type='testsuite'` 的 LogFile，按 suite.id / desc / stem 多策略匹配；匹配不到则链接为 null | 设计判断 |
| 33 | **v5 - 关键步骤日志**默认打开，发布版本关闭（v5 新增） | ✅ |
| 34 | **v5 - 复用现有 `audit_logger`**（结构化审计 JSONL，按 task_id 维度）+ 新增**通用 `logger`**（Python `logging`，覆盖 JSON 树/聚合/S3 探测/API 响应组装等路径） | 设计判断 |
| 35 | **v5 - 新增 `settings.app_debug_logging: bool = True`**，发布时设 `LA_APP_DEBUG_LOGGING=false` 关闭所有新加的 INFO/DEBUG 级日志 | 设计判断 |
| 36 | **v5 - 统一 logging 格式**：`%(asctime)s [%(levelname)s] %(name)s: %(message)s`；输出到 stdout（dev）+ 文件（prod） | 设计判断 |
| 37 | **v5 - 日志级别策略**：INFO 关键节点开始/结束；DEBUG 细节数据；WARNING 异常/缺失；ERROR 失败/异常 | 设计判断 |

---

## 1. JSON 文件格式

### 1.1 输入约束
- 顶层必须是一个对象：`{ "Name": ..., "Id": ..., "child_tasks": [...], ... }`
- 解析逻辑只依赖三个字段：`Name`、`Id`、`child_tasks`
- 其他字段原样存到 `test_task_nodes.extra`（JSON 字符串）
- 字段名**大小写不敏感**
- 不限定层数
- Id 统一规范为字符串存储
- 中文全程 UTF-8

### 1.2 叶子识别
- `child_tasks` 为 `[]` / `null` / 缺失 → 该节点为叶子
- 该节点的 `Id` 视作一个 S3 任务编号

### 1.3 name_key 提取（v3.2 新增）
- 规则：`name_key = name.rsplit('_', 1)[0]`（按最后一个 `_` 分割，取前面部分）
- 例：
  - `TC_id_1` → `TC_id_1`（无 `_`，整体保留）
  - `TC_id_1_a8b3c` → `TC_id_1`
  - `统计分析__2` → `统计分析_`（保留前面 `统计分析_` 段）
  - `统计分析__2_x9y2z` → `统计分析__2`
- 没有 `_` 时 name_key == name
- 解析时**同时存** `name` 和 `name_key` 到 `TestTaskNode`

### 1.4 解析错误处理
- 顶层不是对象 → 400
- 节点缺 `Id` → 400
- `child_tasks` 存在但不是数组 → 400
- 同一棵树内 Id 重复 → 400
- 跨 round 冲突 Id → 400 + 整次 append 回滚

### 1.5 解析产出
- 节点展平列表（含 name / name_key / node_id / path / depth / is_leaf / parent_id / extra）
- 树形结构
- 叶子 Id 集合

---

## 2. 数据模型变更

### 2.1 新建表 `test_task_trees`
```text
id              TEXT(12)   PK
version_id      TEXT(12)   FK test_versions.id
round_number    INTEGER    -- 1, 2, 3, ...
root_name       TEXT
root_id         TEXT
raw_json        TEXT
note            TEXT       -- NOT NULL
parsed_at       DATETIME
created_at      DATETIME
UNIQUE          (version_id, round_number)
```

### 2.2 新建表 `test_task_nodes`
```text
id              TEXT(12)   PK
tree_id         TEXT(12)   FK test_task_trees.id
parent_id       TEXT(12)   FK test_task_nodes.id NULL
name            TEXT       -- 节点 Name
name_key        TEXT       -- 聚合键：name.rsplit('_', 1)[0]（v3.2 新增）
node_id         TEXT
depth           INTEGER
path            TEXT
is_leaf         BOOLEAN
sort_order      INTEGER
extra           TEXT
```

索引：`(tree_id, path)`、`(tree_id, node_id)`、`(tree_id, name_key)`（name_key 索引供整体视图聚合用）。

### 2.3 `tasks` 表加字段
```text
tree_node_id    TEXT(12)   FK test_task_nodes.id NULL
```

### 2.4 多轮次下的数据关系
```
test_versions
  ├─ test_task_trees (round=1)  ── test_task_nodes
  │                              ├─ name="TC_id_1", name_key="TC_id_1"
  │                              └─ name="TC_id_2", name_key="TC_id_2"
  │                                                  └─ Task ─── TestCase "test_login" / "test_logout"
  └─ test_task_trees (round=2)  ── test_task_nodes
                                 ├─ name="TC_id_1_a8b3c", name_key="TC_id_1"  ← 前缀匹配到 round=1
                                 └─ name="TC_id_2_x9y2z", name_key="TC_id_2"  ← 前缀匹配到 round=1
                                                                          └─ Task ─── TestCase "test_login" / "test_logout"
```

**name_key 是聚合键**（不是 name）；TestCase.name 是稳定的（HTML 报告里的用例名）。

### 2.5 migration
- 新表自动建
- `ALTER TABLE tasks ADD COLUMN tree_node_id TEXT(12)`
- 不引入 Alembic

---

## 3. 后端 API

### 3.1 JSON 树管理

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/mapping/versions/{version_id}/tree?mode=preview` | 预览：不写库 |
| POST | `/api/mapping/versions/{version_id}/tree?mode=append` | 追加：写库 + 跨 round 冲突检查 |
| GET  | `/api/mapping/versions/{version_id}/trees` | 列所有轮次 |
| GET  | `/api/mapping/versions/{version_id}/trees/{round_number}` | 拉取指定轮次 |
| DELETE | `/api/mapping/versions/{version_id}/trees/{round_number}` | 删除指定轮次 |
| POST | `/api/mapping/versions/{version_id}/trees/{round_number}/create_tasks` | 批量建任务 |
| POST | `/api/mapping/versions/{version_id}/tree/auto-fetch` | 占位（503） |
| PUT  | `/api/mapping/versions/{version_id}/trees/{round_number}/note` | 改备注 |

### 3.2 追加流程（"追加执行轮次"按钮）

UI 触发一体化操作：
1. 用户点"追加执行轮次" → 弹窗
2. 弹窗：备注（必填）+ JSON 粘贴框 + 解析预览（实时）
3. 解析预览（`mode=preview`）：返回树形结构 + 冲突 Id 列表（不写库）
4. 解析通过 → "确认追加并创建任务"按钮可点
5. 调 `POST /tree?mode=append` → 写库 + 自动 round 分配
6. 调 `POST /trees/{round}/create_tasks` → 批量建任务
7. 弹窗显示结果

### 3.3 批量创建任务

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/mapping/versions/{version_id}/trees/{round_number}/create_tasks` | 遍历该轮次 JSON 树的所有叶子 Id → S3 探测 → 创建 Task 或关联已有 |

**响应**：
```json
{
  "round_number": 2,
  "created":  [...],
  "linked":   [...],
  "skipped":  [...]
}
```

### 3.4 任务详情 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/analysis/{task_id}/trees` | 该 Task 所属 TestVersion 下**所有轮次**的概要 |
| GET | `/api/analysis/{task_id}/tree?round={n}` | 拉取指定轮次的 JSON 树 |
| GET | `/api/analysis/{task_id}/aggregate?tree_node_id={...}` | **整体视图**用的节点元信息（v3.2 扩展：含 missing_rounds） |
| GET | `/api/analysis/{task_id}/aggregate/testcases?tree_node_id={...}` | **整体视图右表 = 跨 round 聚合的 TestCase 行**（按 `LogFile.testcase_name` 聚合；v4 扩展：每行带 suite 信息） |
| GET | `/api/analysis/{task_id}/testcases?round_filter={n}&tree_node_id={...}` | **单轮次视图右表 = 当前 round 的 TestCase 行**（v3.3 新增；v4 扩展：每行带 suite 信息） |
| GET | `/api/analysis/{task_id}/files?round_filter={n\|all}&tree_node_id={...}` | **单轮次视图**用的 LogFile 列表（保留用于审核跳转） |

#### 3.4.1 `/aggregate` — 整体视图节点元信息（v3.2 扩展）

输入：`tree_node_id`（来自 round=1 树的某个节点）。

算法（v3.2 修正）：
1. 找该节点 → 取 `name_key` 作为聚合键（**不是 name**）
2. 范围：当前 Task 所属 TestVersion 下**所有 round** 的 `TestTaskNode` 里 `name_key == X` 的节点
3. 对每个 node 关联的 Task：
   - `SELECT COUNT(*) FROM log_files WHERE task_id = :task_id` → `logfile_count`
   - `logfile_count > 0` → `has_data = true`
4. 计算：
   - `execution_count` = `sum(r.has_data for r in all_rounds)`
   - `latest_round` = `max(r.round_number for r in all_rounds if r.has_data)`（无数据 round 不参与）
   - `missing_rounds` = `[r.round_number for r in all_rounds if not r.has_data]`
5. 首轮 / 最新轮用例数对比

响应：
```json
{
  "node": { "id": "n1", "name": "TC_id_1", "name_key": "TC_id_1", "path": "/.../TC_id_1", "extra": "..." },
  "aggregate": {
    "execution_count": 2,
    "first_round_logfile_count": 5,
    "latest_round": 2,
    "latest_round_logfile_count": 3,
    "latest_round_result": { "success": 2, "failed": 1, "blocked": 0, "unrecognized": 0 },
    "missing_rounds": [3],                    // v3.2 新增：has_data=false 的 round
    "all_rounds": [
      { "round_number": 1, "task_id": "tA", "node_id": "...", "node_name": "TC_id_1",         "logfile_count": 5, "has_data": true  },
      { "round_number": 2, "task_id": "tB", "node_id": "...", "node_name": "TC_id_1_a8b3c",  "logfile_count": 3, "has_data": true  },
      { "round_number": 3, "task_id": "tC", "node_id": "...", "node_name": "TC_id_1_x9y2z",  "logfile_count": 0, "has_data": false }
    ]
  }
}
```

#### 3.4.2 `/aggregate/testcases` — 整体视图右表（v3.3 修正）

输入：`tree_node_id`（来自 round=1 树的某个节点）。

算法（v3.3 修正：按 `LogFile.testcase_name` 聚合，不查 `TestCase` 表）：
1. 找该节点 → 取 `name_key`
2. 范围：当前 TestVersion 下所有 `name_key == X` 的 node
3. 对每个 node 关联的 Task：
   - `logfile_count = count(LogFile WHERE task_id = :task_id)`
   - `logfile_count > 0` → 该 round 实际执行
4. 拉取该 Task 下的所有 `LogFile`（`file_type='testcase'`）
5. 按 `LogFile.testcase_name` 分组聚合：
   - `execution_count` = 该 testcase_name 出现在多少个有数据的 round
   - `rounds` = `[round_number for each occurrence]`
   - `latest_round` = `max(rounds)`
   - `latest_logfile_id` = 最新 round 该 testcase 对应的 LogFile.id（用于"查看详情"跳转）
   - `latest_logfile_status` = 该 LogFile 的最终结论/审核状态
   - `latest_round_file_count` = latest_round 下该 testcase_name 的 LogFile 数
   - `missing_rounds` = 该 testcase_name 在哪些 round 缺失（节点存在但该 round 没对应 LogFile）
6. 响应：按 testcase_name 排序

响应（v4 扩展，每行带 suite 信息）：
```json
{
  "node": { "id": "n1", "name": "TC_id_1", "name_key": "TC_id_1", "path": "/.../TC_id_1" },
  "testcases": [
    {
      "name": "test_login_success",
      "execution_count": 2,
      "rounds": [1, 2],
      "latest_round": 2,
      "latest_status": "pass",
      "latest_round_file_count": 1,
      "missing_rounds": [3],
      "suite": {                         // v4 新增：所属测试套（用 round=1 的 suite 作为基准）
        "id": "TS_id_1",
        "name": "TestSuite_1",
        "result": "failed",
        "start_time": "...",
        "end_time": "...",
        "fail_detail_short": "...",
        "logfile_id": "fSuite1",        // 匹配到的 testsuite LogFile.id
        "logfile_path": "s3://.../artifacts/testsuite/TS_id_1.html"
      }
    },
    {
      "name": "test_logout",
      "execution_count": 1,
      "rounds": [1],
      "latest_round": 1,
      "latest_status": "fail",
      "latest_round_file_count": 1,
      "missing_rounds": [2, 3],
      "suite": { "id": "TS_id_1", "name": "TestSuite_1", "result": "failed", "logfile_id": "fSuite1", "logfile_path": "..." }
    }
  ],
  "summary": {
    "total_testcases": 5,
    "executed_in_all_rounds": 1,
    "missing_in_some_round": 4,
    "missing_testcases_in_latest": 1
  }
}
```

> **v4 关键**：跨 round 同一 testcase_name 关联到同一个 suite（按 suite.id 关联）。如果
> 不同 round 的 testcase 关联到不同 suite（理论上不应该发生），以 round=1 的为准。

#### 3.4.3 `/testcases` — 单轮次视图右表（v3.3 新增）

输入：`tree_node_id`（来自对应 round 树的某个节点） + `round_filter`（默认 = 当前 Task 所在 round）。

算法：
1. 找 `tree_node_id` → 关联 Task
2. 拉取该 Task 下的所有 `LogFile`（`file_type='testcase'`）
3. 按 `testcase_name` 分组（一行一个 testcase_name）
4. 每行展示该 testcase_name 对应 LogFile 的字段：
   - testcase_name
   - logfile_id（用于审核跳转）
   - logfile_path
   - file_type
   - total_lines / failure_count
   - summary_report（来自 metadata/summary_report.yaml）
   - primary 最终结论 / 置信度 / 匹配规则
   - review_status / override 信息
5. 响应：按 testcase_name 排序

响应（v4 扩展，每行带 suite 信息）：
```json
{
  "round_number": 1,
  "task_id": "tA",
  "testcases": [
    {
      "testcase_name": "test_login_success",
      "logfile": {
        "id": "f1", "name": "test_login_success.html", "file_path": "...",
        "total_lines": 100, "failure_count": 0,
        "summary_report": { "display_result": "Success", "normalized_status": "success", ... },
        "final_category": { "id": "...", "name": "..." },
        "primary": { "confidence": 0.95, "is_fallback": false, "rule_name": "...", "rule_id": "..." },
        "review_status": "pending", "is_overridden": false
      },
      "suite": {                          // v4 新增：所属测试套
        "id": "TS_id_1",
        "name": "TestSuite_1",
        "result": "failed",
        "start_time": "...",
        "end_time": "...",
        "fail_detail_short": "...",
        "logfile_id": "fSuite1",
        "logfile_path": "s3://.../artifacts/testsuite/TS_id_1.html"
      }
    },
    {
      "testcase_name": "test_logout",
      "logfile": { ... },
      "suite": { "id": "TS_id_1", "name": "TestSuite_1", "result": "failed", "logfile_id": "fSuite1", "logfile_path": "..." }
    }
  ],
  "summary": { "total_testcases": 5, "with_failure": 1 }
}
```

#### 3.4.4 `/files` — 单轮次视图（保留用于"按文件查看"）

- `round_filter=N` → 只看第 N 轮
- `round_filter=all` → 跨轮次合并
- 不传 `tree_node_id` → 仅当前 Task 的 LogFile
- 传 `tree_node_id` → 选中节点子树 + 轮次过滤
- 每条 LogFile 响应带 `round_number`
- **v3.3 状态**：保留为底层端点；单 round tab 默认走 `/testcases`（按 testcase_name 分组），不直接用 `/files`。`/files` 用于"查看完整文件列表"或"审核跳转"

### 3.5 老 API 兼容
- `create_task` 的 `purpose_id` 路径保留
- `discover` 接口保留
- TestPurpose / TaskReference 全保留

---

## 4. 前端改动

### 4.1 `MappingManager.vue`

**"JSON 树（按轮次管理）" 区块**：
- 顶部摘要：列出所有轮次（轮次 N + 根名 + 备注 + 创建时间 + 操作）
- **"追加执行轮次"主按钮** → 弹窗：
  - 备注（必填）
  - JSON 粘贴框
  - 解析预览（实时）：树形 + 叶子数 + S3 匹配 + **跨 round 冲突检查**
  - 占位按钮"按执行 ID 自动获取"（503 + 提示）
- 已有轮次操作：[查看] [改备注] [按此次批量建任务] [删除]

### 4.2 `TaskDetail.vue` — 顶部 Tab 切换 + 两视图

**顶部新结构**（在 `el-tabs` 的 `分析详情` Tab 内）：
```vue
<el-tabs v-model="innerActiveTab" @tab-change="handleInnerTabChange">
  <el-tab-pane label="单轮次" name="round" />
  <el-tab-pane label="整体" name="aggregate" />
</el-tabs>
```

#### 4.2.1 单轮次视图（v4 扩展）
- 顶部轮次选择器（默认 = 当前 Task 所在 round）
- 左树右表布局
- **左树**：当前 round 的 JSON 树（`GET /tree?round=N`）
- 选中节点 → `GET /testcases?tree_node_id=...&round_filter=N`
- **右表 = TestCase 行**（v4 扩展：每行带 suite 信息）：
  - 列：`用例名` / `所属测试套`（v4 新增，suite.name + suite_id 小灰字 + "查看" 链接到 suite LogFile） / `状态`（来自 summary_report）/ `失败原因` / `最终结论` / `置信度` / `匹配规则` / `审核状态` / `操作`
  - 每行对应一个 `LogFile.testcase_name`（一行一个用例）
  - "所属测试套"列：suite 信息缺失时显示 `—` + 鼠标悬停提示 "summary_report.yaml 中无该 testcase 对应 suite"
  - "操作"列的"审核"按钮跳到该行的 LogFile 详情（`ReviewDrawer`）
- **关键设计**：suite 在**多行里重复展示**（1 套 → N 用例 → N 行，每行都带 suite 信息）

#### 4.2.2 整体视图（v3.2 重写）

**顶部缺失告警条**（v3.2 新增）：
- 调 `GET /aggregate?tree_node_id=...` 拿到所有轮次的 missing 状态
- 顶部展示：
  ```
  ⚠ 共有 3 个节点在 2 个 round 存在日志缺失。最新缺失：轮次 3。
  ```
- 缺失为 0 时不显示

**左树**：基于 **round=1** 的树结构
- 节点显示：`{name}` 粗体 + `{node_id}` 小灰字 + **`{name_key}` 灰底**（v3.2 显式显示聚合键）
- 叶子节点附加元信息（`GET /aggregate?tree_node_id=...` 缓存）：
  - `<el-tag>已执行 N 次</el-tag>`
  - `<el-tag>最新: 轮次 M</el-tag>`
  - `<el-tag type="warning">首轮 5 / 最新 3</el-tag>` —— 如果最新 < 首轮
  - **数据缺失告警**（v3.2 新增）：
    - 如果有 `missing_rounds`：`⚠ 轮次 2 缺失日志`（最多显示 2 个，超过用 "..."）
    - `<el-tag type="danger">⚠ 缺失 N</el-tag>` 紧凑显示
  - 鼠标悬停显示：每个 round 的 task_id + node_name + logfile_count（用 `aggregate.all_rounds`）

**右表 = 跨 round 聚合的 TestCase 行**（v4 扩展：每行带 suite 信息）：
- 选中节点时：调 `GET /aggregate/testcases?tree_node_id=...`
- 头部：节点 name_key + "共 5 个用例 / 已执行 N 次（所有用例） / 4 个用例在某轮缺失"
- 表格列：
  | 用例名 | 所属测试套（v4） | 跨 round 执行次数 | 参与轮次 | 最新轮次 | 最新结果 | 最新轮 LogFile |
  |---|---|---|---|---|---|---|
  | test_login_success | TestSuite_1 (TS_id_1) · 查看 | 2 | 1, 2 | 2 | pass | 查看 → |
  | test_logout | TestSuite_1 (TS_id_1) · 查看 | 1 | 1 | 1 | fail | 查看 → |
- **所属测试套列**（v4 新增）：
  - suite.name 粗体 + suite.id 小灰字
  - "查看" 链接到该 suite 对应的 testsuite LogFile（走 `/files/{id}` 详情或直接打开 S3 路径）
  - suite 信息缺失 → `—` + 鼠标悬停 "summary_report.yaml 中无该 testcase 对应 suite"
  - 跨 round 时 suite 用 round=1 的（suite 不变就 OK；理论上不变）
- **缺失告警**：missing_rounds 非空的行用 `<el-tag type="warning">轮次 2, 3 缺失</el-tag>` 标记
- 表格底部"摘要"行：总用例数 / 所有轮次都执行的 / 部分轮次缺失的 / 最新轮缺失数
- **"最新轮 LogFile"列**："查看"按钮跳到该 testcase 最新一轮 LogFile 的 `ReviewDrawer`

**节点 extra 字段**：悬停 tooltip 显示

#### 4.2.3 老任务兼容
- `Task.tree_node_id IS NULL`：
  - "单轮次" tab：现状（平铺表 + "未关联 JSON 树"提示）
  - "整体" tab：禁用 + 提示"需先关联 JSON 树"

### 4.3 `TaskList.vue`
**不动**。

### 4.4 API 客户端扩展

`frontend/src/api/index.js`：
- `mapping.previewTree(versionId, jsonText)`
- `mapping.appendTree(versionId, jsonText, note)`
- `mapping.updateNote(versionId, round, note)`
- `mapping.listTrees(versionId)`
- `mapping.getTree(versionId, round)`
- `mapping.deleteTree(versionId, round)`
- `mapping.createTasksFromTree(versionId, round)`
- `mapping.autoFetchTree(versionId, executionId)`
- `analysis.getTaskTrees(taskId)`
- `analysis.getTaskTree(taskId, round)`
- `analysis.getAggregate(taskId, treeNodeId)` — 节点元信息（含 missing_rounds）
- `analysis.getAggregateTestcases(taskId, treeNodeId)` — **v3.3 修正：按 `LogFile.testcase_name` 聚合**
- `analysis.getTestcases(taskId, { tree_node_id, round_filter })` — **v3.3 新增：单 round 的 TestCase 行**
- `analysis.files(taskId, { ..., tree_node_id, round_filter })` — 保留为底层端点（审核跳转用）

---

## 5. 行为细节

### 5.1 JSON 解析器
`backend/app/services/task_tree.py`：
```python
def parse_task_tree(raw_json: str) -> dict:
    """返回 { tree, nodes, leaves, extra_fields_seen }。
    - nodes: 含 name / name_key / node_id / path / depth / is_leaf / parent_id / extra
    - name_key = name.rsplit('_', 1)[0]  # 聚合键
    - 任何失败抛 ValueError。"""

def check_cross_round_id_conflict(version_id, new_leaf_ids, db) -> list[str]:
    """返回与已有 round 冲突的 Id 列表。"""
```

### 5.2 轮次号分配
- `mode=append`：事务内 `SELECT MAX(round_number) ...` + 1；唯一约束兜底并发
- 不允许 `mode=replace`

### 5.3 删除某轮次
```sql
BEGIN;
UPDATE tasks SET tree_node_id = NULL
  WHERE tree_node_id IN (SELECT id FROM test_task_nodes WHERE tree_id = :tree_id);
DELETE FROM test_task_nodes WHERE tree_id = :tree_id;
DELETE FROM test_task_trees WHERE id = :tree_id;
COMMIT;
```

### 5.4 跨 round 冲突 Id 检查
- 时机：`POST /tree?mode=append` 进入事务后，写入前
- 范围：该 version 下**所有已有 round** 的 `TestTaskNode.node_id` 集合
- 命中：返回 400（整次 append 回滚）

### 5.5 节点 name_key 聚合（整体视图）
```python
def aggregate_by_name_key(version_id, target_node_db_id):
    target = get_node(target_node_db_id)
    target_key = target.name_key
    # 找该 version 下所有 name_key 相同的 node（跨所有 round）
    all_nodes = db.execute(
        select(TestTaskNode)
        .join(TestTaskTree, TestTaskNode.tree_id == TestTaskTree.id)
        .where(TestTaskTree.version_id == version_id,
               TestTaskNode.name_key == target_key)
    ).scalars().all()
    
    per_round = []
    for node in all_nodes:
        task = db.execute(
            select(Task).where(Task.tree_node_id == node.id)
        ).scalar_one_or_none()
        logfile_count = 0
        if task:
            logfile_count = db.execute(
                select(func.count(LogFile.id)).where(LogFile.task_id == task.id)
            ).scalar() or 0
        per_round.append({
            "round_number": node.tree.round_number,
            "task_id": task.id if task else None,
            "node_id": node.node_id,
            "node_name": node.name,
            "logfile_count": logfile_count,
            "has_data": logfile_count > 0,
        })
    
    # 执行次数 = 有数据的 round 数（v3.2 修正）
    execution_count = sum(1 for r in per_round if r["has_data"])
    # 最新一次 = max(round where has_data)（v3.2 修正）
    latest = max((r for r in per_round if r["has_data"]),
                 key=lambda r: r["round_number"], default=None)
    # 缺失 round（v3.2 新增）
    missing_rounds = [r["round_number"] for r in per_round if not r["has_data"]]
    ...
```

### 5.6 TestCase 维度聚合（v4 扩展：带 suite 信息）
```python
def aggregate_testcases_by_name_key(version_id, target_node_db_id):
    target = get_node(target_node_db_id)
    target_key = target.name_key
    # 找该 version 下所有 name_key 相同的 node
    all_nodes = db.execute(...)  # 同 5.5
    
    # 按 (testcase_name, round) 收集 LogFile
    testcase_by_name = {}  # testcase_name -> { rounds: {round_num: logfile}, ... }
    for node in all_nodes:
        task = db.execute(select(Task).where(Task.tree_node_id == node.id)).scalar_one_or_none()
        if not task: continue
        # 该 task 是否有数据
        logfile_count = db.execute(
            select(func.count(LogFile.id)).where(LogFile.task_id == task.id)
        ).scalar() or 0
        if logfile_count == 0:
            continue  # 没数据 round 不参与 TestCase 聚合
        round_num = node.tree.round_number
        # 找该 task 下的 LogFile (file_type='testcase')
        logfiles = db.execute(
            select(LogFile).where(
                LogFile.task_id == task.id,
                LogFile.file_type == "testcase"
            )
        ).scalars().all()
        for lf in logfiles:
            tc_name = lf.testcase_name or lf.name
            if tc_name not in testcase_by_name:
                testcase_by_name[tc_name] = {"rounds": {}}
            testcase_by_name[tc_name]["rounds"][round_num] = lf
    
    # 计算每条 TestCase 的统计
    result = []
    all_round_nums = [n.tree.round_number for n in all_nodes]
    for tc_name, data in testcase_by_name.items():
        rounds_dict = data["rounds"]
        rounds = sorted(rounds_dict.keys())
        latest_round = max(rounds)
        latest_lf = rounds_dict[latest_round]
        # 缺失 round = 节点所在 round 中没有该 testcase_name 对应 LogFile 的 round
        missing_rounds = [r for r in all_round_nums if r not in rounds]
        result.append({
            "name": tc_name,
            "execution_count": len(rounds),
            "rounds": rounds,
            "latest_round": latest_round,
            "latest_logfile_id": latest_lf.id,
            "latest_logfile_status": latest_lf.review_status,
            "latest_round_file_count": 1,  # v3.3 简化：1 个 testcase_name = 1 个 LogFile
            "missing_rounds": missing_rounds,
        })
    return result
```

### 5.6.1 单 round TestCase 视图（v3.3 新增）
```python
def list_testcases_in_round(task_id, tree_node_id, round_filter):
    """单 round tab 用的右表数据：当前 round 下选中节点对应 Task 的所有 LogFile（file_type='testcase'）"""
    node = get_node(tree_node_id)
    task = get_task_by_tree_node(node.id)
    if not task:
        return {"testcases": [], "summary": {"total_testcases": 0, "with_failure": 0}}
    logfiles = db.execute(
        select(LogFile).where(
            LogFile.task_id == task.id,
            LogFile.file_type == "testcase"
        ).order_by(LogFile.testcase_name)
    ).scalars().all()
    
    # 加载每个 LogFile 的 summary_report / final_category / primary（同现有 /files 端点逻辑）
    result = []
    for lf in logfiles:
        result.append({
            "testcase_name": lf.testcase_name or lf.name,
            "logfile": {
                "id": lf.id, "name": lf.name, "file_path": lf.file_path,
                "total_lines": lf.total_lines, "failure_count": lf.failure_count,
                "summary_report": ...,
                "final_category": ...,
                "primary": ...,
                "review_status": lf.review_status,
                "is_overridden": lf.review_status == "overridden",
            }
        })
    return {
        "round_number": round_filter,
        "task_id": task.id,
        "testcases": result,
        "summary": {
            "total_testcases": len(result),
            "with_failure": sum(1 for r in result if r["logfile"]["failure_count"] > 0)
        }
    }
```

### 5.7 测试套 LogFile 匹配算法（v4 新增）

```python
def find_suite_logfile(suite_info, suite_logfiles) -> Optional[LogFile]:
    """suite_info: dict (id/name/desc/result/...)；suite_logfiles: file_type='testsuite' 的 LogFile 列表。
    匹配策略（按优先级）：
      1. suite.id 的 stem 等于 LogFile.name 的 stem（精确）
      2. suite.id 包含 LogFile.name 的 stem（子串）
      3. LogFile.name 的 stem 包含 suite.id（反向子串）
      4. suite.desc 同上三种
      5. 都不匹配 → None
    """
    if not suite_info:
        return None
    candidates = []
    for k in ("id", "desc", "name"):
        v = suite_info.get(k)
        if v:
            v_lower = str(v).lower()
            candidates.append(v_lower)
            # stem（按 _ 或 - 分割取前面）
            for sep in ("_", "-"):
                if sep in v_lower:
                    candidates.append(v_lower.rsplit(sep, 1)[0])
    for lf in suite_logfiles:
        lf_stem = lf.name.lower().rsplit(".", 1)[0]
        for cand in candidates:
            if not cand:
                continue
            if cand == lf_stem:
                return lf
            if cand in lf_stem or lf_stem in cand:
                return lf
    return None
```

**调用位置**：`api/analysis.py:list_analyzed_files` 在拼装响应时：
1. 一次性查该 Task 下所有 `file_type='testsuite'` 的 LogFile → `suite_logfiles`
2. 对每个 testcase LogFile，调用 `summary_for_file` 得到 `case_rec.suite`
3. 调 `find_suite_logfile(case_rec.suite, suite_logfiles)` 得到 `suite_logfile`
4. 响应里加 `suite` 字段（id/name/result/start_time/end_time/fail_detail_short/logfile_id/logfile_path）

### 5.8 跨 round suite 关联（整体视图）

- 同一 testcase_name 在不同 round 关联的 suite **理论上应该相同**（summary_report.yaml 是按 version 生成）
- 整体视图聚合时：取 round=1 的 suite 信息作为该 testcase_name 的 suite
- 如果 round=1 没该 testcase（首轮没跑这个用例），用该 testcase **最早出现的 round** 的 suite
- 跨 round suite 不一致（异常情况） → 取**最常见的**（mode），并加 `<el-tag type="warning">套 ID 不一致</el-tag>` 提示

### 5.9 中文支持
- 全程 UTF-8（DB / Python / JSON / Vue）

### 5.10 节点 extra 字段
- 解析时只关注 Name / Id / child_tasks
- 其他字段原样收集 → `json.dumps(extra_dict, ensure_ascii=False)` → 存 `test_task_nodes.extra`

### 5.11 备注管理
- 追加时必填
- 修改：`PUT /trees/{round}/note`

### 5.12 占位 auto-fetch 接口
- 当前 503 + "即将推出"
- 未来插 Python 函数（输入 execution_id，输出 JSON 字符串）

---

## 9. 关键步骤日志（v5 新增）

### 9.1 现状盘点

| 设施 | 覆盖范围 | 格式 | 配置 |
|---|---|---|---|
| `app.core.audit_logger` | 分析流水线（pipeline/s3/rule/failure） | JSONL，按 task_id 维度 | `settings.audit_enabled` |
| `logging.getLogger("app.xxx")` | 各处用，但**无统一配置**（默认 WARNING） | 看 Python 默认 | 无 |
| `db_diagnostics.log` | SQLite 连接/事务诊断 | 文本 | `db_diagnostics_enabled` |

**缺口**：v3/v4 新增路径（JSON 树、suite 关联、聚合、S3 探测、API 响应组装）**无日志**。

### 9.2 新增配置

`backend/app/config.py`：
```python
# Logging
app_debug_logging: bool = True  # 默认打开；发布设 LA_APP_DEBUG_LOGGING=false
log_file: Path = Path("./data/app.log")  # 可选：单独日志文件
```

### 9.3 统一 logging 配置

新建 `backend/app/core/logging_setup.py`：
```python
def setup_logging(enabled: bool, log_file: Optional[Path] = None) -> None:
    """根据 enabled 初始化 logging 设施。
    - enabled=True:  root logger 设 INFO，app.* logger 设 DEBUG；输出到 stdout + 文件
    - enabled=False: root logger 设 WARNING；app.* logger 设 WARNING
    """
    root = logging.getLogger()
    if enabled:
        root.setLevel(logging.INFO)
        logging.getLogger("app").setLevel(logging.DEBUG)
    else:
        root.setLevel(logging.WARNING)
        logging.getLogger("app").setLevel(logging.WARNING)
    
    # 统一格式
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )
    # stdout handler
    sh = logging.StreamHandler()
    sh.setFormatter(formatter)
    root.addHandler(sh)
    # file handler (可选)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(formatter)
        root.addHandler(fh)
```

`backend/app/main.py` lifespan 启动时调用：
```python
from app.core.logging_setup import setup_logging
setup_logging(enabled=settings.app_debug_logging, log_file=settings.log_file)
```

### 9.4 关键步骤日志清单（v5 新增）

| 路径 | 日志点 | 级别 | 字段 |
|---|---|---|---|
| `POST /tree?mode=preview` | 解析开始 / 解析完成 / 跨 round 冲突数 / S3 匹配数 | INFO | version_id, total_nodes, leaf_count, conflict_count, matched_count |
| `POST /tree?mode=append` | 分配 round / 跨 round 冲突检查结果 / 写库 / 失败回滚 | INFO / WARNING | version_id, round_number, conflict_ids |
| `DELETE /trees/{round}` | 删除轮次 / 影响 task 数 | INFO | version_id, round_number, affected_task_count |
| `POST /trees/{round}/create_tasks` | 探测开始 / S3 匹配数 / 创建 task 数 / 关联 task 数 / 跳过数 | INFO | round_number, created, linked, skipped |
| `POST /tree/auto-fetch` | 占位调用 / 503 返回 | INFO | version_id, execution_id |
| `PUT /trees/{round}/note` | 备注更新 | INFO | round_number, note_length |
| `summary_for_file` | 找到 case_rec / 未找到 / suite 找到 / suite 缺失 | DEBUG | log_file_id, case_id, suite_id |
| `find_suite_logfile` | 5 步匹配过程 / 最终匹配结果 | DEBUG | suite_id, matched_lf_id, strategy_used |
| `list_analyzed_files` | 响应组装开始 / 过滤后行数 | INFO | task_id, raw_count, filtered_count |
| `aggregate_by_name_key` | 跨 round 节点数 / 缺失轮次数 | DEBUG | version_id, name_key, round_count, missing_rounds |
| `aggregate_testcases_by_name_key` | 跨 round testcase 数 / 缺失 testcase 数 | INFO | version_id, name_key, total_testcases, missing_count |
| `list_testcases_in_round` | 单 round testcase 数 / 缺失 suite 数 | INFO | task_id, tree_node_id, testcase_count, missing_suite_count |
| S3 探测 | 探测路径 / 探测结果 | DEBUG | version_name, leaf_id, has_data |
| 异常 catch | 异常信息 | ERROR | full traceback |

### 9.5 日志格式示例

```
2026-07-06 19:45:13,456 [INFO] app.services.task_tree: [tree.append] version_id=v1 round_number=2 total_nodes=5 leaf_count=2 conflict_count=0
2026-07-06 19:45:13,890 [INFO] app.api.mapping: [create_tasks] round_number=2 created=2 linked=0 skipped=0
2026-07-06 19:45:14,012 [DEBUG] app.services.summary_report: [find_suite_logfile] suite_id=TS_id_1 matched_lf_id=fSuite1 strategy=stem_exact
2026-07-06 19:45:14,123 [WARNING] app.services.summary_report: [find_suite_logfile] suite_id=TS_id_2 matched_lf_id=null reason=no_candidate_match
2026-07-06 19:45:14,234 [ERROR] app.api.mapping: [tree.append] version_id=v1 conflict_ids=['3806765545196879874'] rolled_back=true
```

### 9.6 audit_logger 与新 logger 的分工

- **audit_logger**（保持）：**分析流水线的结构化审计**（按 task_id 维度，JSONL）
  - pipeline.start/end、step.enter/exit、s3.list_dir/s3.read_file、rule.evaluate、failure.classified
  - 用户通过 `/api/audit/{task_id}` 查看
- **新 logger**（v5）：**其他关键路径的运行日志**（按时间维度，文本）
  - JSON 树管理、API 响应组装、聚合算法、S3 探测、suite LogFile 匹配
  - 输出到 stdout（dev）或 app.log（prod）
  - 用户通过终端 / 文件查看
- **不重复**：分析流水线已用 audit_logger 的，**不再加 logger**，避免日志爆炸

### 9.7 测试

- **logger 启用/关闭测试**：`app_debug_logging=false` 时，所有新加的 logger.info/debug **不输出**
- **关键路径日志存在性测试**：每个关键函数 mock 后检查 logger 调用次数
- **不破坏现有 audit_logger 行为**

---

## 6. 兼容性

| 旧能力 | 状态 |
|---|---|
| `TestPurpose` / `TaskReference` 表 | 保留 |
| `discover` 接口 | 保留 |
| `create_task` 的 `purpose_id` 路径 | 保留 |
| 老 `Task` 记录（无 `tree_node_id`） | 保留；TaskDetail 给"未关联 JSON 树"提示 |
| 老 `TaskDetail` 4 个 Tab 中"原始日志/日志浏览/失败事件" | 完全不变 |
| 老 `MappingManager` 的"创建目的"流程 | 保留为 legacy |
| 老 `TaskList` 创建入口 | 保留 |

---

## 7. 风险与边界

- **name_key 提取规则的局限性**：当前硬编码"最后一个 `_` 之后是随机后缀"。如果测试系统的随机后缀格式变化（比如用 `-` 分割、或长度固定），需要更新解析逻辑。**缓解**：先在硬编码层做，未来加配置项
- **TestCase.name 跨 round 稳定性**：假设 TestCase.name 不变。如果测试代码改了，跨 round 的 name 不同，则聚合失败——但这是 HTML 报告层面决定的，不是我们能控制的
- **S3 探测超时**：并发探测 + 5s 超时
- **跨 round 冲突 Id 回滚**：整次 append 失败，包括 round_number 分配
- **同名 name_key 跨 round 聚合性能**：用 `(tree_id, name_key)` 索引
- **删除某轮次时 Task**：保留 Task 实体仅置 NULL `tree_node_id`
- **整体视图 round=1 是"最全"假设**：如果用户 round=1 不是最全的，元信息会误导——通过备注/排序提示用户
- **TestCase 缺失轮次计算（v3.3 修正）**：按 `LogFile.testcase_name` 分组聚合——如果 HTML 报告里没解析出 `testcase_name`，该 LogFile 会被忽略
- **v4 - suite LogFile 匹配失败**：suite.id / desc 跟 testsuite HTML 文件名没强匹配规则（5 步策略是启发式），如果上传方 HTML 文件命名不规范（如 `testsuite.html` 这种通用名），**匹配不到** → suite.logfile_id 为 null，前端只展示 suite 名字信息，**链接缺失**。**缓解**：UI 上明确提示"日志文件未匹配"，可考虑后续让用户手动配置 mapping
- **v4 - testsuite HTML 文件名规范**：当前 S3 设计 `artifacts/testsuite/` 下文件名是 `testsuiename.html` 这种通用名。如果匹配规则覆盖不到，建议上传方把文件名改为 `TS_id.html` 格式。**`rustfs-folder-design.md` 可加一条命名建议**
- **v5 - 日志性能开销**：默认 INFO 级别可能产生大量日志（每个 S3 探测、每行 LogFile 都会记）——DEBUG 级尤其需要 care。**缓解**：DEBUG 默认关闭（enabled=True 时只升 INFO 到 app.* 子 logger）；关键路径才用 INFO
- **v5 - 日志文件膨胀**：长时间运行后 `app.log` 持续增长。**缓解**：本计划不实现日志轮转（v5 范围外）；生产环境用 logrotate 外部管理
- **v5 - 重复日志**：audit_logger 已覆盖的路径（如 pipeline.start）不要再用 logger 重复打——文档里 9.6 明确分工
- **auto-fetch 占位接口扩展性**：未来插函数时不影响 UI

---

## 8. 测试计划

### 8.1 后端单测
`backend/tests/test_task_tree.py`：
- ✅ 既有：3 层/1 层/大小写/解析错误/同树 Id 重复
- 🆕 **name_key 提取规则**：
  - `TC_id_1` → `TC_id_1`
  - `TC_id_1_a8b3c` → `TC_id_1`
  - `统计分析__2` → `统计分析_`
  - `统计分析__2_x9y2z` → `统计分析__2`
- 🆕 **节点 extra 字段保存**
- 🆕 **跨 round 冲突 Id 报错**
- 🆕 **append 原子性**
- 🆕 **轮次备注**
- 🆕 **占位 auto-fetch 503**
- 🆕 **`aggregate_by_name_key`**：name_key 相等时跨 round 聚合
- 🆕 **执行次数（节点级）= has_data 的 round 数**：round=3 节点存在但 logfile_count=0 → execution_count 不增加
- 🆕 **最新一次 = max(round where has_data)**
- 🆕 **missing_rounds = [r for r in all_rounds if not r.has_data]**
- 🆕 **`aggregate_testcases_by_name_key`**：按 `LogFile.testcase_name` 聚合 execution_count / rounds / latest（v3.3 修正：不查 `TestCase` 表）
- 🆕 **TestCase 缺失轮次**：round=2 logfile_count=0 → 该 round 的 TestCase 不参与聚合，对应 testcase_name 的 missing_rounds 包含 2
- 🆕 **v4 - 测试套关联（summary_report.yaml）**：`case_rec.suite` 含父 suite 信息；`summary_for_file` 扩展返回 suite 字段（id/name/desc/result/start_time/end_time/fail_detail）
- 🆕 **v4 - suite LogFile 匹配**：`find_suite_logfile` 5 步匹配策略（id/desc/name 的 stem 与 LogFile.name 的 stem 比对）；匹配成功返回 `suite_logfile_id` + `suite_logfile_path`
- 🆕 **v4 - 跨 round suite 关联**：取 round=1 的 suite 作为基准；不一致时用最常见值并加告警

### 8.2 集成测
`backend/tests/test_task_tree_api.py`：
- ✅ 既有
- 🆕 `POST /tree?mode=preview` 不写库
- 🆕 `POST /tree?mode=append` 跨 round 冲突回滚
- 🆕 `POST /tree/auto-fetch` 503
- 🆕 `PUT /trees/{round}/note`
- 🆕 `GET /aggregate?tree_node_id=...` 返回 execution_count / latest_round / **missing_rounds** / all_rounds
- 🆕 `GET /aggregate/testcases?tree_node_id=...` 返回 TestCase 维度数据（按 `LogFile.testcase_name` 聚合，**每行带 suite 字段**）
- 🆕 `GET /testcases?tree_node_id=...&round_filter=N` 返回单 round 的 TestCase 行（**每行带 suite 字段**）

### 8.3 前端
- `npm run build`
- 手动验证：
  - MappingManager 粘贴 example_task_result.json → 出现轮次 1
  - 再次粘贴含 `_a8b3c` 后缀的 JSON + 备注 → 追加为轮次 2
  - 整体视图左树节点显示 `name_key` 灰底
  - 整体视图选中节点：右表 = TestCase 行
  - 右表列：跨 round 执行次数 / 参与轮次 / 最新轮次 / 最新结果
  - 缺失告警：模拟 round=3 节点存在但 S3 无数据
    - 节点元信息显示 `⚠ 轮次 3 缺失日志`
    - 顶部缺失告警条显示 "X 个节点在 Y 个 round 存在日志缺失"
    - 右表里缺失 round 的 TestCase 行标 `轮次 3 缺失`
  - 占位按钮点"按执行 ID 自动获取" → toast "即将推出"
  - 单 round tab：右表 = TestCase 行（**v4 扩展**：每行展示"所属测试套"）
  - 整体 tab：右表 = 跨 round 聚合的 TestCase 行（**v4 扩展**：每行带 suite 信息）
  - 所属测试套列：suite.name + suite_id + "查看" 链接
  - suite 信息缺失：显示 `—` + 提示
  - 跨 round 同一 testcase 关联到不同 suite：告警 `<el-tag type="warning">套 ID 不一致</el-tag>`
  - 老任务：友好降级
- 回归：所有 v3.1 回归项 + 中文/单 round tab 行为

### 8.4 兼容性回归
- 老 task 详情正常打开
- 老 `create_task?purpose_id=` 路径 work
- 老 `discover` 接口 work
- 含中文的 JSON 输入输出无乱码

---

## 9. 实施步骤（建议顺序）

1. **数据模型**：`TestTaskTree` / `TestTaskNode`（含 `name_key` / `extra`）新表 + `Task.tree_node_id` 字段
2. **JSON 解析器**：`backend/app/services/task_tree.py` + 单测（含 name_key、跨 round 冲突）
3. **S3 探测**：`backend/app/services/task_tree_s3.py`
4. **Mapping API**：preview / append / list / get / delete / create_tasks / auto-fetch(占位) / note
5. **Analysis API**：`/trees` / `/tree?round=...` / `/files?round_filter` / `/aggregate` / **`/aggregate/testcases`** / **`/testcases`**
6. **MappingManager.vue**：JSON 树 UI
7. **TaskDetail.vue**：单轮次（TestCase 行） + 整体（跨 round 聚合的 TestCase 行 + 数据缺失告警）
8. **API 客户端**：`frontend/src/api/index.js`
9. **日志设施**（v5）：`backend/app/core/logging_setup.py` + `settings.app_debug_logging` + 关键路径 logger 调用
10. **集成测 + 手动验证**

---

## 10. 假设清单（请审阅时确认/纠正）

| # | 假设 | 影响 |
|---|---|---|
| A | 一个 TestVersion 支持**多棵** JSON 树，每棵 = 一个 round | DB / API / UI |
| B | **轮次号自动递增**（首次=1，追加=max+1），不可手改 | UI |
| C | 物理上每个叶子一条 Task 记录，加 `tree_node_id` 关联 | Task 模型 |
| D | 同一 leaf name 在不同 round 是不同 `TestTaskNode` 记录 | DB |
| E | **跨 round 冲突 Id 直接报错 400**（不 relink） | API / DB |
| F | **删除某 round 不删 Task**，仅 `tree_node_id` 置 NULL | 数据安全 |
| G | **不覆盖**——只 append | API 严格化 |
| H | 字段大小写不敏感解析 | parser |
| I | JSON 解析失败返回 400 | API |
| J | S3 探测不到的叶子跳过 | API |
| K | 中文全程 UTF-8 | 编码 |
| L | 节点其他属性存 `extra` 字段，UI 暂不展示 | DB / 前端 |
| M | 追加必须输入备注 | UI 校验 + DB NOT NULL |
| N | 占位 auto-fetch 接口当前 503 | API |
| O | 解析预览实时可见，冲突警告立即显示 | UI |
| P | 单轮次视图 = 左树右表 + round 选择器 + **LogFile 行** | UI |
| Q | 整体视图 = round=1 树 + name_key 聚合 + **TestCase 行** | UI / API |
| R | **整体视图不按 round 分组展示**（不展开历史文件明细） | UI / API |
| S | 整体视图 round=1 是"最全"假设 | UI |
| T | **节点执行次数 = has_data round 数** | 后端 |
| U | **最新一次 = max(round where has_data)** | 后端 |
| V | 路由 `/tasks/:id` 不变 | URL |
| W | TaskList 不增加"按 JSON 批量建"入口 | 入口分布 |
| X | `node_id` / `task_block_id` 默认 `*` | 行为兼容 |
| Y | "追加执行轮次"是唯一入口 | UI |
| Z | 备注独立接口可改 | API |
| AA | **聚合键 = `name.rsplit('_', 1)[0]`**（v3.2 新增） | parser / DB |
| AB | **TestTaskNode 加 `name_key` 字段**（v3.2 新增） | DB |
| AC | **数据缺失告警**：节点元信息 + 整体视图顶部 + 右表 TestCase 行（v3.2 新增） | UI / API |
| AD | **TestCase 维度聚合**：按 `TestCase.name` 统计跨 round execution_count / rounds / latest_round / latest_status | API / UI |
| AE | **整体视图右表 = 跨 round 聚合的 TestCase 行** | UI |
| AF | **name_key 提取规则硬编码在解析器**，未来加配置项 | parser |
| AG | **`LogFile.testcase_name` 跨 round 稳定**（HTML 报告层面决定，不可控） | 假设 |
| AH | **v3.3 修正**："TestCase 行"实际是按 `LogFile.testcase_name` 聚合的行（`TestCase` 表为空，实际数据在 `LogFile` 上） | DB / API / UI |
| AI | **v3.3 新增**：`/testcases` 端点返回单 round 的 TestCase 行（按 LogFile.testcase_name 分组） | API |
| AJ | **v3.3 修正**：单 round tab 右表 = TestCase 行（不再用 LogFile 行，与整体 tab 保持一致设计） | UI |
| AK | **v3.3 简化**：1 个 testcase_name = 1 个 LogFile（一对一），多对一情况未来扩展 | 假设 |
| AL | **v3.3 修正**：TestCase 行"审核"按钮跳到该行 LogFile 的 `ReviewDrawer`（不破坏现有审核流程） | UI |
| AM | **v4 - 测试套不单独成行**，只作为 TestCase 行的属性 | UI |
| AN | **v4 - 关联源 = `summary_report.yaml`**（用户确认：正常日志包一定有 YAML）；`LogFile` 不加 `suite_name` 字段，关联在响应时动态计算 | DB / API |
| AO | **v4 - 每个 TestCase 行**带 suite 信息：id / name / result / start_time / end_time / fail_detail_short / logfile_id / logfile_path | API / UI |
| AP | **v4 - suite LogFile 匹配**用 5 步策略（id/desc/name 的 stem 与 LogFile.name 的 stem 比对）；匹配不到时 `logfile_id=null` | API |
| AQ | **v4 - 跨 round suite 关联**：用 round=1 的 suite 作为基准；不一致时用 mode 并告警 | API / UI |
| AR | **v5 - 默认打开 / 发布关闭**：`settings.app_debug_logging: bool = True`；发布设 `LA_APP_DEBUG_LOGGING=false` | config |
| AS | **v5 - 复用 audit_logger + 新增通用 logger**：audit_logger 保持（分析流水线结构化审计），新 logger 覆盖 JSON 树/聚合/S3 探测/API 响应 | 日志设施 |
| AT | **v5 - 日志级别策略**：INFO 关键节点开始/结束；DEBUG 细节数据；WARNING 异常/缺失；ERROR 失败/异常 | 日志规范 |
