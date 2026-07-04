from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List


class FileFetcher:
    """按需获取规则所需的附加文件。

    根据日志内容中的文件引用（路径、配置文件名等），
    在工作区和上传目录中查找并读取文件内容。
    """

    # Patterns for detecting file references in log messages
    FILE_REF_PATTERNS = [
        re.compile(r'(?:config|conf|cfg)[/\s]*[:=]?\s*([^\s,;]+\.(?:ya?ml|json|toml|ini|conf|cfg))', re.IGNORECASE),
        re.compile(r'(?:file|path)[/\s]*[:=]?\s*([^\s,;]+)', re.IGNORECASE),
        re.compile(r'(?:reading|loading|opening|writing)\s+([^\s,;]+)', re.IGNORECASE),
        re.compile(r'([/\w.-]+\.(?:ya?ml|json|toml|ini|env|txt|log|cfg|conf))\b', re.IGNORECASE),
    ]

    def __init__(self, upload_dir: str, workspace_dir: str):
        self.upload_dir = Path(upload_dir)
        self.workspace_dir = Path(workspace_dir)

    async def fetch_all(self, log_entries: list) -> Dict[str, str]:
        """从日志条目中检测文件引用并按需读取。

        Returns:
            {filename: content} 字典
        """
        referenced = set()

        for entry in log_entries:
            text = f"{entry.message or ''} {entry.raw_line or ''}"
            for pattern in self.FILE_REF_PATTERNS:
                for m in pattern.finditer(text):
                    filename = m.group(1).strip("'\"")
                    referenced.add(filename)

        return await self._read_files(referenced)

    async def _read_files(self, filenames: set) -> Dict[str, str]:
        """尝试在多个目录中定位并读取文件。"""
        result = {}
        search_dirs = [
            self.upload_dir,
            self.workspace_dir,
            self.upload_dir.parent,  # parent data dir
        ]

        for fname in filenames:
            # Normalize: strip leading/trailing slashes
            clean = fname.strip("/\\").lstrip("./")
            basename = Path(clean).name

            for search_dir in search_dirs:
                if not search_dir.exists():
                    continue

                # Strategy 1: exact relative path
                candidate = search_dir / clean
                if candidate.is_file():
                    result[basename] = self._safe_read(candidate)
                    break

                # Strategy 2: recursive search by basename
                for found in search_dir.rglob(basename):
                    if found.is_file():
                        result[basename] = self._safe_read(found)
                        break
                if basename in result:
                    break

        return result

    @staticmethod
    def _safe_read(path: Path, max_bytes: int = 1024 * 1024) -> str:
        """安全读取文件内容（限制大小）。"""
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(max_bytes)
        except Exception:
            return ""
