"""Multi-service tag override and branch mapping resolution tests."""

from backend.handlers import (
    pipeline_to_task_config,
    resolve_multi_service_tag,
    _is_explicit_service_tag_override,
)


def test_explicit_override_differs_from_pipeline_default():
    assert _is_explicit_service_tag_override("dev", "latest") is True
    assert _is_explicit_service_tag_override("", "latest") is False
    assert _is_explicit_service_tag_override("latest", "latest") is False


def test_resolve_multi_service_tag_priority():
    cfg = {"tag": "dev", "push": False}
    assert (
        resolve_multi_service_tag(cfg, pipeline_tag="latest", mapped_tag="staging", task_tag="latest")
        == "dev"
    )

    cfg_empty = {"tag": "", "push": False}
    assert (
        resolve_multi_service_tag(
            cfg_empty, pipeline_tag="latest", mapped_tag="dev", task_tag="latest"
        )
        == "dev"
    )

    cfg_legacy_latest = {"tag": "latest", "push": False}
    assert (
        resolve_multi_service_tag(
            cfg_legacy_latest, pipeline_tag="latest", mapped_tag="dev", task_tag="latest"
        )
        == "dev"
    )


def test_pipeline_to_task_config_applies_branch_mapping_for_multi_service():
    pipeline = {
        "git_url": "https://example.com/repo.git",
        "image_name": "myapp/demo",
        "tag": "latest",
        "branch": "main",
        "project_type": "web",
        "use_project_dockerfile": True,
        "dockerfile_name": "Dockerfile",
        "push_mode": "multi",
        "selected_services": ["api", "worker"],
        "service_push_config": {
            "api": {"push": False, "imageName": "myapp/demo/api", "tag": "latest"},
            "worker": {"push": False, "imageName": "myapp/demo/worker", "tag": "dev"},
        },
        "branch_tag_mapping": {"dev": "dev"},
    }

    task = pipeline_to_task_config(
        pipeline,
        trigger_source="manual",
        branch="dev",
        tag="latest",
    )

    assert task["tag"] == "dev"
    assert task["service_push_config"]["api"]["tag"] == "dev"
    assert task["service_push_config"]["worker"]["tag"] == "dev"
