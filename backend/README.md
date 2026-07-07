# Backend — Log Analyzer

FastAPI + SQLAlchemy 2.0 async (aiosqlite) + Pydantic v2。
日志解析 / 失败检测 / 规则分类的完整 pipeline。

## 目录

```
backend/
├── app/
│   ├── api/           # FastAPI routers — 每个文件挂载到 /api/<name>
│   │   ├── analysis.py    # /api/analysis — 分析流水线 / rerun / batch
│   │   ├── mapping.py     # /api/mapping — TestVersion + JSON 树管理
│   │   ├── review.py      # /api/review — 人工审核 / 覆盖 / 归档
│   │   ├── rules.py       # /api/rules — 规则 CRUD
│   │   ├── tasks.py       # /api/tasks — Task CRUD
│   │   ├── logs.py        # /api/logs — LogEntry 浏览
│   │   ├── feedback.py    # /api/feedback — Feedback 提交
│   │   ├── browse.py      # /api/browse — S3 浏览
│   │   ├── audit.py       # /api/audit — 审计日志查询
│   │   ├── auth.py        # /api/auth — 登录 / 鉴权
│   │   └── user CRUD via /api/users
│   ├── models/        # SQLAlchemy ORM 模型
│   │   ├── task.py        # Task / LogFile / LogEntry / FailureEvent / AnalysisResult
│   │   ├── mapping.py     # TestVersion / TestPurpose / TaskReference
│   │   ├── task_tree.py   # TestTaskTree / TestTaskNode（v5）
│   │   ├── user.py
│   │   └── rule.py
│   ├── services/      # 业务逻辑层
│   │   ├── log_parser.py            # HTML / log → LogEntry
│   │   ├── failure_detector.py      # LogEntry → FailureEvent
│   │   ├── rule_executor.py         # FailureEvent → AnalysisResult
│   │   ├── task_tree.py             # JSON 解析 + 跨 round 冲突检查
│   │   ├── task_tree_s3.py          # S3 叶子路径探测
│   │   ├── task_tree_aggregate.py   # 跨 round 节点 / 用例聚合
│   │   ├── summary_report.py        # YAML 加载 + suite/case 关联
│   │   ├── rule_registry.py         # builtin 规则动态加载
│   │   ├── rule_template.py         # 用户规则模板渲染
│   │   ├── file_fetcher.py          # extra_files 拉取
│   │   └── storage/                 # S3 / 本地 provider
│   ├── core/          # 横切关注
│   │   ├── audit_logger.py          # 结构化审计日志（pipeline / rule / classify）
│   │   └── logging_setup.py         # 通用 logging setup
│   ├── auth.py        # role-based 鉴权（admin / reviewer / analyst）
│   ├── config.py      # pydantic-settings
│   ├── database.py    # async engine + init_db + manual migrations
│   └── main.py        # FastAPI app + lifespan
├── rules/             # 内置规则（Python 模块动态加载）
├── tests/             # pytest 套件
└── pyproject.toml
```

## 跑起来

```bash
cd backend
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"

# 改 .env 或设环境变量
LA_S3_BUCKET=ci-logs
LA_S3_PREFIX=automation
LA_S3_ACCESS_KEY=...
LA_S3_SECRET_KEY=...
LA_S3_ENDPOINT_URL=http://localhost:9000   # RustFS local dev

.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

API: <http://localhost:8000/docs>

## 关键 API 一览

### 分析流水线

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/analysis/{id}/run` | POST | 启动单任务后台分析流水线 |
| `/api/analysis/run_batch` | POST | 批量启动（≤200 个） |
| `/api/analysis/{id}/rerun` | POST | 完整重分析（清旧数据 + 后台重跑） |
| `/api/analysis/rerun_batch` | POST | 批量完整重分析 |
| `/api/analysis/{id}/files` | GET | 列文件分析结果（含 `summary_report` 元数据） |
| `/api/analysis/{id}/results` | GET | 列分析结果（按 category / is_fallback 过滤） |
| `/api/analysis/{id}/dashboard` | GET | 看板数据（类别分布 / 反馈统计 / 审核进度） |
| `/api/analysis/{id}/report` | GET | 报告统计（套 / 用例 / 自动分析率） |
| `/api/analysis/{id}/trees` | GET | 该 task 所属版本的所有轮次 |
| `/api/analysis/{id}/tree` | GET | 单轮次树（默认用 task.tree_node_id 找） |
| `/api/analysis/{id}/aggregate` | GET | 跨 round 按 name_key 聚合 |
| `/api/analysis/{id}/aggregate/testcases` | GET | 整体视图右表 |

