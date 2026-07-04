from __future__ import annotations

import importlib
import inspect
import pkgutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Type

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import settings
from app.models.task import AnalysisRule, Category
from rules.base import BaseRule, RuleResult


class RuleRegistry:
    """规则注册中心：扫描 rules/ 目录，发现并加载所有规则类。"""

    def __init__(self):
        self._rules: Dict[str, Type[BaseRule]] = {}
        self._instances: Dict[str, BaseRule] = {}

    async def discover(self):
        """扫描 rules/ 包，发现所有 BaseRule 子类。"""
        self._rules.clear()
        self._instances.clear()

        rules_dir = settings.rules_dir
        if not rules_dir.exists():
            return

        # Ensure rules package is importable
        if "rules" not in sys.modules:
            import rules
        else:
            importlib.reload(sys.modules["rules"])

        # Walk rules package
        rules_pkg = sys.modules["rules"]
        pkg_path = str(rules_dir)

        for _, module_name, is_pkg in pkgutil.iter_modules([pkg_path]):
            if module_name == "base":
                continue
            try:
                full_name = f"rules.{module_name}"
                mod = importlib.import_module(full_name)
                # Find all BaseRule subclasses in this module
                for name, obj in inspect.getmembers(mod, inspect.isclass):
                    if (
                        issubclass(obj, BaseRule)
                        and obj is not BaseRule
                        and not inspect.isabstract(obj)
                    ):
                        instance = obj()
                        self._rules[instance.rule_id] = obj
                        self._instances[instance.rule_id] = instance
            except Exception as e:
                print(f"Warning: Failed to load rule module {module_name}: {e}")

    def get_instance(self, rule_id: str) -> Optional[BaseRule]:
        return self._instances.get(rule_id)

    def get_all(self) -> List[BaseRule]:
        return sorted(
            self._instances.values(),
            key=lambda r: r.priority,
        )

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

            if db_rule:
                db_rule.name = rule.name
                db_rule.category_id = category.id
                db_rule.priority = rule.priority
                db_rule.script_module = f"rules.{rule.rule_id}"
                db_rule.description = rule.description
                db_rule.version = rule.version
                db_rule.enabled = True
            else:
                db_rule = AnalysisRule(
                    rule_id=rule.rule_id,
                    name=rule.name,
                    category_id=category.id,
                    priority=rule.priority,
                    enabled=True,
                    script_module=f"rules.{rule.rule_id}",
                    description=rule.description,
                    version=rule.version,
                )
                db.add(db_rule)

            synced.append(db_rule)

        # Mark rules that no longer exist as disabled
        active_ids = [r.rule_id for r in self.get_all()]
        stale_result = await db.execute(
            select(AnalysisRule).where(AnalysisRule.rule_id.notin_(active_ids))
        )
        for stale in stale_result.scalars():
            stale.enabled = False

        await db.commit()
        return synced


# Global singleton
rule_registry = RuleRegistry()
