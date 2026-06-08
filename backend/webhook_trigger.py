# backend/webhook_trigger.py
"""Webhook 触发工具函数"""
import json
import logging
import asyncio
import hashlib
from fnmatch import fnmatchcase
from typing import Dict, Any, List, Optional
import httpx

logger = logging.getLogger(__name__)


def normalize_branch_name(branch: Optional[str]) -> str:
    """Normalize Git branch refs before matching."""
    if not branch:
        return ""
    branch = str(branch).strip()
    if branch.startswith("refs/heads/"):
        return branch[len("refs/heads/") :]
    return branch


def get_webhook_event(headers: Dict[str, Any]) -> Dict[str, str]:
    """Return normalized webhook event metadata from common Git providers."""
    normalized_headers = {
        str(key).lower(): str(value) for key, value in (headers or {}).items()
    }
    if "x-gitee-event" in normalized_headers:
        return {"platform": "gitee", "event": normalized_headers["x-gitee-event"]}
    if "x-gitlab-event" in normalized_headers:
        return {"platform": "gitlab", "event": normalized_headers["x-gitlab-event"]}
    if "x-github-event" in normalized_headers:
        return {"platform": "github", "event": normalized_headers["x-github-event"]}
    return {"platform": "unknown", "event": ""}


def is_build_webhook_event(event: Optional[str]) -> bool:
    """Allow only push-like events when a provider event header is present."""
    if not event:
        return True
    normalized = str(event).strip().lower().replace("_", " ")
    blocked_tokens = (
        "merge",
        "pull",
        "note",
        "comment",
        "issue",
        "review",
        "pipeline",
        "job",
        "release",
    )
    if any(token in normalized for token in blocked_tokens):
        return False
    return "push" in normalized


def extract_webhook_commit_sha(payload: Optional[dict]) -> str:
    """Extract the commit identity used for webhook dedupe."""
    payload = payload or {}
    for key in ("after", "checkout_sha"):
        value = payload.get(key)
        if value:
            return str(value)

    head_commit = payload.get("head_commit")
    if isinstance(head_commit, dict) and head_commit.get("id"):
        return str(head_commit["id"])

    commits = payload.get("commits")
    if isinstance(commits, list) and commits:
        last_commit = commits[-1]
        if isinstance(last_commit, dict):
            for key in ("id", "sha"):
                if last_commit.get(key):
                    return str(last_commit[key])

    return ""


def get_webhook_delivery_id(headers: Dict[str, Any]) -> str:
    """Extract provider delivery id when available."""
    normalized_headers = {
        str(key).lower(): str(value) for key, value in (headers or {}).items()
    }
    for key in (
        "x-github-delivery",
        "x-gitee-delivery",
        "x-gitlab-event-uuid",
        "x-request-id",
    ):
        value = normalized_headers.get(key)
        if value:
            return value
    return ""


def build_webhook_dedupe_key(
    pipeline_id: str,
    ref: Optional[str],
    payload: Optional[dict],
    headers: Optional[Dict[str, Any]] = None,
) -> Dict[str, str]:
    """Build a stable key for suppressing duplicate webhook deliveries."""
    event_meta = get_webhook_event(headers or {})
    commit_sha = extract_webhook_commit_sha(payload)
    delivery_id = get_webhook_delivery_id(headers or {})
    normalized_ref = str(ref or (payload or {}).get("ref") or "").strip()
    payload_identity = commit_sha or delivery_id

    if not payload_identity:
        payload_body = json.dumps(payload or {}, sort_keys=True, ensure_ascii=False)
        payload_identity = hashlib.sha256(payload_body.encode("utf-8")).hexdigest()

    raw_key = "|".join(
        [
            str(pipeline_id or ""),
            event_meta.get("platform", "unknown"),
            event_meta.get("event", ""),
            normalized_ref,
            payload_identity,
        ]
    )
    dedupe_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return {
        "dedupe_key": dedupe_key,
        "raw_key": raw_key,
        "platform": event_meta.get("platform", "unknown"),
        "event": event_meta.get("event", ""),
        "ref": normalized_ref,
        "commit_sha": commit_sha,
        "delivery_id": delivery_id,
    }