### 映射管理（v5）

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/mapping/versions` | GET / POST | 测试版本 CRUD |
| `/api/mapping/versions/{id}/discover` | POST | S3 自动发现 task_id 列表 |
| `/api/mapping/purposes` | GET / POST | 测试目的 + 关联 task_refs |
| `/api/mapping/versions/{id}/tree?mode=preview` | POST | JSON 预览（返回嵌套树 + 冲突 + S3 探测） |
| `/api/mapping/versions/{id}/tree/append` | POST | 追加轮次（备注必填） |
| `/api/mapping/versions/{id}/trees` | GET | 轮次列表 |
| `/api/mapping/versions/{id}/trees/{round}` | GET | 取轮次（返回嵌套树） |
| `/api/mapping/versions/{id}/trees/{round}` | DELETE | 删轮次（Task 保留，tree_node_id 置 NULL） |
| `/api/mapping/versions/{id}/trees/{round}/create_tasks` | POST | 批量建任务（created / linked / skipped） |
| `/api/mapping/versions/{id}/trees/{round}/note` | PUT | 改备注 |

### 审核 / 覆盖

| 路径 | 方法 | 说明 |
|---|---|---|
| `/api/review/files/{id}/confirm` | POST | 确认文件的自动结论 |
| `/api/review/files/{id}/override` | POST | 人工覆盖（指定 category_id + 行号 + evidence） |
| `/api/review/files/{id}/reset` | POST | 重置回 pending |
| `/api/review/overridden` | GET | 已覆盖列表 |

### 规则 / 任务 / 文件

- `/api/rules` — builtin / 用户规则的 CRUD + publish
- `/api/tasks` — Task 列表 / 创建（upload 或 S3）/ 详情 / 删除 / 摘要
- `/api/feedback` — 用户反馈

## 关键设计判断

### `parse_task_tree` 名字聚合

```python
"TC_id_1"           -> "TC_id"            # 删最后一段
"TC_id_1_a8b3c"     -> "TC_id_1"          # 多层后缀
"BGP0_reRun6458"    -> "BGP0"             # 切错最后一段（接受误伤）
```

### 完整重分析：`_reset_task_data` 顺序

```
Feedback → AnalysisResult → FailureEvent → LogEntry / TestCase
        → ArchivedReview / HighValueRecord → LogFile
```

`LogFile` 必须删（`task_id` + `file_path` 没有 unique 约束；只 reset review_status 会留下旧 + 新两份 row）。

### 鉴权（`app/auth.py`）

| 角色 | 能力 |
|---|---|
| `admin` | 全部 + 用户管理 |
| `reviewer` | 启动任务 + 审核 + 覆盖 + 写规则 |
| `analyst` | 查看 + 反馈（不能启动任务） |

`require_start_task` / `require_write_review` / etc. 装饰器。

## 测试

```bash
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m pytest tests/test_task_tree.py -v
.venv\Scripts\python.exe -m pytest -k "test_rerun" -v
```

测试用 `tests/conftest.py` 的 in-memory SQLite fixture，跑得快。当前 ~80 个用例。

## 自定义内置规则

规则 = 后端 `backend/rules/` 下的 Python 模块，需要继承 `BaseRule` (在 `rules/base.py`)：

```python
# rules/my_rule.py
from rules.base import BaseRule, RuleResult

class MyRule(BaseRule):
    rule_id = "network_timeout"
    name = "网络超时检测"
    version = "1.0"
    priority = 100

    async def evaluate(self, ctx: RuleContext) -> RuleResult:
        if "ConnectionTimeout" in ctx.traceback:
            return RuleResult(
                matched=True,
                category="网络异常",
                confidence=0.95,
                evidence="检测到 ConnectionTimeout 异常",
            )
        return RuleResult(matched=False)
```

启动时 `rule_registry.discover()` 自动加载；改代码不用重启 v5 之前的 pipeline；rerun 即可生效。

## 数据库迁移

`init_db()` 启动时：
- `Base.metadata.create_all` 创建不存在的表
- `_apply_manual_migrations()` 对 SQLite 老库手动 ALTER TABLE 补列

新增字段时，往 `_apply_manual_migrations()` 列表里加一条 `ALTER TABLE` 即可（生产环境长期应改用 Alembic 但小项目就这样）。
