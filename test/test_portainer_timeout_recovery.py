"""Portainer deploy timeout recovery tests."""

import asyncio

from backend.deploy_executors.portainer_executor import PortainerExecutor


class FakePortainerClient:
    def extract_mutable_compose_images(self, _compose_content):
        return []

    def strip_deploy_revision(self, compose_content):
        return compose_content, False, 0

    def deploy_stack(self, _stack_name, _compose_content):
        return {
            "success": False,
            "message": "部署失败: 连接超时，请检查 Portainer URL 是否正确",
        }

    def get_stack_by_name(self, stack_name):
        return {"Id": 42, "Name": stack_name}

    def verify_stack_services(self, stack_name, _expected_revision=None, _min_revision_services=0):
        return {
            "success": True,
            "checked": True,
            "message": f"Verified 1 container(s) for Stack: {stack_name}",
            "service_count": 1,
            "workload_kind": "compose",
        }


class RecoveringPortainerExecutor(PortainerExecutor):
    def can_execute(self):
        return True

    def _get_portainer_client(self):
        return FakePortainerClient()


def test_portainer_stack_timeout_is_success_when_remote_stack_is_verified():
    executor = RecoveringPortainerExecutor(
        {
            "host_id": "host-1",
            "name": "portainer-host",
            "host_type": "portainer",
            "portainer_url": "http://portainer.example",
            "portainer_endpoint_id": 1,
            "status": "online",
        }
    )
    logs = []

    result = asyncio.run(
        executor.execute(
            deploy_config={
                "deploy_mode": "docker_compose",
                "compose_content": "version: '3.8'\nservices:\n  app:\n    image: nginx:latest\n",
                "stack_strategy": "create_new",
                "stack_name": "demo-stack",
            },
            task_id="task-1",
            target_name="target-1",
            context={"app": {"name": "demo"}},
            update_status_callback=logs.append,
        )
    )

    assert result["success"] is True
    assert result["timeout_recovered"] is True
    assert result["stack_id"] == 42
    assert result["stack_name"] == "demo-stack"
    assert any("超时后确认成功" in item for item in logs)