def branch_rule_has_wildcard(rule: str) -> bool:
    return any(token in rule for token in ("*", "?", "["))


def matches_branch_rule(branch: Optional[str], rule: Optional[str]) -> bool:
    """
    Match a branch against a single rule.

    Plain text is exact-match only. Wildcard matching is enabled only when the
    rule explicitly contains shell-style wildcard characters.
    """
    normalized_branch = normalize_branch_name(branch)
    normalized_rule = normalize_branch_name(rule)
    if not normalized_branch or not normalized_rule:
        return False
    if normalized_branch == normalized_rule:
        return True
    if not branch_rule_has_wildcard(normalized_rule):
        return False
    return fnmatchcase(normalized_branch, normalized_rule)


def matches_any_branch_rule(branch: Optional[str], rules: Optional[List[str]]) -> bool:
    if not branch or not rules:
        return False
    return any(matches_branch_rule(branch, rule) for rule in rules if rule)


def get_branch_mapping_value(branch: Optional[str], mapping: Optional[dict]):
    """Return mapping value with exact matches taking precedence over wildcard rules."""
    normalized_branch = normalize_branch_name(branch)
    if not normalized_branch or not mapping:
        return None

    normalized_exact_lookup = {}
    for rule, value in mapping.items():
        normalized_rule = normalize_branch_name(rule)
        if normalized_rule and not branch_rule_has_wildcard(normalized_rule):
            normalized_exact_lookup[normalized_rule] = value

    if normalized_branch in normalized_exact_lookup:
        return normalized_exact_lookup[normalized_branch]

    for rule, value in mapping.items():
        if matches_branch_rule(normalized_branch, rule):
            return value

    return None


def normalize_tag_values(tag_value) -> List[str]:
    if not tag_value:
        return []
    if isinstance(tag_value, list):
        return [str(tag).strip() for tag in tag_value if str(tag).strip()]
    if isinstance(tag_value, str):
        normalized = tag_value.replace("，", ",")
        return [tag.strip() for tag in normalized.split(",") if tag.strip()]
    return [str(tag_value).strip()] if str(tag_value).strip() else []


def resolve_branch_tags(
    branch: Optional[str],
    mapping: Optional[dict] = None,
    default_tag: Optional[str] = None,
) -> List[str]:
    """Resolve image tags for a branch. Defaults to the branch name."""
    mapped_tag_value = get_branch_mapping_value(branch, mapping)
    mapped_tags = normalize_tag_values(mapped_tag_value)
    if mapped_tags:
        return mapped_tags

    fallback = default_tag or normalize_branch_name(branch)
    return [fallback] if fallback else []


