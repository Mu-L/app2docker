"""
应用版本与 Gitee Release 更新检查。

- 当前版本：backend/VERSION（单行语义化版本号）
- 远端：Gitee API v5 releases 列表，取 tag/name 中语义版本最大的一条
- 进程内缓存：环境变量 GITEE_UPDATE_CACHE_SECONDS（默认 600，≤0 表示关闭缓存）
"""

from __future__ import annotations

import copy
import json
import os
import re
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

# 与仓库 Gitee Release 对应：gitee.com/numen06/app2docker
GITEE_OWNER = "numen06"
GITEE_REPO = "app2docker"
DEFAULT_VERSION = "1.0.0"

GITEE_RELEASES_LIST_API = (
    f"https://gitee.com/api/v5/repos/{GITEE_OWNER}/{GITEE_REPO}/releases"
    "?per_page=30&page=1"
)

_release_cache: dict | None = None
_release_cache_at: float = 0.0


def _gitee_release_cache_ttl_seconds() -> float:
    raw = os.environ.get("GITEE_UPDATE_CACHE_SECONDS", "600")
    try:
        return float(raw)
    except ValueError:
        return 600.0


def _version_file_path() -> Path:
    return Path(__file__).resolve().parent / "VERSION"


def get_version() -> str:
    """读取当前应用版本（VERSION 文件首行）。"""
    path = _version_file_path()
    try:
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text.splitlines()[0].strip()
    except OSError:
        pass
    return DEFAULT_VERSION


def normalize_version(version: str) -> str:
    """标准化版本号，兼容 v1.2.3 -> 1.2.3。"""
    if not isinstance(version, str):
        return ""
    normalized = version.strip()
    if normalized.lower().startswith("v"):
        normalized = normalized[1:]
    return normalized.strip()


def version_to_parts(version: str) -> list[int]:
    """提取版本中的数字段，用于比较。"""
    normalized = normalize_version(version)
    if not normalized:
        return []
    return [int(item) for item in re.findall(r"\d+", normalized)]


def compare_versions(current: str, latest: str) -> int:
    """
    比较两个版本号。

    Returns:
        -1: current < latest
         0: current == latest
         1: current > latest
    """
    current_parts = version_to_parts(current)
    latest_parts = version_to_parts(latest)
    max_len = max(len(current_parts), len(latest_parts))
    current_parts.extend([0] * (max_len - len(current_parts)))
    latest_parts.extend([0] * (max_len - len(latest_parts)))

    if current_parts < latest_parts:
        return -1
    if current_parts > latest_parts:
        return 1
    return 0


def summarize_release_body(body: str | None, max_len: int = 200) -> str:
    """将 Gitee Release 正文压缩为单行摘要。"""
    if not isinstance(body, str) or not body.strip():
        return ""
    text = " ".join(body.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _pick_highest_semver_release(releases: list) -> dict:
    """从 Gitee 返回的 Release 列表中选出语义版本号最大的一条。"""
    best: dict = {}
    best_ver = ""
    for item in releases:
        if not isinstance(item, dict):
            continue
        tag_name = item.get("tag_name") or item.get("name") or ""
        ver = normalize_version(tag_name)
        if not ver or not version_to_parts(ver):
            continue
        if not best_ver or compare_versions(best_ver, ver) < 0:
            best_ver = ver
            best = item
    return best


def fetch_latest_gitee_release(force_refresh: bool = False) -> dict:
    """获取 Gitee 上语义版本号最大的 Release（带短时缓存，减轻对 Gitee 的请求压力）。"""
    global _release_cache, _release_cache_at
    ttl = _gitee_release_cache_ttl_seconds()
    now = time.monotonic()
    if (
        ttl > 0
        and not force_refresh
        and _release_cache is not None
        and (now - _release_cache_at) < ttl
    ):
        return copy.deepcopy(_release_cache)

    request = Request(
        GITEE_RELEASES_LIST_API,
        headers={"User-Agent": "app2docker-version-checker"},
    )
    with urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
        if isinstance(payload, list) and payload:
            release = _pick_highest_semver_release(payload)
        else:
            release = {}
    if ttl > 0:
        _release_cache = copy.deepcopy(release)
        _release_cache_at = now
    return copy.deepcopy(release)


def check_gitee_update(force_refresh: bool = False) -> dict:
    """
    检查是否有新版本。

    Returns:
        统一结构；失败时 success=False 并带 message。
    """
    current_version = normalize_version(get_version())
    result = {
        "current_version": current_version,
        "latest_version": None,
        "has_update": False,
        "release_url": None,
        "release_name": None,
        "release_body": None,
        "release_body_summary": None,
        "success": True,
        "message": "",
    }

    try:
        release = fetch_latest_gitee_release(force_refresh=force_refresh)
        tag_name = release.get("tag_name") or release.get("name") or ""
        latest_version = normalize_version(tag_name)
        # Gitee OpenAPI 的 release 条目通常不含 html_url，需按标签拼接发行页
        raw_url = release.get("html_url")
        if isinstance(raw_url, str) and raw_url.strip():
            release_url = raw_url.strip()
        elif tag_name.strip():
            release_url = (
                f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/releases/tag/"
                f"{quote(tag_name.strip(), safe='')}"
            )
        else:
            release_url = f"https://gitee.com/{GITEE_OWNER}/{GITEE_REPO}/releases"
        release_name = release.get("name") or tag_name
        raw_body = release.get("body")
        if isinstance(raw_body, str) and raw_body.strip():
            result["release_body"] = raw_body.strip()
            result["release_body_summary"] = summarize_release_body(raw_body) or None

        result["latest_version"] = latest_version or None
        result["release_url"] = release_url
        result["release_name"] = release_name

        if latest_version:
            result["has_update"] = compare_versions(current_version, latest_version) < 0
        else:
            result["success"] = False
            result["message"] = "未获取到有效的 Release 版本号"
    except (HTTPError, URLError, TimeoutError, ValueError) as e:
        result["success"] = False
        result["message"] = f"检查更新失败: {str(e)}"
    except Exception as e:
        result["success"] = False
        result["message"] = f"检查更新失败: {str(e)}"

    return result
