"""存储 Provider 管理器。

管理多个 StorageProvider 实例（本地 + S3），
对外提供按 provider_id 路由请求的统一接口。
"""

from __future__ import annotations

from pathlib import Path

from app.services.storage.base import StorageProvider
from app.services.storage.local_provider import LocalProvider


class ProviderManager:
    """管理多个存储 Provider。

    用法:
        mgr = ProviderManager()
        mgr.register(LocalProvider(root="/data/sample-logs", label="示例日志"))
        entries = await mgr.list_dir("local", "1.2.3/")
        content = await mgr.read_file("local", "1.2.3/summary.json")
    """

    def __init__(self):
        self._providers: dict[str, StorageProvider] = {}

    def register(self, provider: StorageProvider):
        self._providers[provider.provider_type] = provider

    def unregister(self, provider_type: str):
        self._providers.pop(provider_type, None)

    def get(self, provider_type: str) -> StorageProvider | None:
        return self._providers.get(provider_type)

    def list_providers(self) -> list[dict]:
        return [
            {
                "id": p.provider_type,
                "label": p.label,
                "type": p.provider_type,
            }
            for p in self._providers.values()
        ]

    def get_default(self) -> StorageProvider | None:
        """返回第一个注册的 provider（如果没有指定则用 local）。"""
        if "local" in self._providers:
            return self._providers["local"]
        if self._providers:
            return next(iter(self._providers.values()))
        return None

    async def list_dir(self, provider_type: str, path: str) -> list:
        provider = self._get_or_raise(provider_type)
        return await provider.list_dir(path)

    async def read_file(self, provider_type: str, path: str, max_bytes: int = 5 * 1024 * 1024):
        provider = self._get_or_raise(provider_type)
        return await provider.read_file(path, max_bytes=max_bytes)

    async def file_meta(self, provider_type: str, path: str):
        provider = self._get_or_raise(provider_type)
        return await provider.file_meta(path)

    async def search(self, provider_type: str, path: str, query: str, max_results: int = 50):
        provider = self._get_or_raise(provider_type)
        return await provider.search(path, query, max_results=max_results)

    async def close_all(self):
        """关闭所有 Provider 的连接。"""
        for provider in self._providers.values():
            if hasattr(provider, "close"):
                try:
                    await provider.close()
                except Exception:
                    pass
        self._providers.clear()

    def _get_or_raise(self, provider_type: str) -> StorageProvider:
        provider = self._providers.get(provider_type)
        if not provider:
            raise ValueError(f"Unknown provider type: {provider_type}. Available: {list(self._providers)}")
        return provider


# 全局单例
provider_manager = ProviderManager()


# ── 初始化 ──

def init_providers():
    """从配置初始化存储 Provider。

    在应用启动时调用，注册本地目录和 S3 后端。
    始终确保至少有一个 local provider 作为后备。
    """
    from app.config import settings

    upload_path = Path(settings.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)

    # ── 始终注册本地 provider ──
    label = "本地上传"
    try:
        if any(upload_path.iterdir()):
            label = f"本地上传 ({upload_path})"
    except Exception:
        pass
    provider_manager.register(
        LocalProvider(root=str(upload_path), label=label)
    )

    # ── S3 provider ──
    if settings.s3_enabled and settings.s3_bucket:
        from app.services.storage.rustfs_provider import RustFSProvider
        try:
            s3_provider = RustFSProvider(
                bucket=settings.s3_bucket,
                prefix=settings.s3_prefix,
                endpoint_url=settings.s3_endpoint_url,
                access_key=settings.s3_access_key,
                secret_key=settings.s3_secret_key,
                region=settings.s3_region,
                label=f"s3://{settings.s3_bucket}/{settings.s3_prefix}" if settings.s3_prefix else f"s3://{settings.s3_bucket}",
            )
            provider_manager.register(s3_provider)
        except Exception as e:
            import logging
            logging.warning(f"Failed to register S3 provider: {e}")


async def shutdown_providers():
    """关闭所有注册的存储 Provider。在应用关闭时调用。"""
    await provider_manager.close_all()
