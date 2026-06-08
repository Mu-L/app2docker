"""Multi-service tag override and branch mapping resolution tests."""

from backend.handlers import pipeline_to_task_config, resolve_multi_service_tag


def test_resolve_multi_service_tag_mapping_always_wins():
    cfg = {"tag": "dev", "push": False}
    assert (
        resolve_multi_service_tag(
            cfg, pipeline_tag="latest", mapped_tag="staging", task_tag="latest"
        )
        == "staging"
    )

    cfg_empty = {"tag": "", "push": False}
    assert (
        resolve_multi_service_tag(
            cfg_empty, pipeline_tag="latest", mapped_tag="dev", task_tag="latest"
        )
        == "dev"
    )


def test_resolve_multi_service_tag_without_mapping_uses_service_tag():
    cfg = {"tag": "v2.0", "push": False}
    assert (
        resolve_multi_service_tag(
            cfg, pipeline_tag="latest", mapped_tag=None, task_tag="latest"
        )
        == "v2.0"
    )


def test_pipeline_to_task_config_mapping_overrides_per_service_tag():
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
            "worker": {
                "push": False,
                "imageName": "myapp/demo/worker",
                "tag": "v1.0",
            },
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
