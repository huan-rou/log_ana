"""RustFS / S3 Provider。

通过 S3 兼容 API 读写日志文件，用于生产环境的 RustFS 后端。
"""

from __future__ import annotations

from datetime import datetime, timezone
import mimetypes

from app.services.storage.base import (
    StorageProvider, DirEntry, FileContent, FileMeta,
)


class RustFSProvider(StorageProvider):
    """S3 兼容的 RustFS Provider。

    使用 aiobotocore 做异步 S3 调用。

    用法:
        provider = RustFSProvider(
            bucket="ci-logs",
            prefix="automation",
            endpoint_url="https://s3.example.com",
            access_key="...",
            secret_key="...",
            label="s3://ci-logs/automation",
        )
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "",
        endpoint_url: str = "",
        access_key: str = "",
        secret_key: str = "",
        region: str = "us-east-1",
        label: str = "",
    ):
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._endpoint_url = endpoint_url
        self._access_key = access_key
        self._secret_key = secret_key
        self._region = region
        self._label = label or f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"

        self._client = None

    @property
    def provider_type(self) -> str:
        return "s3"

    @property
    def label(self) -> str:
        return self._label

    def _s3_key(self, path: str) -> str:
        """将相对路径转换为完整的 S3 key。"""
        clean = path.strip("/")
        if self._prefix:
            return f"{self._prefix}/{clean}" if clean else self._prefix
        return clean

    def _relative_key(self, s3_key: str) -> str:
        """从 S3 key 中剥离 prefix，得到相对路径。"""
        if self._prefix:
            prefix_slash = self._prefix + "/"
            if s3_key.startswith(prefix_slash):
                return s3_key[len(prefix_slash):]
            elif s3_key == self._prefix:
                return ""
        return s3_key

    async def _get_client(self):
        """懒加载 S3 客户端。"""
        if self._client is None:
            try:
                from aiobotocore.session import get_session
            except ImportError:
                raise ImportError(
                    "aiobotocore is required for S3 support. "
                    "Install with: pip install aiobotocore"
                )

            session = get_session()
            self._client = await session.create_client(
                "s3",
                endpoint_url=self._endpoint_url or None,
                aws_access_key_id=self._access_key or None,
                aws_secret_access_key=self._secret_key or None,
                region_name=self._region,
            ).__aenter__()
        return self._client

    async def close(self):
        if self._client:
            await self._client.__aexit__(None, None, None)
            self._client = None

    async def list_dir(self, path: str) -> list[DirEntry]:
        client = await self._get_client()
        s3_prefix = self._s3_key(path)

        # Ensure prefix ends with '/' to list directory contents, not prefix itself
        if s3_prefix and not s3_prefix.endswith("/"):
            s3_prefix += "/"

        # If root (no prefix), we want to list common prefixes
        try:
            paginator = client.get_paginator("list_objects_v2")
            entries: dict[str, DirEntry] = {}

            # First pass: collect common prefixes (directories)
            async for page in paginator.paginate(
                Bucket=self._bucket,
                Prefix=s3_prefix,
                Delimiter="/",
            ):
                # Subdirectories
                for cp in page.get("CommonPrefixes", []):
                    prefix_key = cp["Prefix"]
                    # Extract directory name
                    dir_path = self._relative_key(prefix_key)
                    dir_name = dir_path.rstrip("/").split("/")[-1]

                    entry_key = f"dir:{dir_name}"
                    if entry_key not in entries:
                        # 去掉尾部斜杠：拼接子路径时避免出现 "//"（RustFS 会报 InvalidArgument）
                        entries[entry_key] = DirEntry(
                            name=dir_name,
                            type="directory",
                            path=dir_path.rstrip("/"),
                        )

                # Files
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if key == s3_prefix:
                        continue  # Skip the directory marker itself

                    rel = self._relative_key(key)
                    filename = rel.split("/")[-1]
                    if not filename:
                        continue

                    mtime = obj.get("LastModified")
                    if mtime:
                        mtime = mtime.isoformat()

                    entry_key = f"file:{filename}"
                    entries[entry_key] = DirEntry(
                        name=filename,
                        type="file",
                        size=obj.get("Size"),
                        modified=mtime,
                        path=rel,
                    )

            # Sort: directories first, then files, both alphabetically
            sorted_entries = sorted(
                entries.values(),
                key=lambda e: (e.is_file, e.name.lower()),
            )
            return sorted_entries

        except Exception as e:
            error_msg = str(e)
            if "NoSuchBucket" in error_msg:
                raise FileNotFoundError(f"Bucket not found: {self._bucket}")
            if "AccessDenied" in error_msg or "Forbidden" in error_msg:
                raise PermissionError(f"Access denied: s3://{self._bucket}/{s3_prefix}")
            raise

    async def read_file(self, path: str, max_bytes: int = 5 * 1024 * 1024) -> FileContent:
        client = await self._get_client()
        s3_key = self._s3_key(path)

        # First get metadata
        try:
            head = await client.head_object(Bucket=self._bucket, Key=s3_key)
        except Exception as e:
            error_msg = str(e)
            if "NoSuchKey" in error_msg or "404" in error_msg:
                raise FileNotFoundError(f"Object not found: s3://{self._bucket}/{s3_key}")
            if "AccessDenied" in error_msg:
                raise PermissionError(f"Access denied: s3://{self._bucket}/{s3_key}")
            raise

        content_length = int(head.get("ContentLength", 0))
        mime_type = head.get("ContentType", "")
        mtime = head.get("LastModified")
        if mtime:
            mtime = mtime.isoformat()

        filename = s3_key.split("/")[-1]
        content_type = self.guess_content_type(filename)

        if content_type in ("image", "binary"):
            return FileContent(
                path=self._relative_key(s3_key),
                content_type=content_type,
                content=None,
                size=content_length,
                truncated=False,
                mime_type=mime_type,
                modified=mtime,
            )

        # Read text content
        try:
            resp = await client.get_object(
                Bucket=self._bucket,
                Key=s3_key,
                Range=f"bytes=0-{max_bytes - 1}",
            )
            body = await resp["Body"].read()
            raw_bytes = body if isinstance(body, bytes) else body.encode("utf-8")
            truncated = len(raw_bytes) >= max_bytes

            # Decode
            try:
                content = raw_bytes.decode("utf-8")
                encoding = "utf-8"
            except UnicodeDecodeError:
                content = raw_bytes.decode("latin-1")
                encoding = "latin-1"

            return FileContent(
                path=self._relative_key(s3_key),
                content_type=content_type,
                content=content,
                size=content_length,
                encoding=encoding,
                truncated=truncated,
                mime_type=mime_type or "text/plain",
                modified=mtime,
            )

        except Exception as e:
            raise IOError(f"Failed to read s3://{self._bucket}/{s3_key}: {e}")

    async def file_meta(self, path: str) -> FileMeta:
        client = await self._get_client()
        s3_key = self._s3_key(path)

        try:
            head = await client.head_object(Bucket=self._bucket, Key=s3_key)
        except Exception as e:
            error_msg = str(e)
            if "NoSuchKey" in error_msg or "404" in error_msg:
                raise FileNotFoundError(f"Object not found: s3://{self._bucket}/{s3_key}")
            raise

        content_length = int(head.get("ContentLength", 0))
        mime_type = head.get("ContentType", "")
        mtime = head.get("LastModified")
        if mtime:
            mtime = mtime.isoformat()

        filename = s3_key.split("/")[-1]
        content_type = self.guess_content_type(filename)

        return FileMeta(
            path=self._relative_key(s3_key),
            content_type=content_type,
            size=content_length,
            modified=mtime,
            mime_type=mime_type or "",
        )
