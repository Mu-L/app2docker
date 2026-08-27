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


def test_buildx_registry_login_uses_password_stdin(monkeypatch):
    calls = []

    monkeypatch.setattr("backend.docker_builder.shutil.which", lambda _name: "docker")

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("backend.docker_builder.subprocess.run", fake_run)

    LocalDockerBuilder._login_registry_cli(
        {
            "username": "builder",
            "password": "secret-value",
            "serveraddress": "registry.example.com",
        }
    )

    command, kwargs = calls[0]
    assert command == [
        "docker",
        "login",
        "registry.example.com",
        "--username",
        "builder",
        "--password-stdin",
    ]
    assert kwargs["input"] == "secret-value"
    assert "secret-value" not in command
