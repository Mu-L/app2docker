from types import SimpleNamespace

from backend.docker_builder import LocalDockerBuilder


def test_multiarch_build_uses_docker_container_builder(monkeypatch):
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        if command[2:4] == ["inspect", "app2docker-multiarch"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="not found")
        return SimpleNamespace(returncode=0, stdout="app2docker-multiarch", stderr="")

    monkeypatch.setattr("backend.docker_builder.subprocess.run", fake_run)
    builder = object.__new__(LocalDockerBuilder)

    assert builder._ensure_buildx_builder("docker", require_container=True) == "app2docker-multiarch"
    assert commands[-1][:6] == [
        "docker",
        "buildx",
        "create",
        "--name",
        "app2docker-multiarch",
        "--driver",
    ]
    assert "docker-container" in commands[-1]
