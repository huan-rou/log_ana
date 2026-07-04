"""本地文件系统 Provider。

读取本地目录中的日志文件，用于开发验证和离线分析。
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import mimetypes

from app.services.storage.base import (
    StorageProvider, DirEntry, FileContent, FileMeta,
)


class LocalProvider(StorageProvider):
    """本地文件系统 Provider。

    用法:
        provider = LocalProvider(root="/data/ci-logs", label="本地日志")
        entries = await provider.list_dir("")
        content = await provider.read_file("1.2.3/nightly/summary.json")
    """

    def __init__(self, root: str, label: str = ""):
        self._root = Path(root).resolve()
        if not self._root.exists():
            raise FileNotFoundError(f"Root directory not found: {self._root}")
        self._label = label or str(self._root)

    @property
    def provider_type(self) -> str:
        return "local"

    @property
    def label(self) -> str:
        return self._label

    def _resolve(self, path: str) -> Path:
        """将相对路径解析为绝对路径，防止路径遍历。"""
        clean = path.lstrip("/").replace("\\", "/")
        if clean in ("", "."):
            return self._root
        resolved = (self._root / clean).resolve()
        # 安全检查：不允许逃逸 root
        if not str(resolved).startswith(str(self._root)):
            raise PermissionError(f"Path traversal blocked: {path}")
        return resolved

    async def list_dir(self, path: str) -> list[DirEntry]:
        target = self._resolve(path)
        if not target.is_dir():
            raise FileNotFoundError(f"Not a directory: {path}")

        entries = []
        try:
            for child in sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name.lower())):
                stat = child.stat()
                relative = str(child.relative_to(self._root)).replace("\\", "/")

                mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

                if child.is_dir():
                    entries.append(DirEntry(
                        name=child.name,
                        type="directory",
                        size=None,
                        modified=mtime,
                        path=relative,
                    ))
                else:
                    entries.append(DirEntry(
                        name=child.name,
                        type="file",
                        size=stat.st_size,
                        modified=mtime,
                        path=relative,
                    ))
        except PermissionError:
            raise PermissionError(f"Cannot read directory: {path}")

        return entries

    async def read_file(self, path: str, max_bytes: int = 5 * 1024 * 1024) -> FileContent:
        target = self._resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"Not a file: {path}")

        stat = target.stat()
        relative = str(target.relative_to(self._root)).replace("\\", "/")
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        content_type = self.guess_content_type(target.name)
        mime_type, _ = mimetypes.guess_type(target.name)

        if content_type in ("image", "binary"):
            # Binary: don't load into content string
            return FileContent(
                path=relative,
                content_type=content_type,
                content=None,
                raw_bytes=None,
                size=stat.st_size,
                encoding="",
                truncated=False,
                mime_type=mime_type or "application/octet-stream",
                modified=mtime,
            )

        # Text file — attempt UTF-8
        try:
            with open(target, "r", encoding="utf-8") as f:
                content = f.read(max_bytes)
                truncated = len(content) >= max_bytes
        except UnicodeDecodeError:
            # Try latin-1 as fallback
            try:
                with open(target, "r", encoding="latin-1") as f:
                    content = f.read(max_bytes)
                    truncated = len(content) >= max_bytes
                    encoding = "latin-1"
            except Exception:
                return FileContent(
                    path=relative,
                    content_type="binary",
                    size=stat.st_size,
                    truncated=False,
                    mime_type="application/octet-stream",
                    modified=mtime,
                )
        else:
            encoding = "utf-8"

        return FileContent(
            path=relative,
            content_type=content_type,
            content=content,
            size=stat.st_size,
            encoding=encoding,
            truncated=truncated,
            mime_type=mime_type or "text/plain",
            modified=mtime,
        )

    async def file_meta(self, path: str) -> FileMeta:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"Not found: {path}")

        stat = target.stat()
        relative = str(target.relative_to(self._root)).replace("\\", "/")
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

        content_type = self.guess_content_type(target.name) if target.is_file() else ""
        mime_type, _ = mimetypes.guess_type(target.name) if target.is_file() else ("", "")

        return FileMeta(
            path=relative,
            content_type=content_type,
            size=stat.st_size if target.is_file() else 0,
            modified=mtime,
            mime_type=mime_type or "",
        )
