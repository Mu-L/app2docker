"""磁盘监控与 Docker 构建缓存自动清理。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

STATE_FILE = "data/.cache_cleanup.json"
LOCK_FILE = "data/.cache_cleanup.lock"
LOG_FILE = "data/logs/cache_cleanup.log"
STALE_LOCK_SECONDS = 600  # 10 分钟
COOLDOWN_BASE_SECONDS = 6 * 3600
COOLDOWN_MAX_SECONDS = 24 * 3600

_cleanup_running = False
_module_lock = threading.Lock()

RECLAIMED_PATTERN = re.compile(
    r"Total reclaimed space:\s*(.+)", re.IGNORECASE
)


def get_disk_usage_percent(path: str = "/") -> Optional[float]:
    """获取指定路径所在分区的磁盘占用百分比。"""
    try:
        import psutil

        return float(psutil.disk_usage(path).percent)
    except ImportError:
        print("⚠️ psutil 未安装，无法检测磁盘占用")
    except Exception as e:
        print(f"⚠️ 检测磁盘占用失败: {e}")
    return None


def _ensure_dirs() -> None:
    os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(LOG_FILE) or ".", exist_ok=True)


def _safe_print(message: str) -> None:
    try:
        print(message)
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(message.encode(encoding, errors="replace").decode(encoding, errors="replace"))


def _append_log(message: str) -> None:
    _ensure_dirs()
    line = f"[{datetime.now().isoformat()}] {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as e:
        _safe_print(f"⚠️ 写入缓存清理日志失败: {e}")
    _safe_print(message)


def load_cleanup_state() -> Dict[str, Any]:
    """读取持久化的清理状态（供调度器使用）。"""
    return _load_state()


def _load_state() -> Dict[str, Any]:
    _ensure_dirs()
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠️ 读取缓存清理状态失败: {e}")
        return {}


def _save_state(state: Dict[str, Any]) -> None:
    _ensure_dirs()
    temp = f"{STATE_FILE}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(temp, STATE_FILE)
    except Exception as e:
        if os.path.exists(temp):
            try:
                os.remove(temp)
            except OSError:
                pass
        print(f"⚠️ 保存缓存清理状态失败: {e}")


def _clear_stale_lock() -> None:
    if not os.path.exists(LOCK_FILE):
        return
    try:
        mtime = os.path.getmtime(LOCK_FILE)
        if time.time() - mtime > STALE_LOCK_SECONDS:
            os.remove(LOCK_FILE)
            _append_log("🧹 已清除过期的缓存清理锁文件")
    except OSError as e:
        print(f"⚠️ 清除过期锁文件失败: {e}")


def _try_acquire_lock() -> bool:
    global _cleanup_running

    with _module_lock:
        if _cleanup_running:
            return False
        _cleanup_running = True

    _clear_stale_lock()
    _ensure_dirs()
    try:
        fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"{os.getpid()} {int(time.time())}\n")
        return True
    except FileExistsError:
        with _module_lock:
            _cleanup_running = False
        return False
    except Exception as e:
        with _module_lock:
            _cleanup_running = False
        print(f"⚠️ 获取缓存清理锁失败: {e}")
        return False


def _release_lock() -> None:
    global _cleanup_running

    try:
        if os.path.exists(LOCK_FILE):
            os.remove(LOCK_FILE)
    except OSError as e:
        print(f"⚠️ 释放缓存清理锁失败: {e}")
    finally:
        with _module_lock:
            _cleanup_running = False


def should_cleanup(
    disk_percent: float,
    config: dict,
    state: Optional[dict] = None,
) -> Tuple[bool, str]:
    """返回 (是否清理, 原因说明)。"""
    state = state if state is not None else _load_state()
    threshold = float(config.get("disk_threshold_percent", 80))
    interval_h = float(config.get("interval_hours", 72))
    now = time.time()

    last = float(state.get("last_cleanup_ts") or 0)
    if last > 0 and now - last >= interval_h * 3600:
        return True, "scheduled"

    cooldown_until = state.get("cooldown_until")
    if cooldown_until and now < float(cooldown_until):
        return False, "in_cooldown"

    if disk_percent >= threshold:
        return True, f"high_disk {disk_percent:.1f}%"

    return False, "skip"


def _parse_reclaimed(stdout: str, stderr: str) -> str:
    for text in (stdout or "", stderr or ""):
        for line in text.splitlines():
            match = RECLAIMED_PATTERN.search(line)
            if match:
                return match.group(1).strip()
    return ""


def _run_docker_cmd(args: list, timeout: int = 600) -> Tuple[bool, str, str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            return False, output, f"命令失败 (exit {result.returncode}): {' '.join(args)}"
        return True, output, ""
    except FileNotFoundError:
        return False, "", "未找到 docker 命令"
    except subprocess.TimeoutExpired:
        return False, "", f"命令超时: {' '.join(args)}"
    except Exception as e:
        return False, "", str(e)


def _execute_prune(config: dict) -> Tuple[bool, str]:
    keep_cache = bool(config.get("keep_builder_cache", False))
    builder_cmd = ["docker", "builder", "prune", "-f"]
    if not keep_cache:
        builder_cmd.append("--all")

    reclaimed_parts = []
    errors = []

    ok, out, err = _run_docker_cmd(builder_cmd)
    if ok:
        part = _parse_reclaimed(out, "")
        if part:
            reclaimed_parts.append(f"builder: {part}")
    else:
        errors.append(f"builder prune: {err or out}")

    ok, out, err = _run_docker_cmd(["docker", "image", "prune", "-f"])
    if ok:
        part = _parse_reclaimed(out, "")
        if part:
            reclaimed_parts.append(f"image: {part}")
    else:
        errors.append(f"image prune: {err or out}")

    if errors and not reclaimed_parts:
        return False, "; ".join(errors)

    message = "，".join(reclaimed_parts) if reclaimed_parts else "无额外可回收空间"
    if errors:
        message = f"{message}（部分失败: {'; '.join(errors)}）"
    return True, message


def _log_disk_pressure_warning(post_percent: float, cooldown_until: float) -> None:
    msg = (
        f"⚠️ 清理后磁盘仍 {post_percent:.1f}%，进入冷却期至 "
        f"{datetime.fromtimestamp(cooldown_until).isoformat()}，"
        f"请人工检查 docker volumes / 系统日志 / 挂载磁盘"
    )
    _append_log(msg)
    try:
        from backend.handlers import OperationLogger

        OperationLogger.log(
            "system",
            "disk_cleanup_warning",
            {
                "level": "WARNING",
                "disk_percent": post_percent,
                "cooldown_until": datetime.fromtimestamp(cooldown_until).isoformat(),
                "message": msg,
            },
        )
    except Exception as e:
        _safe_print(f"记录操作日志失败: {e}")


def _apply_post_cleanup_state(config: dict, state: dict, now: float) -> None:
    threshold = float(config.get("disk_threshold_percent", 80))
    post = get_disk_usage_percent()

    if post is not None and post >= threshold:
        state["cooldown_count"] = int(state.get("cooldown_count", 0)) + 1
        delay = min(
            COOLDOWN_BASE_SECONDS * (2 ** (state["cooldown_count"] - 1)),
            COOLDOWN_MAX_SECONDS,
        )
        state["cooldown_until"] = now + delay
        state["last_disk_percent"] = post
        _log_disk_pressure_warning(post, state["cooldown_until"])
    else:
        state["cooldown_count"] = 0
        state.pop("cooldown_until", None)
        if post is not None:
            state["last_disk_percent"] = post

    _save_state(state)


def run_cache_cleanup(
    force: bool = False,
    config: Optional[dict] = None,
) -> dict:
    """
    执行构建缓存清理。

    Returns:
        {success, reclaimed, message}
    """
    if config is None:
        from backend.config import load_config

        config = load_config().get("maintenance", {})

    if not _try_acquire_lock():
        return {
            "success": False,
            "reclaimed": "",
            "message": "已有清理任务在运行或锁被占用，跳过",
        }

    now = time.time()
    state = _load_state()
    pre_percent = get_disk_usage_percent()

    try:
        if pre_percent is not None:
            _append_log(
                f"🧹 开始构建缓存清理 (force={force}, 磁盘: {pre_percent:.1f}%)"
            )
        else:
            _append_log(f"🧹 开始构建缓存清理 (force={force})")

        success, message = _execute_prune(config)
        state["last_cleanup_ts"] = now
        state["last_reason"] = "forced" if force else "auto"

        if success:
            _apply_post_cleanup_state(config, state, now)
            _append_log(f"✅ 构建缓存清理完成: {message}")
            return {"success": True, "reclaimed": message, "message": message}

        state["last_error"] = message
        _save_state(state)
        _append_log(f"⚠️ 构建缓存清理失败: {message}")
        return {"success": False, "reclaimed": "", "message": message}
    finally:
        _release_lock()
