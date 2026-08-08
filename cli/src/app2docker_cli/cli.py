from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import os
import ssl
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


ENV_KEYS = {
    "server": "APP2DOCKER_SERVER",
    "auth_mode": "APP2DOCKER_AUTH_MODE",
    "credential_id": "APP2DOCKER_CREDENTIAL_ID",
    "private_key": "APP2DOCKER_PRIVATE_KEY",
    "api_key": "APP2DOCKER_API_KEY",
    "username": "APP2DOCKER_USERNAME",
    "password": "APP2DOCKER_PASSWORD",
    "ca_cert": "APP2DOCKER_CA_CERT",
    "team_id": "APP2DOCKER_TEAM_ID",
}
TERMINAL_STATUSES = {"completed", "failed", "stopped"}


class CLIError(Exception):
    pass


class APIError(CLIError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def config_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return root / "app2docker" / "config.json"


def load_config() -> Dict[str, str]:
    path = config_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CLIError(f"无法读取配置 {path}: {exc}") from exc
    return {key: str(value) for key, value in data.items() if value not in (None, "")}


def save_config(values: Dict[str, str]) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    return path


def resolved_config(args: argparse.Namespace) -> Dict[str, str]:
    result = load_config()
    if not result.get("api_key") and result.get("app_key"):
        result["api_key"] = result.pop("app_key")
    if not os.environ.get("APP2DOCKER_API_KEY") and os.environ.get(
        "APP2DOCKER_APP_KEY"
    ):
        result["api_key"] = os.environ["APP2DOCKER_APP_KEY"]
    for key, env_name in ENV_KEYS.items():
        if os.environ.get(env_name):
            result[key] = os.environ[env_name]
        value = getattr(args, key, None)
        if value:
            result[key] = value
    if result.get("server"):
        result["server"] = result["server"].rstrip("/")
    return result


def display_config(config: Dict[str, str]) -> Dict[str, str]:
    shown = dict(config)
    key = shown.get("api_key", "")
    if key:
        shown["api_key"] = (key[:4] + "…" + key[-4:]) if len(key) > 10 else "********"
    if shown.get("password"):
        shown["password"] = "********"
    shown.pop("app_key", None)
    return shown


class APIClient:
    def __init__(self, config: Dict[str, str]):
        if not config.get("server"):
            raise CLIError("未配置服务地址；请运行 app2docker config set --server URL")
        self.server = config["server"]
        self.ca_cert = config.get("ca_cert")
        self.config = config
        self.auth_mode = self._resolve_auth_mode(config)
        self._private_key = None

    @staticmethod
    def _resolve_auth_mode(config: Dict[str, str]) -> str:
        mode = config.get("auth_mode", "auto").lower()
        available = {
            "certificate": bool(config.get("credential_id") and config.get("private_key")),
            "api-key": bool(config.get("api_key")),
            "basic": bool(config.get("username") and config.get("password")),
        }
        if mode == "auto":
            for candidate in ("certificate", "api-key", "basic"):
                if available[candidate]:
                    return candidate
        elif mode in available and available[mode]:
            return mode
        elif mode not in available:
            raise CLIError("--auth-mode 仅支持 auto、certificate、api-key 或 basic")
        raise CLIError(
            "未配置可用认证：证书需要 credential-id/private-key，"
            "API Key 需要 api-key，Basic 需要 username/password"
        )

    def _ssl_context(self) -> ssl.SSLContext:
        try:
            return ssl.create_default_context(cafile=self.ca_cert or None)
        except OSError as exc:
            raise CLIError(f"无法加载 CA 证书 {self.ca_cert}: {exc}") from exc

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Dict[str, Any]] = None,
        body: Optional[Dict[str, Any]] = None,
        text_response: bool = False,
    ) -> Any:
        if query:
            values = {k: v for k, v in query.items() if v not in (None, "")}
            path += ("&" if "?" in path else "?") + urllib.parse.urlencode(values)
        data = None
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = self._auth_headers(method, path, data or b"")
        headers["Accept"] = "application/json"
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.server + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, context=self._ssl_context(), timeout=30) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            self._raise_http(exc.code, exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise CLIError(f"无法连接 app2docker: {exc}") from exc
        if text_response:
            return raw.decode("utf-8", errors="replace")
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _auth_headers(self, method: str, target: str, body: bytes = b"", body_hash: str = None):
        if self.auth_mode == "api-key":
            return {"Authorization": f"Bearer {self.config['api_key']}"}
        if self.auth_mode == "basic":
            raw = f"{self.config['username']}:{self.config['password']}".encode("utf-8")
            return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}

        timestamp = str(int(time.time()))
        nonce = str(uuid.uuid4())
        digest = body_hash or hashlib.sha256(body).hexdigest()
        message = "\n".join(
            [method.upper(), target, timestamp, nonce, digest]
        ).encode("utf-8")
        signature, algorithm = self._sign(message)
        return {
            "X-App2Docker-Credential-Id": self.config["credential_id"],
            "X-App2Docker-Timestamp": timestamp,
            "X-App2Docker-Nonce": nonce,
            "X-App2Docker-Content-SHA256": digest,
            "X-App2Docker-Signature-Algorithm": algorithm,
            "X-App2Docker-Signature": base64.b64encode(signature).decode("ascii"),
        }

    def _sign(self, message: bytes):
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa

        if self._private_key is None:
            path = Path(self.config["private_key"]).expanduser()
            try:
                data = path.read_bytes()
            except OSError as exc:
                raise CLIError(f"无法读取私钥 {path}: {exc}") from exc
            passphrase = os.environ.get("APP2DOCKER_KEY_PASSPHRASE")
            password = passphrase.encode("utf-8") if passphrase else None
            try:
                try:
                    self._private_key = serialization.load_ssh_private_key(data, password)
                except ValueError:
                    self._private_key = serialization.load_pem_private_key(data, password)
            except (TypeError, ValueError) as exc:
                raise CLIError("私钥格式或 APP2DOCKER_KEY_PASSPHRASE 无效") from exc
        key = self._private_key
        if isinstance(key, ed25519.Ed25519PrivateKey):
            return key.sign(message), "ed25519"
        if isinstance(key, rsa.RSAPrivateKey):
            return key.sign(message, padding.PKCS1v15(), hashes.SHA256()), "rsa-sha256"
        if isinstance(key, ec.EllipticCurvePrivateKey):
            return key.sign(message, ec.ECDSA(hashes.SHA256())), "ecdsa-sha256"
        raise CLIError("仅支持 Ed25519、RSA 或 ECDSA 私钥")

    def upload(self, path: str, fields: Dict[str, Any], file_path: Path) -> Dict[str, Any]:
        parsed = urllib.parse.urlsplit(self.server)
        boundary = "----app2docker-" + uuid.uuid4().hex
        parts = []
        for name, value in fields.items():
            if value in (None, ""):
                continue
            text = str(value).lower() if isinstance(value, bool) else str(value)
            parts.append(
                f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{text}\r\n".encode()
            )
        file_head = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"project_archive\"; "
            f"filename=\"{file_path.name}\"\r\nContent-Type: application/zip\r\n\r\n"
        ).encode()
        ending = f"\r\n--{boundary}--\r\n".encode()
        length = sum(map(len, parts)) + len(file_head) + file_path.stat().st_size + len(ending)
        target = (parsed.path.rstrip("/") + path) or "/"
        if parsed.query:
            target += "?" + parsed.query
        connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        kwargs = {"timeout": 30}
        if parsed.scheme == "https":
            kwargs["context"] = self._ssl_context()
        hasher = hashlib.sha256()
        for part in parts:
            hasher.update(part)
        hasher.update(file_head)
        with file_path.open("rb") as source:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                hasher.update(chunk)
        hasher.update(ending)
        auth_headers = self._auth_headers(
            "POST", target, body_hash=hasher.hexdigest()
        )
        connection = connection_cls(parsed.hostname, parsed.port, **kwargs)
        try:
            connection.putrequest("POST", target)
            for name, value in auth_headers.items():
                connection.putheader(name, value)
            connection.putheader("Accept", "application/json")
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(length))
            connection.endheaders()
            for part in parts:
                connection.send(part)
            connection.send(file_head)
            with file_path.open("rb") as source:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    connection.send(chunk)
            connection.send(ending)
            response = connection.getresponse()
            raw = response.read()
            if response.status >= 400:
                self._raise_http(response.status, raw)
            return json.loads(raw.decode("utf-8")) if raw else {}
        except (OSError, http.client.HTTPException) as exc:
            raise CLIError(f"上传本地源码失败: {exc}") from exc
        finally:
            connection.close()

    @staticmethod
    def _raise_http(status: int, raw: bytes) -> None:
        message = raw.decode("utf-8", errors="replace")
        try:
            payload = json.loads(message)
            message = payload.get("detail") or payload.get("message") or message
        except json.JSONDecodeError:
            pass
        raise APIError(status, str(message))


