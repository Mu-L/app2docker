import json
import os
import stat
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli" / "src"))

import app2docker_cli.cli as cli
from app2docker_cli.cli import display_config, git_context, make_snapshot, resolved_config
import backend.handlers as handlers


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def test_cli_config_precedence_and_key_mask(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("APP2DOCKER_SERVER", "https://env.example/")
    monkeypatch.setenv("APP2DOCKER_API_KEY", "abcdefghijklmnop")

    class Args:
        server = "https://flag.example/"
        api_key = None
        ca_cert = None
        team_id = None

    config = resolved_config(Args())

    assert config["server"] == "https://flag.example"
    assert display_config(config)["api_key"] == "abcd…mnop"


def test_local_snapshot_contains_git_visible_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "App2Docker Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("old", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    (repo / "tracked.txt").write_text("current", encoding="utf-8")
    (repo / "untracked.txt").write_text("new", encoding="utf-8")
    (repo / "ignored.txt").write_text("secret", encoding="utf-8")

    archive = make_snapshot(git_context(str(repo)))
    try:
        with zipfile.ZipFile(archive) as bundle:
            assert set(bundle.namelist()) == {
                ".gitignore",
                "tracked.txt",
                "untracked.txt",
            }
            assert bundle.read("tracked.txt") == b"current"
    finally:
        archive.unlink()


def test_server_extract_rejects_traversal_and_symlink(tmp_path, monkeypatch):
    pending = tmp_path / "pending"
    pending.mkdir()
    monkeypatch.setattr(handlers, "PENDING_SOURCE_DIR", str(pending))

    traversal_id = str(uuid.uuid4())
    with zipfile.ZipFile(handlers.get_source_archive_path(traversal_id), "w") as bundle:
        bundle.writestr("../outside.txt", "bad")
    with pytest.raises(RuntimeError, match="非法路径"):
        handlers.extract_source_archive(traversal_id, str(tmp_path / "target"))

    symlink_id = str(uuid.uuid4())
    with zipfile.ZipFile(handlers.get_source_archive_path(symlink_id), "w") as bundle:
        info = zipfile.ZipInfo("link")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, "target")
    with pytest.raises(RuntimeError, match="符号链接"):
        handlers.extract_source_archive(symlink_id, str(tmp_path / "target2"))


def test_server_extracts_normal_snapshot(tmp_path, monkeypatch):
    pending = tmp_path / "pending"
    pending.mkdir()
    monkeypatch.setattr(handlers, "PENDING_SOURCE_DIR", str(pending))
    archive_id = str(uuid.uuid4())
    with zipfile.ZipFile(handlers.get_source_archive_path(archive_id), "w") as bundle:
        bundle.writestr("src/main.py", "print('ok')\n")

    target = tmp_path / "target"
    handlers.extract_source_archive(archive_id, str(target))

    assert (target / "src" / "main.py").read_text(encoding="utf-8") == "print('ok')\n"


class _FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.response


def test_cli_pipeline_trigger_uses_cli_source(monkeypatch):
    client = _FakeClient({"task_id": "build-1"})
    monkeypatch.setattr(cli, "follow_task", lambda *args, **kwargs: {"status": "completed"})
    args = cli.parser().parse_args(["pipeline", "trigger", "pipeline-1", "--branch", "main"])

    assert cli.cmd_pipeline(args, client, {"team_id": "team-1"}) == 0
    assert client.calls[0] == (
        "POST",
        "/api/pipelines/pipeline-1/run",
        {"body": {"branch": "main", "trigger_source": "cli"}},
    )


def test_cli_deploy_trigger_uses_cli_source(monkeypatch):
    client = _FakeClient({"task_id": "deploy-1"})
    monkeypatch.setattr(cli, "follow_task", lambda *args, **kwargs: {"status": "completed"})
    args = cli.parser().parse_args(
        ["deploy", "trigger", "config-1", "--target", "production-a"]
    )

    assert cli.cmd_deploy(args, client, {"team_id": "team-1"}) == 0
    assert client.calls[0] == (
        "POST",
        "/api/deploy-tasks/config-1/execute",
        {
            "body": {
                "target_names": ["production-a"],
                "trigger_source": "cli",
            }
        },
    )


