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