def resolve_pipeline_webhook_branch(
    strategy: str,
    webhook_branch: Optional[str],
    configured_branch: Optional[str],
    allowed_branches: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Resolve whether a pipeline webhook should trigger and which branch to build.

    The result uses:
    - ok=True with branch when a build should be created.
    - ignored=True when the webhook is valid but the pushed branch is not allowed.
    - error when required branch data is missing.
    """
    strategy = strategy or "use_push"

    if strategy == "select_branches":
        if not webhook_branch:
            return {"ok": False, "error": "missing_webhook_branch"}
        if matches_any_branch_rule(webhook_branch, allowed_branches):
            return {"ok": True, "branch": normalize_branch_name(webhook_branch)}
        return {"ok": False, "ignored": True, "reason": "branch_not_allowed"}

    if strategy == "select_configured":
        if not webhook_branch:
            return {"ok": False, "error": "missing_webhook_branch"}
        if matches_any_branch_rule(webhook_branch, allowed_branches):
            return {"ok": True, "branch": normalize_branch_name(configured_branch)}
        return {"ok": False, "ignored": True, "reason": "branch_not_allowed"}

    if strategy == "filter_match":
        if not webhook_branch:
            return {"ok": False, "error": "missing_webhook_branch"}
        if matches_branch_rule(webhook_branch, configured_branch):
            return {"ok": True, "branch": normalize_branch_name(webhook_branch)}
        return {"ok": False, "ignored": True, "reason": "branch_not_matched"}

    if strategy == "use_configured":
        if not webhook_branch:
            return {"ok": False, "error": "missing_webhook_branch"}
        if normalize_branch_name(webhook_branch) == normalize_branch_name(
            configured_branch
        ):
            return {"ok": True, "branch": normalize_branch_name(configured_branch)}
        return {"ok": False, "ignored": True, "reason": "not_configured_branch"}

    if not webhook_branch:
        return {"ok": False, "error": "missing_webhook_branch"}
    return {"ok": True, "branch": normalize_branch_name(webhook_branch)}


async def trigger_webhook(
    url: str,
    method: str = "POST",
    headers: Optional[Dict[str, str]] = None,
    body: Optional[str] = None,
    timeout: float = 10.0,
) -> Dict[str, Any]:
    """
    触发 Webhook HTTP 请求

    Args:
        url: Webhook URL
        method: HTTP 方法（POST, PUT等）
        headers: 请求头（可选）
        body: 请求体（可选）
        timeout: 超时时间（秒）

    Returns:
        包含 success, status_code, response_text 的字典
    """
    try:
        # 设置默认请求头
        request_headers = {"Content-Type": "application/json"}
        if headers:
            request_headers.update(headers)

        # 发送HTTP请求
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method.upper() == "POST":
                response = await client.post(url, headers=request_headers, content=body)
            elif method.upper() == "PUT":
                response = await client.put(url, headers=request_headers, content=body)
            elif method.upper() == "PATCH":
                response = await client.patch(
                    url, headers=request_headers, content=body
                )
            else:
                logger.warning(f"不支持的HTTP方法: {method}，使用POST")
                response = await client.post(url, headers=request_headers, content=body)

            return {
                "success": response.status_code < 400,
                "status_code": response.status_code,
                "response_text": response.text[:500],  # 限制响应文本长度
            }
    except httpx.TimeoutException:
        logger.error(f"Webhook 请求超时: {url}")
        return {
            "success": False,
            "status_code": None,
            "response_text": "Request timeout",
            "error": "timeout",
        }
    except httpx.RequestError as e:
        logger.error(f"Webhook 请求失败: {url}, 错误: {str(e)}")
        return {
            "success": False,
            "status_code": None,
            "response_text": str(e),
            "error": "request_error",
        }
    except Exception as e:
        logger.exception(f"Webhook 触发异常: {url}, 错误: {str(e)}")
        return {
            "success": False,
            "status_code": None,
            "response_text": str(e),
            "error": "unknown_error",
        }


def render_template(template: str, context: Dict[str, Any]) -> str:
    """
    渲染模板字符串（支持变量替换）

    Args:
        template: 模板字符串，支持 {variable} 格式的变量
        context: 变量上下文

    Returns:
        渲染后的字符串
    """
    try:
        result = template
        for key, value in context.items():
            placeholder = "{" + key + "}"
            # 将值转换为字符串
            str_value = str(value) if value is not None else ""
            result = result.replace(placeholder, str_value)
        return result
    except Exception as e:
        logger.error(f"模板渲染失败: {e}")
        return template


def match_branch(
    branch: str, strategy: str, allowed_branches: List[str]
) -> bool:
    """
    判断任务分支是否匹配 Webhook 的分支策略

    Args:
        branch: 当前任务分支
        strategy: 分支策略 ("all" / "select_branches" / "filter_match")
        allowed_branches: 允许的分支列表

    Returns:
        是否匹配
    """
    if strategy != "select_branches" and strategy != "filter_match":
        return True

    if not branch:
        return False

    if not allowed_branches:
        return False

    return matches_any_branch_rule(branch, allowed_branches)
