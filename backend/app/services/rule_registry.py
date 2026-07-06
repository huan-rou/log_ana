from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Type

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.task import AnalysisRule, Category
from rules.base import BaseRule, RuleResult


# (包名, 物理路径, 来源标签)
_RULE_PACKAGES: List[Tuple[str, str, str]] = [
    ("rules",      "./rules",     "builtin"),
    ("rules.user", "./rules/user", "user"),
]


class RuleRegistry:
    """规则注册中心：扫描 rules/ 与 rules/user/，发现并加载所有规则类。"""

    def __init__(self):
        self._rules: Dict[str, Type[BaseRule]] = {}
        self._instances: Dict[str, BaseRule] = {}
        # 额外记录每条规则的来源（builtin / user）
        self._sources: Dict[str, str] = {}

    async def discover(self):
        """扫描多个规则包，发现所有 BaseRule 子类。"""
        self._rules.clear()
        self._instances.clear()
        self._sources.clear()

        for pkg_name, rel_path, source in _RULE_PACKAGES:
            # rel_path 是相对 rules_dir 的子路径
            if rel_path == "./rules":
                rules_dir = Path(settings.rules_dir)
            elif rel_path == "./rules/user":
                rules_dir = Path(settings.rules_dir) / "user"
            else:
                rules_dir = Path(settings.rules_dir) / Path(rel_path).relative_to("rules")
            if not rules_dir.exists():
                continue

            # 确保父包已加载
            try:
                if pkg_name in sys.modules:
                    importlib.reload(sys.modules[pkg_name])
                else:
                    importlib.import_module(pkg_name)
            except Exception as e:
                print(f"Warning: failed to import package {pkg_name}: {e}")
                continue

            for _, module_name, is_pkg in pkgutil.iter_modules([str(rules_dir)]):
                if module_name == "base" or module_name.startswith("_"):
                    continue
                try:
                    full_name = f"{pkg_name}.{module_name}"
                    mod = importlib.import_module(full_name)
                    for name, obj in inspect.getmembers(mod, inspect.isclass):
                        if (
                            issubclass(obj, BaseRule)
                            and obj is not BaseRule
                            and not inspect.isabstract(obj)
                            and obj.__module__ == full_name
                        ):
                            instance = obj()
                            self._rules[instance.rule_id] = obj
                            self._instances[instance.rule_id] = instance
                            self._sources[instance.rule_id] = source
                except Exception as e:
                    print(f"Warning: Failed to load rule module {module_name} from {pkg_name}: {e}")

    def get_instance(self, rule_id: str) -> Optional[BaseRule]:
        return self._instances.get(rule_id)

    def get_source(self, rule_id: str) -> str:
        """返回规则的来源 builtin / user；未知返回 'unknown'。"""
        return self._sources.get(rule_id, "unknown")

    def is_user_rule(self, rule_id: str) -> bool:
        return self.get_source(rule_id) == "user"

    def get_all(self) -> List[BaseRule]:
        return sorted(
            self._instances.values(),
            key=lambda r: r.priority,
        )

    def get_user_module_path(self, rule_id: str) -> str:
        """返回 user 规则在磁盘上的 .py 路径（用于删除）。"""
        if not self.is_user_rule(rule_id):
            raise ValueError(f"{rule_id} 不是 user 规则")
        return str(Path(settings.rules_dir) / "user" / f"{rule_id}.py")

    async def sync_to_db(self, db: AsyncSession) -> List[AnalysisRule]:
        """将发现的规则同步到数据库。

        创建不存在的类别和规则记录，标记缺失规则为禁用。
        """
        synced = []

        for rule in self.get_all():
            # Ensure category exists（支持 "大类/子类" 路径）
            from app.services.rule_executor import _get_category_id
            category_id = await _get_category_id(db, rule.category)
            category = (await db.execute(
                select(Category).where(Category.id == category_id)
            )).scalar_one()

            # Upsert rule
            rule_result = await db.execute(
                select(AnalysisRule).where(AnalysisRule.rule_id == rule.rule_id)
            )
            db_rule = rule_result.scalar_one_or_none()

            # 按来源拼 script_module
            script_module = (
                f"rules.user.{rule.rule_id}"
                if self.is_user_rule(rule.rule_id)
                else f"rules.{rule.rule_id}"
            )

            if db_rule:
                db_rule.name = rule.name
                db_rule.category_id = category.id
                db_rule.priority = rule.priority
                db_rule.script_module = script_module
                db_rule.description = rule.description
                db_rule.version = rule.version
                # builtin 重新出现时启用；user 规则尊重 db 中 enabled（不被 sync 覆盖）
                if not self.is_user_rule(rule.rule_id):
                    db_rule.enabled = True
            else:
                db_rule = AnalysisRule(
                    rule_id=rule.rule_id,
                    name=rule.name,
                    category_id=category.id,
                    priority=rule.priority,
                    enabled=True,
                    script_module=script_module,
                    description=rule.description,
                    version=rule.version,
                )
                db.add(db_rule)

            synced.append(db_rule)

        # builtin 缺失时标记禁用（user 规则不归 sync 管）
        active_builtin_ids = [
            r.rule_id for r in self.get_all()
            if not self.is_user_rule(r.rule_id)
        ]
        if active_builtin_ids:
            stale_result = await db.execute(
                select(AnalysisRule).where(
                    AnalysisRule.rule_id.notin_(active_builtin_ids),
                    AnalysisRule.script_module.notlike("rules.user.%"),
                )
            )
            for stale in stale_result.scalars():
                stale.enabled = False
        else:
            # 没有 builtin 时仍要把所有非 user 的禁用
            stale_result = await db.execute(
                select(AnalysisRule).where(
                    AnalysisRule.script_module.notlike("rules.user.%")
                )
            )
            for stale in stale_result.scalars():
                stale.enabled = False

        await db.commit()
        return synced


# Global singleton
rule_registry = RuleRegistry()

