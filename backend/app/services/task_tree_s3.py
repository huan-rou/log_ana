"""S3 探测：检查叶子 Id 在 S3 上是否实际有数据。

探测路径：`s3://<bucket>/<prefix>/<version_name>/<leaf_id>/`
判定规则：list_dir 返回的 entries 非空 → 算有数据。

并发：用 asyncio.gather 跑多个 leaf 探测，单个失败不影响其他。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from app.services.storage.provider_manager import provider_manager

logger = logging.getLogger("app.services.task_tree_s3")


def _build_probe_path(version_name: str, leaf_id: str) -> str:
    """构造探测路径。version_name + leaf_id 直接拼接（中间用 /）。"""
    version = (version_name or "").strip("/ ")
    leaf = (leaf_id or "").strip("/ ")
    if not version or not leaf:
        raise ValueError(f"version_name 和 leaf_id 不能为空: {version_name!r}, {leaf_id!r}")
    return f"{version}/{leaf}/"


async def probe_leaf_in_s3(
    version_name: str,
    leaf_id: str,
    *,
    timeout: float = 5.0,
) -> bool:
    """探测单个 leaf 在 S3 上是否有数据。

    Returns:
        True  = 路径下至少有一个子条目（文件或目录）
        False = 路径不存在 / 空 / 探测失败

    Args:
        version_name: 测试版本号（package_version）
        leaf_id: 叶子节点 Id（对应 S3 task_id）
        timeout: 单次探测超时秒数
    """
    path = _build_probe_path(version_name, leaf_id)
    try:
        entries = await asyncio.wait_for(
            provider_manager.list_dir("s3", path),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "[s3.probe] timeout version=%s leaf=%s timeout=%.1fs",
            version_name, leaf_id, timeout,
        )
        return False
    except Exception as exc:
        # provider_manager.list_dir 自身可能 raise（如 S3 配置缺失、bucket 不存在）
        # 探测失败 → 视为无数据
        logger.warning(
            "[s3.probe] failed version=%s leaf=%s err=%s",
            version_name, leaf_id, exc,
        )
        return False

    has_data = bool(entries)
    logger.debug(
        "[s3.probe] version=%s leaf=%s has_data=%s entries=%d",
        version_name, leaf_id, has_data, len(entries) if entries else 0,
    )
    return has_data


async def probe_leaves_in_s3_batch(
    version_name: str,
    leaf_ids: Iterable[str],
    *,
    timeout: float = 5.0,
    concurrency: int = 8,
) -> dict[str, bool]:
    """并发探测多个 leaf。

    Args:
        version_name: 测试版本号
        leaf_ids: 叶子 Id 列表
        timeout: 单次探测超时秒数
        concurrency: 并发上限（Semaphore）

    Returns:
        { leaf_id: has_data } 映射
        探测失败的 leaf 一律算 has_data=False
    """
    sem = asyncio.Semaphore(concurrency)
    results: dict[str, bool] = {}

    async def _one(leaf_id: str) -> None:
        async with sem:
            try:
                results[leaf_id] = await probe_leaf_in_s3(
                    version_name, leaf_id, timeout=timeout
                )
            except Exception as exc:
                # probe_leaf_in_s3 已吞常见异常；这里兜底
                logger.warning(
                    "[s3.probe_batch] unexpected version=%s leaf=%s err=%s",
                    version_name, leaf_id, exc,
                )
                results[leaf_id] = False

    await asyncio.gather(*(_one(lid) for lid in leaf_ids))
    return results