def run_git(args: Iterable[str], cwd: Optional[Path] = None, *, required: bool = True) -> str:
    result = subprocess.run(
        ["git", *args], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    if required and result.returncode:
        raise CLIError(result.stderr.strip() or "Git 命令执行失败")
    return result.stdout.strip()


def git_context(project: str) -> Dict[str, Any]:
    root = Path(run_git(["-C", project, "rev-parse", "--show-toplevel"])).resolve()
    branch = run_git(["symbolic-ref", "--quiet", "--short", "HEAD"], root, required=False)
    commit = run_git(["rev-parse", "HEAD"], root)
    remote = run_git(["remote", "get-url", "origin"], root, required=False)
    dirty = bool(run_git(["status", "--porcelain"], root, required=False))
    upstream = run_git(["rev-parse", "--abbrev-ref", "@{upstream}"], root, required=False)
    upstream_commit = run_git(["rev-parse", "@{upstream}"], root, required=False) if upstream else ""
    return {
        "root": root,
        "branch": branch,
        "commit": commit,
        "remote": remote,
        "dirty": dirty,
        "upstream": upstream,
        "upstream_commit": upstream_commit,
    }


def require_remote_current(context: Dict[str, Any], reason: str) -> None:
    if context["dirty"]:
        raise CLIError(f"{reason}要求工作区无未提交修改")
    if not context["remote"]:
        raise CLIError(f"{reason}要求 Git origin 地址")
    if not context["upstream"]:
        raise CLIError(f"{reason}要求当前分支已设置 upstream")
    if context["commit"] != context["upstream_commit"]:
        raise CLIError(f"{reason}要求本地 HEAD 与 upstream 一致；请先推送或拉取")


def make_snapshot(context: Dict[str, Any]) -> Path:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=context["root"], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode:
        raise CLIError(result.stderr.decode(errors="replace").strip())
    handle, name = tempfile.mkstemp(prefix="app2docker-source-", suffix=".zip")
    os.close(handle)
    archive = Path(name)
    try:
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for raw_name in result.stdout.split(b"\0"):
                if not raw_name:
                    continue
                relative = os.fsdecode(raw_name)
                path = context["root"] / relative
                if path.is_symlink():
                    raise CLIError(f"本地快照不支持符号链接：{relative}")
                if not path.is_file():
                    continue
                info = zipfile.ZipInfo.from_file(path, arcname=Path(relative).as_posix())
                info.compress_type = zipfile.ZIP_DEFLATED
                mode = path.stat().st_mode
                info.external_attr = (stat.S_IMODE(mode) & 0xFFFF) << 16
                with path.open("rb") as source, bundle.open(info, "w") as target:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
        return archive
    except Exception:
        archive.unlink(missing_ok=True)
        raise


def select_team(client: APIClient, configured: Optional[str]) -> str:
    if configured:
        return configured
    memberships = client.request("GET", "/api/teams/me")
    if len(memberships) == 1:
        return memberships[0]["team"]["team_id"]
    if not memberships:
        raise CLIError("当前认证账号没有可用团队")
    names = ", ".join(f'{item["team"]["name"]}={item["team"]["team_id"]}' for item in memberships)
    raise CLIError(f"存在多个团队，请用 --team-id 指定：{names}")


def follow_task(
    client: APIClient,
    task_id: str,
    team_id: str,
    *,
    json_output: bool = False,
    emit_json: bool = True,
    timeout: float = 0,
    poll_interval: float = 1,
    retries: int = 5,
) -> Dict[str, Any]:
    after_id = 0
    started = time.monotonic()
    failures = 0
    while True:
        if timeout > 0 and time.monotonic() - started >= timeout:
            raise CLIError(
                f"跟踪任务 {task_id} 超时；远端任务仍在运行，可执行 "
                f"app2docker task logs {task_id} --follow 继续跟踪"
            )
        try:
            task = client.request(
                "GET", f"/api/build-tasks/{task_id}", query={"team_id": team_id}
            )
            page = client.request(
                "GET",
                f"/api/build-tasks/{task_id}/logs",
                query={"team_id": team_id, "after_id": after_id},
            )
            logs = page.get("logs", "")
            after_id = int(page.get("next_after_id", after_id))
            failures = 0
        except CLIError as exc:
            retryable = not isinstance(exc, APIError) or exc.status in {
                408, 425, 429, 500, 502, 503, 504
            }
            if not retryable or failures >= retries:
                raise
            failures += 1
            delay = min(max(poll_interval, 0.1) * (2 ** (failures - 1)), 10)
            print(
                f"跟踪暂时中断，{delay:g} 秒后重试（{failures}/{retries}）：{exc}",
                file=sys.stderr,
            )
            time.sleep(delay)
            continue
        if logs:
            stream = sys.stderr if json_output else sys.stdout
            stream.write(logs)
            stream.flush()
        if task.get("status") in TERMINAL_STATUSES:
            if json_output and emit_json:
                print(json.dumps(task, ensure_ascii=False))
            elif not str(task.get("status")) == "completed":
                print(f"\n任务结束：{task.get('status')} - {task.get('error') or ''}", file=sys.stderr)
            return task
        time.sleep(max(poll_interval, 0))


def follow_options(args: argparse.Namespace) -> Dict[str, Any]:
    return {
        "timeout": args.timeout,
        "poll_interval": args.poll_interval,
        "retries": args.retries,
    }


def build_payload(args: argparse.Namespace, team_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
    payload = {
        "git_url": args.git_url or context["remote"],
        "branch": args.branch or context["branch"] or None,
        "tag_name": args.tag_name,
        "profile": args.profile,
        "project_type": args.project_type,
        "template": args.template,
        "image_name": args.image_name,
        "tag": args.tag,
        "push": args.push,
        "team_id": team_id,
        "pipeline_name": args.save_pipeline,
        "pipeline_description": args.pipeline_description,
        "trigger_source": "cli",
    }
    return {key: value for key, value in payload.items() if value is not None}


def cmd_build(args: argparse.Namespace, client: APIClient, config: Dict[str, str]) -> int:
    if args.detach and args.deploy:
        raise CLIError("--detach 不能与 --deploy 同时使用；自动部署需要等待构建成功")
    context = git_context(args.project)
    team_id = select_team(client, config.get("team_id"))
    payload = build_payload(args, team_id, context)
    archive = None
    if args.source == "git":
        require_remote_current(context, "Git 远程构建")
        if not payload.get("git_url"):
            raise CLIError("未找到 Git 地址，请使用 --git-url")
        response = client.request("POST", "/api/build-with-config", body=payload)
    else:
        if args.tag_name:
            raise CLIError("本地快照模式不支持 --tag-name；请使用 --tag 设置镜像标签")
        if args.save_pipeline:
            require_remote_current(context, "保存可复现流水线")
        archive = make_snapshot(context)
        fields = dict(payload)
        fields.pop("tag_name", None)
        fields.pop("trigger_source", None)
        fields["commit"] = context["commit"]
        try:
            response = client.upload("/api/build-from-local", fields, archive)
        finally:
            archive.unlink(missing_ok=True)
    if args.detach:
        print(json.dumps(response, ensure_ascii=False) if args.json else response["task_id"])
        return 0
    if not args.json:
        detail = f"；流水线 {response['pipeline_id']}" if response.get("pipeline_id") else ""
        print(f"构建任务已启动：{response['task_id']}{detail}", file=sys.stderr)
    task = follow_task(
        client,
        response["task_id"],
        team_id,
        json_output=args.json,
        emit_json=not args.deploy,
        **follow_options(args),
    )
    if task.get("status") != "completed":
        if args.json and args.deploy:
            print(json.dumps({"build": task, "deployment": None}, ensure_ascii=False))
        return 1
    if not args.deploy:
        return 0

    _, deployment = trigger_deployment(
        client,
        args.deploy,
        team_id,
        target_names=args.deploy_target,
        json_output=args.json,
        emit_json=False,
    )
    if args.json:
        print(json.dumps({"build": task, "deployment": deployment}, ensure_ascii=False))
    return 0 if deployment.get("status") == "completed" else 1


def cmd_task(args: argparse.Namespace, client: APIClient, config: Dict[str, str]) -> int:
    team_id = select_team(client, config.get("team_id"))
    if args.task_command == "status":
        value = client.request("GET", f"/api/build-tasks/{args.task_id}", query={"team_id": team_id})
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif args.task_command == "logs":
        if args.follow:
            task = follow_task(client, args.task_id, team_id, **follow_options(args))
            return 0 if task.get("status") == "completed" else 1
        print(client.request("GET", f"/api/build-tasks/{args.task_id}/logs", query={"team_id": team_id}, text_response=True), end="")
    else:
        value = client.request("POST", f"/api/build-tasks/{args.task_id}/stop", query={"team_id": team_id})
        print(value.get("message", "任务已停止"))
    return 0


def cmd_pipeline(args: argparse.Namespace, client: APIClient, config: Dict[str, str]) -> int:
    team_id = select_team(client, config.get("team_id"))
    if args.pipeline_command == "list":
        value = client.request("GET", "/api/pipelines", query={"team_id": team_id, "page_size": 1000})
        if args.json:
            print(json.dumps(value, ensure_ascii=False))
        else:
            for pipeline in value.get("pipelines", []):
                print(f'{pipeline["pipeline_id"]}\t{pipeline["name"]}\t{pipeline.get("branch") or "-"}\t{pipeline.get("profile") or "-"}')
        return 0
    body = {"branch": args.branch, "trigger_source": "cli"}
    if args.tag_name:
        body = {
            "ref_type": "tag",
            "ref_name": args.tag_name,
            "trigger_source": "cli",
        }
    value = client.request("POST", f"/api/pipelines/{args.pipeline_id}/run", body=body)
    task_ids = value.get("task_ids") or [value["task_id"]]
    if args.detach:
        print(json.dumps(value, ensure_ascii=False) if args.json else "\n".join(task_ids))
        return 0
    if not args.json:
        print(f"流水线任务已启动：{', '.join(task_ids)}", file=sys.stderr)
    success = True
    for task_id in task_ids:
        if len(task_ids) > 1 and not args.json:
            print(f"== {task_id} ==")
        task = follow_task(
            client, task_id, team_id, json_output=args.json, **follow_options(args)
        )
        success = success and task.get("status") == "completed"
    return 0 if success else 1


def trigger_deployment(
    client: APIClient,
    config_id: str,
    team_id: str,
    *,
    target_names: Optional[list] = None,
    detach: bool = False,
    json_output: bool = False,
    emit_json: bool = True,
    timeout: float = 0,
    poll_interval: float = 1,
    retries: int = 5,
):
    value = client.request(
        "POST",
        f"/api/deploy-tasks/{config_id}/execute",
        body={"target_names": target_names or None, "trigger_source": "cli"},
    )
    if detach:
        print(json.dumps(value, ensure_ascii=False) if json_output else value["task_id"])
        return value, None
    if not json_output:
        print(f"部署任务已启动：{value['task_id']}", file=sys.stderr)
    task = follow_task(
        client,
        value["task_id"],
        team_id,
        json_output=json_output,
        emit_json=emit_json,
        timeout=timeout,
        poll_interval=poll_interval,
        retries=retries,
    )
    return value, task


def cmd_deploy(args: argparse.Namespace, client: APIClient, config: Dict[str, str]) -> int:
    team_id = select_team(client, config.get("team_id"))
    if args.deploy_command == "list":
        value = client.request(
            "GET",
            "/api/deploy-tasks",
            query={"team_id": team_id, "page_size": 100},
        )
        if args.json:
            print(json.dumps(value, ensure_ascii=False))
        else:
            for item in value.get("tasks", []):
                status = (item.get("status") or {}).get("status", "-")
                print(f'{item["task_id"]}\t{item.get("app_name") or "-"}\t{status}')
        return 0
    _, task = trigger_deployment(
        client,
        args.config_id,
        team_id,
        target_names=args.target,
        detach=args.detach,
        json_output=args.json,
        **follow_options(args),
    )
    return 0 if task is None or task.get("status") == "completed" else 1


def add_connection_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", help="app2docker 服务地址")
    parser.add_argument(
        "--auth-mode",
        choices=("auto", "certificate", "api-key", "basic"),
        help="认证方式，默认自动选择",
    )
    parser.add_argument("--credential-id", help="账号下的 CLI 证书凭证 ID")
    parser.add_argument("--private-key", help="本地 SSH/PEM 私钥路径")
    parser.add_argument("--api-key", help="API Key")
    parser.add_argument("--username", help="Basic 用户名")
    parser.add_argument("--password", help="Basic 密码")
    parser.add_argument("--ca-cert", help="自定义 CA 证书路径")
    parser.add_argument("--team-id", help="团队 ID")


def add_follow_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--timeout", type=float, default=0, metavar="SECONDS", help="跟踪超时，0 表示不限时")
    parser.add_argument("--poll-interval", type=float, default=1, metavar="SECONDS", help="状态轮询间隔")
    parser.add_argument("--retries", type=int, default=5, metavar="COUNT", help="临时连接错误重试次数")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="app2docker", description="app2docker CLI")
    add_connection_options(root)
    commands = root.add_subparsers(dest="command", required=True)

    config = commands.add_parser("config", help="管理连接配置")
    config_commands = config.add_subparsers(dest="config_command", required=True)
    config_set = config_commands.add_parser("set")
    add_connection_options(config_set)
    config_commands.add_parser("show")
    commands.add_parser("doctor", help="检查服务、认证、证书和团队")

    build = commands.add_parser("build", help="触发构建")
    build.add_argument("project", nargs="?", default=".")
    build.add_argument("--source", choices=("git", "local"), default="git")
    build.add_argument("--git-url")
    build.add_argument("--branch")
    build.add_argument("--tag-name")
    build.add_argument("--profile")
    build.add_argument("--project-type")
    build.add_argument("--template")
    build.add_argument("--image-name")
    build.add_argument("--tag")
    push = build.add_mutually_exclusive_group()
    push.add_argument("--push", action="store_true", default=None)
    push.add_argument("--no-push", action="store_false", dest="push")
    build.add_argument("--save-pipeline", metavar="NAME")
    build.add_argument("--pipeline-description")
    build.add_argument("--deploy", metavar="CONFIG_ID", help="构建成功后触发部署配置")
    build.add_argument(
        "--deploy-target",
        action="append",
        metavar="NAME",
        help="仅部署指定目标，可重复传入",
    )
    build.add_argument("--detach", action="store_true")
    build.add_argument("--json", action="store_true")
    add_follow_options(build)

    task = commands.add_parser("task", help="查看或停止任务")
    task_commands = task.add_subparsers(dest="task_command", required=True)
    for name in ("status", "logs", "stop"):
        command = task_commands.add_parser(name)
        command.add_argument("task_id")
        if name == "logs":
            command.add_argument("--follow", action="store_true")
            add_follow_options(command)

    pipeline = commands.add_parser("pipeline", help="查看或运行流水线")
    pipeline_commands = pipeline.add_subparsers(dest="pipeline_command", required=True)
    pipeline_list = pipeline_commands.add_parser("list")
    pipeline_list.add_argument("--json", action="store_true")
    pipeline_run = pipeline_commands.add_parser("run", aliases=["trigger"])
    pipeline_run.add_argument("pipeline_id")
    pipeline_run.add_argument("--branch")
    pipeline_run.add_argument("--tag-name")
    pipeline_run.add_argument("--detach", action="store_true")
    pipeline_run.add_argument("--json", action="store_true")
    add_follow_options(pipeline_run)

    deploy = commands.add_parser("deploy", help="查看或触发部署配置")
    deploy_commands = deploy.add_subparsers(dest="deploy_command", required=True)
    deploy_list = deploy_commands.add_parser("list")
    deploy_list.add_argument("--json", action="store_true")
    deploy_run = deploy_commands.add_parser("run", aliases=["trigger"])
    deploy_run.add_argument("config_id")
    deploy_run.add_argument(
        "--target", action="append", metavar="NAME", help="仅部署指定目标，可重复传入"
    )
    deploy_run.add_argument("--detach", action="store_true")
    deploy_run.add_argument("--json", action="store_true")
    add_follow_options(deploy_run)
    return root


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "config":
            if args.config_command == "show":
                print(json.dumps(display_config(load_config()), ensure_ascii=False, indent=2))
                return 0
            values = load_config()
            for key in ENV_KEYS:
                value = getattr(args, key, None)
                if value:
                    values[key] = value.rstrip("/") if key == "server" else value
            path = save_config(values)
            print(f"配置已保存：{path}")
            return 0
        config = resolved_config(args)
        client = APIClient(config)
        if args.command == "doctor":
            client.request("GET", "/health")
            memberships = client.request("GET", "/api/teams/me")
            print(
                f"连接正常；{client.auth_mode} 认证有效；可用团队 {len(memberships)} 个"
            )
            return 0
        if args.command == "build":
            return cmd_build(args, client, config)
        if args.command == "task":
            return cmd_task(args, client, config)
        if args.command == "pipeline":
            return cmd_pipeline(args, client, config)
        return cmd_deploy(args, client, config)
    except KeyboardInterrupt:
        print("\n已停止等待，远端任务仍在运行。", file=sys.stderr)
        return 130
    except APIError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except CLIError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
