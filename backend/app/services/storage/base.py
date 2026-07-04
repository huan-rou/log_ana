"""存储抽象基类。

定义目录导航和文件读取的统一接口，本地文件系统和 S3/RustFS 分别实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DirEntry:
    """目录项。"""
    name: str
    type: str           # "directory" | "file"
    size: int | None = None       # bytes, None for directories
    modified: str | None = None   # ISO 8601
    path: str = ""                # full key relative to provider root

    @property
    def is_dir(self) -> bool:
        return self.type == "directory"

    @property
    def is_file(self) -> bool:
        return self.type == "file"


@dataclass
class FileContent:
    """文件内容。"""
    path: str
    content_type: str    # "text" | "html" | "json" | "yaml" | "xml" | "log" | "binary" | "image"
    content: str | None = None   # text content (text types only)
    raw_bytes: bytes | None = None
    size: int = 0
    encoding: str = "utf-8"
    truncated: bool = False      # True if content exceeded max_bytes
    mime_type: str = ""
    modified: str | None = None


@dataclass
class FileMeta:
    """文件元数据（不读内容）。"""
    path: str
    content_type: str = ""
    size: int = 0
    modified: str | None = None
    mime_type: str = ""


@dataclass
class SearchMatch:
    """搜索结果。"""
    path: str
    line_number: int
    line_content: str
    column: int = 0


class StorageProvider(ABC):
    """存储 Provider 抽象基类。

    所有实现必须保证：
    - 只读操作不可修改源文件
    - 大文件截断时设置 truncated=True
    - 路径分隔符统一为 '/'
    """

    @property
    @abstractmethod
    def provider_type(self) -> str:
        """Provider 类型标识: 'local' | 's3'"""
        ...

    @property
    @abstractmethod
    def label(self) -> str:
        """人类可读的标识，如 '/data/logs' 或 's3://ci-logs'"""
        ...

    @abstractmethod
    async def list_dir(self, path: str) -> list[DirEntry]:
        """列出目录内容。

        Args:
            path: 相对路径，'' 或 '/' 表示根。

        Returns:
            目录项列表。空目录返回 []；不存在的路径 raise FileNotFoundError。
        """
        ...

    @abstractmethod
    async def read_file(self, path: str, max_bytes: int = 5 * 1024 * 1024) -> FileContent:
        """读取文件内容。

        Args:
            path: 相对文件路径
            max_bytes: 最大读取字节数，超出则截断并设置 truncated=True

        Returns:
            FileContent。文件不存在 raise FileNotFoundError。
        """
        ...

    @abstractmethod
    async def file_meta(self, path: str) -> FileMeta:
        """获取文件元数据（不读取内容）。"""
        ...

    async def search(
        self, path: str, query: str, max_results: int = 50, case_sensitive: bool = False
    ) -> list[SearchMatch]:
        """在目录内搜索文本。

        默认实现：递归遍历文件并 grep。Provider 可覆盖为服务端搜索。
        """
        results: list[SearchMatch] = []

        async def _search_dir(dir_path: str):
            if len(results) >= max_results:
                return
            try:
                entries = await self.list_dir(dir_path)
            except (FileNotFoundError, PermissionError):
                return

            for entry in entries:
                if len(results) >= max_results:
                    return
                if entry.is_dir:
                    await _search_dir(entry.path)
                elif entry.is_file and self._is_text_file(entry.name):
                    try:
                        fc = await self.read_file(entry.path, max_bytes=2 * 1024 * 1024)
                        if fc.content:
                            search_text = fc.content if case_sensitive else fc.content.lower()
                            q = query if case_sensitive else query.lower()
                            for i, line in enumerate(search_text.split("\n"), 1):
                                if q in line:
                                    results.append(SearchMatch(
                                        path=entry.path,
                                        line_number=i,
                                        line_content=line[:500],
                                    ))
                                    if len(results) >= max_results:
                                        return
                    except Exception:
                        continue

        await _search_dir(path)
        return results

    @staticmethod
    def _is_text_file(filename: str) -> bool:
        """判断文件名是否对应文本文件。"""
        text_exts = {
            ".json", ".yaml", ".yml", ".xml", ".html", ".htm",
            ".log", ".txt", ".py", ".js", ".ts", ".vue", ".css",
            ".md", ".cfg", ".conf", ".ini", ".toml", ".env",
            ".csv", ".tsv", ".irpx", ".summary",
        }
        name = filename.lower()
        return any(name.endswith(ext) for ext in text_exts)

    @staticmethod
    def guess_content_type(filename: str) -> str:
        """根据文件名猜测内容类型。"""
        name = filename.lower()
        if name.endswith(".json"):
            return "json"
        if name.endswith((".yaml", ".yml")):
            return "yaml"
        if name.endswith(".xml"):
            return "xml"
        if name.endswith((".html", ".htm")):
            return "html"
        if name.endswith(".log"):
            return "log"
        if name.endswith((".txt", ".md", ".cfg", ".conf", ".ini", ".env", ".py")):
            return "text"
        if name.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico")):
            return "image"
        if name.endswith((".zip", ".gz", ".tar", ".bz2", ".7z")):
            return "binary"
        return "binary"
