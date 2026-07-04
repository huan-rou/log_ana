"""日志浏览 API。

提供目录树导航、文件内容读取、搜索等只读操作。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.services.storage.provider_manager import provider_manager

router = APIRouter()

MAX_FILE_BYTES = 5 * 1024 * 1024    # 5 MB
MAX_LARGE_FILE_BYTES = 20 * 1024 * 1024  # 20 MB for explicit large reads


@router.get("/roots")
async def list_roots():
    """列出所有可用的存储根。"""
    return {"roots": provider_manager.list_providers()}


@router.get("/tree")
async def list_tree(
    provider: str = Query("local"),
    path: str = Query("", description="目录相对路径，空字符串表示根"),
):
    """获取指定路径的目录树（一层展开）。

    URL 示例:
        /api/browse/tree?provider=local&path=
        /api/browse/tree?provider=local&path=1.2.3/nightly/ci-node-01
    """
    try:
        entries = await provider_manager.list_dir(provider, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))

    return {
        "provider": provider,
        "path": path,
        "entries": [
            {
                "name": e.name,
                "type": e.type,
                "size": e.size,
                "modified": e.modified,
                "path": e.path,
            }
            for e in entries
        ],
    }


@router.get("/file")
async def read_file_content(
    provider: str = Query("local"),
    path: str = Query(..., description="文件相对路径"),
    max_bytes: int = Query(MAX_FILE_BYTES, le=MAX_LARGE_FILE_BYTES),
):
    """读取文件内容。

    URL 示例:
        /api/browse/file?provider=local&path=1.2.3/nightly/summary.json
    """
    try:
        fc = await provider_manager.read_file(provider, path, max_bytes=max_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except IOError as e:
        raise HTTPException(500, str(e))

    return {
        "path": fc.path,
        "content_type": fc.content_type,
        "content": fc.content,
        "size": fc.size,
        "encoding": fc.encoding,
        "truncated": fc.truncated,
        "mime_type": fc.mime_type,
        "modified": fc.modified,
    }


@router.get("/file/meta")
async def get_file_meta(
    provider: str = Query("local"),
    path: str = Query(...),
):
    """获取文件元数据（不读内容）。

    URL 示例:
        /api/browse/file/meta?provider=local&path=summary.json
    """
    try:
        fm = await provider_manager.file_meta(provider, path)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(403, str(e))

    return {
        "path": fm.path,
        "content_type": fm.content_type,
        "size": fm.size,
        "modified": fm.modified,
        "mime_type": fm.mime_type,
    }


@router.get("/search")
async def search_files(
    provider: str = Query("local"),
    path: str = Query("", description="搜索根目录"),
    q: str = Query(..., min_length=1, description="搜索关键词"),
    max_results: int = Query(50, le=200),
):
    """在目录内递归搜索文本。

    URL 示例:
        /api/browse/search?provider=local&path=1.2.3/&q=AssertionError
    """
    try:
        matches = await provider_manager.search(
            provider, path, q, max_results=max_results,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "query": q,
        "path": path,
        "total_matches": len(matches),
        "matches": [
            {
                "path": m.path,
                "line_number": m.line_number,
                "line_content": m.line_content,
            }
            for m in matches
        ],
    }


@router.get("/s3-config")
async def get_s3_config():
    """返回当前 S3 公开配置（不含密钥），供前端预填表单。"""
    from app.config import settings
    return {
        "enabled": settings.s3_enabled,
        "bucket": settings.s3_bucket,
        "prefix": settings.s3_prefix,
        "region": settings.s3_region,
        "endpoint_url": settings.s3_endpoint_url,
    }