def test_cli_build_then_deploy_waits_for_success(monkeypatch, capsys):
    client = _FakeClient(None)

    def request(method, path, **kwargs):
        client.calls.append((method, path, kwargs))
        return {"task_id": "deploy-1"} if "/deploy-tasks/" in path else {"task_id": "build-1"}

    results = iter(
        [
            {"task_id": "build-1", "status": "completed"},
            {"task_id": "deploy-1", "status": "completed"},
        ]
    )
    client.request = request
    monkeypatch.setattr(
        cli,
        "git_context",
        lambda project: {
            "root": Path(project),
            "branch": "main",
            "commit": "abc",
            "remote": "https://example.com/repo.git",
            "dirty": False,
            "upstream": "origin/main",
            "upstream_commit": "abc",
        },
    )
    monkeypatch.setattr(cli, "follow_task", lambda *args, **kwargs: next(results))
    args = cli.parser().parse_args(
        ["build", "--source", "git", "--deploy", "config-1", "--json"]
    )

    assert cli.cmd_build(args, client, {"team_id": "team-1"}) == 0
    assert client.calls[0][1] == "/api/build-with-config"
    assert client.calls[1][1] == "/api/deploy-tasks/config-1/execute"
    output = capsys.readouterr().out
    assert '"build"' in output and '"deployment"' in output


def test_follow_task_streams_incremental_logs_and_reports_failure(capsys):
    class Client:
        def __init__(self):
            self.statuses = iter(("running", "failed"))
            self.pages = iter(
                (
                    {"logs": "step 1\n", "next_after_id": 4},
                    {"logs": "build failed\n", "next_after_id": 7},
                )
            )
            self.queries = []

        def request(self, method, path, **kwargs):
            if path.endswith("/logs"):
                self.queries.append(kwargs["query"])
                return next(self.pages)
            status = next(self.statuses)
            return {"task_id": "task-1", "status": status, "error": "docker build 失败"}

    client = Client()
    task = cli.follow_task(client, "task-1", "team-1", poll_interval=0)

    output = capsys.readouterr()
    assert task["status"] == "failed"
    assert output.out == "step 1\nbuild failed\n"
    assert "任务结束：failed - docker build 失败" in output.err
    assert [query["after_id"] for query in client.queries] == [0, 4]


def test_follow_task_retries_transient_error_and_keeps_json_stdout_clean(capsys):
    class Client:
        def __init__(self):
            self.failed = False

        def request(self, method, path, **kwargs):
            if not self.failed:
                self.failed = True
                raise cli.CLIError("connection reset")
            if path.endswith("/logs"):
                return {"logs": "final log\n", "next_after_id": 2}
            return {"task_id": "task-1", "status": "completed"}

    task = cli.follow_task(
        Client(), "task-1", "team-1", json_output=True, poll_interval=0, retries=1
    )

    output = capsys.readouterr()
    assert task["status"] == "completed"
    assert json.loads(output.out)["status"] == "completed"
    assert "final log" in output.err
    assert "跟踪暂时中断" in output.err


def test_failed_build_does_not_trigger_deployment(monkeypatch):
    client = _FakeClient({"task_id": "build-1"})
    monkeypatch.setattr(
        cli,
        "git_context",
        lambda project: {
            "root": Path(project),
            "branch": "main",
            "commit": "abc",
            "remote": "https://example.com/repo.git",
            "dirty": False,
            "upstream": "origin/main",
            "upstream_commit": "abc",
        },
    )
    monkeypatch.setattr(
        cli, "follow_task", lambda *args, **kwargs: {"status": "failed", "error": "bad Dockerfile"}
    )
    args = cli.parser().parse_args(
        ["build", "--source", "git", "--deploy", "config-1"]
    )

    assert cli.cmd_build(args, client, {"team_id": "team-1"}) == 1
    assert [call[1] for call in client.calls] == ["/api/build-with-config"]


def test_follow_task_timeout_keeps_remote_task_running(monkeypatch):
    class Client:
        def request(self, method, path, **kwargs):
            if path.endswith("/logs"):
                return {"logs": "", "next_after_id": 0}
            return {"task_id": "task-1", "status": "running"}

    ticks = iter((0, 0, 2))
    monkeypatch.setattr(cli.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(cli.time, "sleep", lambda seconds: None)

    with pytest.raises(cli.CLIError, match="远端任务仍在运行"):
        cli.follow_task(Client(), "task-1", "team-1", timeout=1)


def test_server_incremental_logs_return_stable_id_cursor(monkeypatch):
    class Column:
        def __eq__(self, other):
            return self

        def __gt__(self, other):
            return self

        def asc(self):
            return self

    class TaskLog:
        task_id = Column()
        id = Column()

    rows = [
        type("Log", (), {"id": 11, "log_message": "one\n"})(),
        type("Log", (), {"id": 15, "log_message": "two\n"})(),
    ]

    class Query:
        def filter(self, *args):
            return self

        def order_by(self, *args):
            return self

        def all(self):
            return rows

    class Session:
        closed = False

        def query(self, model):
            return Query()

        def close(self):
            self.closed = True

    session = Session()
    monkeypatch.setattr("backend.database.get_db_session", lambda: session)
    monkeypatch.setattr("backend.models.TaskLog", TaskLog)

    logs, cursor = handlers.BuildTaskManager.get_logs_after(object(), "task-1", 7)

    assert logs == "one\ntwo\n"
    assert cursor == 15
    assert session.closed
