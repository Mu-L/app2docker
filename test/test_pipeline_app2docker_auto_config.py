import subprocess

import pytest

from backend.app2docker_config import config_to_build_params, inspect_repository_config
from backend.handlers import pipeline_to_task_config


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _create_repo(tmp_path, config_content=None):
    repo = tmp_path / "sample"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "App2Docker Test")
    _git(repo, "config", "user.email", "app2docker-test@localhost")
    (repo / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    if config_content is not None:
        (repo / ".app2docker.yaml").write_text(config_content, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture")
    return repo


def test_pipeline_tasks_enable_optional_repository_config():
    task = pipeline_to_task_config(
        {
            "pipeline_id": "pipeline-1",
            "git_url": "https://example.com/repo.git",
            "branch": "main",
            "image_name": "fallback/image",
            "tag": "fallback",
            "use_project_dockerfile": True,
        },
        trigger_source="manual",
    )

    assert task["config_only_overrides"] is True
    assert task["branch"] == "main"
    assert task["image_name"] == "fallback/image"


def test_pipeline_tasks_preserve_fixed_profile():
    task = pipeline_to_task_config(
        {
            "pipeline_id": "pipeline-1",
            "git_url": "https://example.com/repo.git",
            "branch": "main",
            "profile": "prod",
            "image_name": "fallback/image",
            "tag": "latest",
        },
        trigger_source="manual",
    )

    assert task["profile"] == "prod"


def test_tag_pipeline_uses_git_tag_as_config_profile():
    task = pipeline_to_task_config(
        {
            "pipeline_id": "pipeline-1",
            "git_url": "https://example.com/repo.git",
            "branch": "main",
            "image_name": "fallback/image",
            "tag": "latest",
        },
        trigger_source="manual",
        git_ref_type="tag",
        git_ref_name="v1.2.3",
    )

    assert task["tag_name"] == "v1.2.3"
    assert task["config_only_overrides"] is True


def test_inspect_repository_config_resolves_default_fallback_and_variables(tmp_path):
    repo = _create_repo(
        tmp_path,
        """
version: "1.0"
build:
  project_type: go
  use_project_dockerfile: true
image:
  name: demo
  prefix: registry.example.com/team
  tag: "git-{commit}"
  push: false
""",
    )

    result = inspect_repository_config(str(repo), branch="main")

    assert result["found"] is True
    assert result["requested_profile"] == "main"
    assert result["used_profile"] == "default"
    assert result["config_source"] == ".app2docker.yaml"
    assert result["build_params"]["project_type"] == "go"
    assert result["build_params"]["image_name"] == "registry.example.com/team/demo"
    assert result["build_params"]["tag"] == f"git-{result['commit'][:7]}"
    assert result["build_params"]["push_mode"] == "single"


def test_inspect_repository_config_reports_missing_config(tmp_path):
    repo = _create_repo(tmp_path)

    result = inspect_repository_config(str(repo), branch="main")

    assert result["found"] is False
    assert result["build_params"] == {}
    assert result["warnings"]


def test_config_extracts_and_resolves_docker_build_args():
    params = config_to_build_params(
        {
            "build": {
                "project_type": "nodejs",
                "build_args": {
                    "BUILD_SCRIPT": "build:{profile}",
                    "SOURCE_BRANCH": "{branch}",
                    "ENABLE_CACHE": True,
                    "RETRY_COUNT": 3,
                },
            },
            "image": {"name": "web", "tag": "dev"},
        },
        {"profile": "dev", "branch": "dev"},
    )

    assert params["build_args"] == {
        "BUILD_SCRIPT": "build:dev",
        "SOURCE_BRANCH": "dev",
        "ENABLE_CACHE": "true",
        "RETRY_COUNT": "3",
    }


def test_config_rejects_non_mapping_build_args():
    with pytest.raises(ValueError, match="build.build_args"):
        config_to_build_params(
            {
                "build": {"build_args": ["BUILD_SCRIPT=build:dev"]},
                "image": {"name": "web"},
            },
            {"profile": "dev", "branch": "dev"},
        )
