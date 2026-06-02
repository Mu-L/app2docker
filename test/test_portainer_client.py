import unittest
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.portainer_client import PortainerClient


class FakePortainerClient(PortainerClient):
    def __init__(self):
        self.endpoint_id = 7
        self.calls = []
        self.stacks = [{"Id": 42, "Name": "demo", "EndpointId": 7}]
        self.stack_file = "services:\n  app:\n    image: repo/app:latest\n"
        self.delete_error = None
        self.force_update_error = None
        self.services_error = None
        self.pull_error = None
        self.pulled_images = []
        self.services = [
            {
                "ID": "svc1",
                "Version": {"Index": 11},
                "Spec": {
                    "Name": "demo_app",
                    "Labels": {"app2docker.deploy.revision": "task-1"},
                    "TaskTemplate": {
                        "ForceUpdate": 0,
                        "ContainerSpec": {"Image": "repo/app:latest@sha256:old"}
                    },
                },
            }
        ]
        self.tasks = []
        self.nodes = [
            {
                "ID": "node1",
                "Description": {"Hostname": "worker-1"},
            }
        ]
        self.compose_containers = [
            {
                "Id": "ctr1",
                "Names": ["/demo_web_1"],
                "Image": "repo/app:latest",
                "ImageID": "sha256:current",
                "Labels": {
                    "com.docker.compose.project": "demo",
                    "com.docker.compose.service": "web",
                    "com.docker.compose.config-hash": "abc",
                    "com.docker.compose.oneoff": "False",
                    "app2docker.deploy.revision": "task-1",
                },
            }
        ]
        self.images = [
            {
                "Id": "sha256:current",
                "RepoTags": ["repo/app:latest"],
                "RepoDigests": ["repo/app@sha256:current"],
            }
        ]

    def _request(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        if method == "GET" and endpoint == "/stacks":
            return list(self.stacks)
        if method == "GET" and endpoint == "/stacks/42":
            if not self.stacks:
                raise Exception("not found")
            return dict(self.stacks[0])
        if method == "GET" and endpoint == "/stacks/42/file":
            return {"StackFileContent": self.stack_file}
        if method == "PUT" and endpoint == "/stacks/42":
            return {}
        if method == "DELETE" and endpoint == "/stacks/42":
            if self.delete_error:
                raise self.delete_error
            self.stacks = []
            return {}
        if method == "GET" and endpoint == "/endpoints/7/docker/services":
            if self.services_error:
                raise self.services_error
            return list(self.services)
        if method == "PUT" and endpoint == "/endpoints/7/forceupdateservice":
            if self.force_update_error:
                raise self.force_update_error
            return {}
        if method == "POST" and endpoint.startswith("/endpoints/7/docker/services/"):
            if self.force_update_error:
                raise self.force_update_error
            return {}
        if method == "GET" and endpoint == "/endpoints/7/docker/tasks":
            return list(self.tasks)
        if method == "GET" and endpoint == "/endpoints/7/docker/nodes":
            return list(self.nodes)
        if method == "GET" and endpoint == "/endpoints/7/docker/containers/json":
            filters = kwargs.get("params", {}).get("filters")
            if filters and "com.docker.compose.project=demo" in filters:
                return list(self.compose_containers)
            return []
        if method == "GET" and endpoint == "/endpoints/7/docker/images/json":
            return list(self.images)
        if method == "GET" and endpoint == "/endpoints/7/registries":
            return [{"Id": 3, "URL": "registry.example.com", "Name": "registry.example.com"}]
        if method == "DELETE" and endpoint.startswith("/endpoints/7/docker/containers/"):
            deleted_id = endpoint.rsplit("/", 1)[-1]
            self.compose_containers = [
                c for c in self.compose_containers if c.get("Id") != deleted_id
            ]
            return {}
        raise AssertionError(f"Unexpected request: {method} {endpoint}")

    def pull_image(self, image):
        self.pulled_images.append(image)
        if self.pull_error:
            raise self.pull_error
        return {"success": True, "image": image, "last_status": "Downloaded newer image"}


class PortainerClientTests(unittest.TestCase):
    def test_update_stack_requests_pull_image(self):
        client = FakePortainerClient()

        result = client.update_stack(42, client.stack_file, stack_name="demo")

        stack_put_calls = [
            call for call in client.calls if call[0] == "PUT" and call[1] == "/stacks/42"
        ]
        self.assertEqual(len(stack_put_calls), 1)
        payload = stack_put_calls[0][2]["json"]
        self.assertTrue(payload["PullImage"])
        self.assertTrue(payload["RepullImageAndRedeploy"])
        self.assertFalse(payload["Prune"])
        self.assertEqual(result["stack_id"], 42)
        self.assertEqual(result["stack_name"], "demo")
        self.assertTrue(result["pull_image"])
        self.assertTrue(result["repull_image_and_redeploy"])
        self.assertEqual(client.pulled_images, ["repo/app:latest"])
        self.assertTrue(result["explicit_pull"]["success"])

    def test_update_stack_fails_when_explicit_pull_fails(self):
        client = FakePortainerClient()
        client.pull_error = Exception("manifest unknown")

        result = client.update_stack(42, client.stack_file, stack_name="demo")

        self.assertFalse(result["success"])
        self.assertEqual(result["explicit_pull"]["failed"][0]["image"], "repo/app:latest")
        self.assertIn("manifest unknown", result["explicit_pull"]["failed"][0]["error"])

    def test_extract_mutable_compose_images_skips_digest_and_build_only(self):
        content = """
services:
  latest:
    image: repo/app:latest
  implicit:
    image: repo/worker
  pinned:
    image: repo/api@sha256:abc
  build_only:
    build: .
  empty:
    image: ""
"""

        result = PortainerClient.extract_mutable_compose_images(content)

        self.assertEqual(
            result,
            [
                {"service": "latest", "image": "repo/app:latest"},
                {"service": "implicit", "image": "repo/worker"},
            ],
        )

    def test_update_stack_force_updates_swarm_services(self):
        client = FakePortainerClient()
        client.services.append(
            {
                "ID": "svc2",
                "Version": {"Index": 12},
                "Spec": {
                    "Name": "demo_worker",
                    "Labels": {"app2docker.deploy.revision": "task-1"},
                    "TaskTemplate": {
                        "ForceUpdate": 2,
                        "ContainerSpec": {"Image": "repo/worker:latest@sha256:new"}
                    },
                },
            }
        )

        compose = """
services:
  app:
    image: repo/app:latest
  worker:
    image: repo/worker:latest
"""

        result = client.update_stack(42, compose, stack_name="demo")

        update_calls = [
            call
            for call in client.calls
            if call[0] == "POST"
            and call[1].startswith("/endpoints/7/docker/services/")
        ]
        self.assertEqual(len(update_calls), 2)
        payloads = [call[2]["json"] for call in update_calls]
        self.assertEqual(
            [payload["TaskTemplate"]["ContainerSpec"]["Image"] for payload in payloads],
            ["repo/app:latest", "repo/worker:latest"],
        )
        self.assertEqual(
            [payload["TaskTemplate"]["ForceUpdate"] for payload in payloads],
            [1, 3],
        )
        self.assertEqual(update_calls[0][2]["params"]["version"], 11)
        self.assertEqual(update_calls[1][2]["params"]["version"], 12)
        self.assertTrue(result["success"])
        self.assertEqual(result["force_update"]["service_count"], 2)
        self.assertEqual(
            [svc["method"] for svc in result["force_update"]["updated_services"]],
            ["service_update", "service_update"],
        )

    def test_force_update_falls_back_when_compose_image_not_mapped(self):
        client = FakePortainerClient()

        result = client.force_update_swarm_stack_services("demo", [])

        force_calls = [
            call
            for call in client.calls
            if call[0] == "PUT" and call[1] == "/endpoints/7/forceupdateservice"
        ]
        self.assertEqual(len(force_calls), 1)
        self.assertEqual(
            force_calls[0][2]["json"], {"ServiceID": "svc1", "PullImage": True}
        )
        self.assertTrue(result["success"])
        self.assertEqual(
            result["updated_services"][0]["method"], "forceupdateservice"
        )

    def test_resolve_registry_id_for_image_matches_endpoint_registry(self):
        client = FakePortainerClient()

        registry_id = client.resolve_registry_id_for_image("registry.example.com/app:latest")

        self.assertEqual(registry_id, 3)

    def test_update_stack_fails_when_force_update_fails(self):
        client = FakePortainerClient()
        client.force_update_error = Exception("pull denied")

        result = client.update_stack(42, client.stack_file, stack_name="demo")

        self.assertFalse(result["success"])
        self.assertEqual(len(result["force_update"]["failed_services"]), 1)
        self.assertIn("pull denied", result["force_update"]["failed_services"][0]["error"])

    def test_update_stack_skips_force_update_when_no_swarm_services(self):
        client = FakePortainerClient()
        client.services = []

        result = client.update_stack(42, client.stack_file, stack_name="demo")

        force_calls = [
            call
            for call in client.calls
            if call[0] == "PUT" and call[1] == "/endpoints/7/forceupdateservice"
        ]
        self.assertEqual(force_calls, [])
        self.assertTrue(result["success"])
        self.assertTrue(result["force_update"]["checked"])
        self.assertEqual(result["force_update"]["workload_kind"], "compose")
        self.assertEqual(result["force_update"]["recreated_containers"], [])

    def test_update_stack_treats_non_swarm_endpoint_as_compose(self):
        client = FakePortainerClient()
        client.services_error = Exception("This node is not a swarm manager")

        result = client.update_stack(42, client.stack_file, stack_name="demo")

        self.assertTrue(result["success"])
        self.assertTrue(result["force_update"]["checked"])
        self.assertEqual(result["force_update"]["workload_kind"], "compose")

    def test_update_stack_recreates_stale_compose_container(self):
        client = FakePortainerClient()
        client.services = []
        client.compose_containers[0]["ImageID"] = "sha256:old"
        client.images[0]["Id"] = "sha256:new"

        result = client.update_stack(42, client.stack_file, stack_name="demo")

        delete_calls = [
            call
            for call in client.calls
            if call[0] == "DELETE"
            and call[1].startswith("/endpoints/7/docker/containers/")
        ]
        stack_put_calls = [
            call for call in client.calls if call[0] == "PUT" and call[1] == "/stacks/42"
        ]
        self.assertEqual(len(delete_calls), 1)
        self.assertEqual(len(stack_put_calls), 2)
        self.assertTrue(result["success"])
        self.assertEqual(
            result["force_update"]["recreated_containers"][0]["container_image_id"],
            "sha256:old",
        )
        self.assertEqual(
            result["force_update"]["recreated_containers"][0]["local_image_id"],
            "sha256:new",
        )

    def test_remove_stack_resolves_name_to_id_and_waits_until_gone(self):
        client = FakePortainerClient()

        result = client.remove_stack(stack_name="demo", interval=0)

        self.assertTrue(result["success"])
        self.assertTrue(result["deleted"])
        self.assertEqual(result["stack_id"], 42)
        self.assertIn(("DELETE", "/stacks/42", {"params": {"endpointId": 7}, "timeout": 30}), client.calls)

    def test_remove_stack_raises_when_delete_fails(self):
        client = FakePortainerClient()
        client.delete_error = Exception("boom")

        with self.assertRaises(Exception):
            client.remove_stack(stack_name="demo", interval=0)

    def test_inject_deploy_revision_only_for_non_digest_image_refs(self):
        content = """
services:
  latest:
    image: repo/app:latest
  implicit:
    image: repo/worker
  versioned:
    image: repo/api:v1
  pinned:
    image: repo/api@sha256:abc
"""

        rendered, injected, count = PortainerClient.inject_deploy_revision(
            content, "task-1"
        )
        parsed = yaml.safe_load(rendered)

        self.assertTrue(injected)
        self.assertEqual(count, 3)
        self.assertEqual(
            parsed["services"]["latest"]["deploy"]["labels"][
                "app2docker.deploy.revision"
            ],
            "task-1",
        )
        self.assertEqual(
            parsed["services"]["latest"]["labels"]["app2docker.deploy.revision"],
            "task-1",
        )
        self.assertEqual(
            parsed["services"]["implicit"]["deploy"]["labels"][
                "app2docker.deploy.revision"
            ],
            "task-1",
        )
        self.assertEqual(
            parsed["services"]["versioned"]["deploy"]["labels"][
                "app2docker.deploy.revision"
            ],
            "task-1",
        )
        self.assertNotIn("deploy", parsed["services"]["pinned"])

    def test_deploy_stack_updates_existing_stack_with_revision_metadata(self):
        client = FakePortainerClient()

        result = client.deploy_stack("demo", client.stack_file, revision="task-1")

        self.assertTrue(result["success"])
        self.assertTrue(result["revision_injected"])
        self.assertEqual(result["revision_service_count"], 1)
        put_payload = [
            call for call in client.calls if call[0] == "PUT" and call[1] == "/stacks/42"
        ][0][2]["json"]
        self.assertIn("app2docker.deploy.revision", put_payload["StackFileContent"])

    def test_verify_stack_services_reports_service_images(self):
        client = FakePortainerClient()

        result = client.verify_stack_services(
            "demo", expected_revision="task-1", min_revision_services=1
        )

        self.assertTrue(result["success"])
        self.assertTrue(result["checked"])
        self.assertEqual(result["service_count"], 1)
        self.assertEqual(result["images"], ["repo/app:latest@sha256:old"])
        self.assertEqual(result["matching_revision_services"], 1)

    def test_verify_stack_services_fails_when_revision_is_missing(self):
        client = FakePortainerClient()
        client.services[0]["Spec"]["Labels"] = {}

        result = client.verify_stack_services(
            "demo", expected_revision="task-1", min_revision_services=1
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["missing_revision_count"], 1)

    def test_verify_stack_services_reports_failed_task_details(self):
        client = FakePortainerClient()
        client.tasks = [
            {
                "ID": "task1",
                "ServiceID": "svc1",
                "NodeID": "node1",
                "DesiredState": "running",
                "Status": {
                    "State": "rejected",
                    "Err": "No such image: repo/app:latest",
                },
            }
        ]

        result = client.verify_stack_services(
            "demo", expected_revision="task-1", min_revision_services=1
        )

        self.assertFalse(result["success"])
        failures = result["task_diagnostics"]["failures"]
        self.assertEqual(len(failures), 1)
        self.assertEqual(failures[0]["node"], "worker-1")
        self.assertEqual(failures[0]["service"], "demo_app")
        self.assertIn("No such image", failures[0]["error"])

    def test_get_stack_services_falls_back_to_compose_containers(self):
        client = FakePortainerClient()
        client.services = []

        workloads = client.get_stack_services("demo")

        self.assertEqual(len(workloads), 1)
        self.assertEqual(workloads[0]["workload_kind"], "compose")
        self.assertEqual(workloads[0]["Spec"]["Name"], "web")

    def test_get_stack_services_falls_back_when_swarm_services_error(self):
        client = FakePortainerClient()
        client.services_error = Exception("This node is not a swarm manager")

        workloads = client.get_stack_services("demo")

        self.assertEqual(len(workloads), 1)
        self.assertEqual(workloads[0]["workload_kind"], "compose")

    def test_verify_stack_services_accepts_compose_containers(self):
        client = FakePortainerClient()
        client.services = []

        result = client.verify_stack_services(
            "demo", expected_revision="task-1", min_revision_services=1
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["workload_kind"], "compose")
        self.assertEqual(result["service_count"], 1)
        self.assertEqual(result["matching_revision_services"], 1)


if __name__ == "__main__":
    unittest.main()
