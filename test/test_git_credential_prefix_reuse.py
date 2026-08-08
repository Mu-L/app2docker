from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import backend.git_source_manager as git_sources
import backend.resource_permissions as permissions
import backend.route_definitions as routes
from backend.crypto_utils import encrypt_password
from backend.models import Base, GitSource


def test_personal_git_credentials_reuse_longest_account_prefix(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'git-prefix.db'}")
    Base.metadata.create_all(engine, tables=[GitSource.__table__])
    session = sessionmaker(bind=engine)
    monkeypatch.setattr(git_sources, "get_db_session", session)

    now = datetime.now()
    db = session()
    db.add_all(
        [
            GitSource(
                name="acme",
                git_url="https://git.example.com/acme/service-a.git",
                username="generic",
                password=encrypt_password("generic-token"),
                created_by="alice",
                scope="personal",
                updated_at=now,
            ),
            GitSource(
                name="platform",
                git_url="https://git.example.com/acme/platform/service-a.git",
                username="platform",
                password=encrypt_password("platform-token"),
                created_by="alice",
                scope="personal",
                updated_at=now + timedelta(seconds=1),
            ),
            GitSource(
                name="other account",
                git_url="https://git.example.com/acme/platform/private.git",
                username="bob",
                password=encrypt_password("bob-token"),
                created_by="bob",
                scope="personal",
            ),
        ]
    )
    db.commit()
    db.close()

    manager = git_sources.GitSourceManager()
    assert manager.get_personal_credentials_by_prefix(
        "alice", "https://git.example.com/acme/platform/service-b.git"
    ) == {"username": "platform", "password": "platform-token"}
    assert manager.get_personal_credentials_by_prefix(
        "alice", "https://git.example.com/acme/service-b.git"
    ) == {"username": "generic", "password": "generic-token"}
    assert manager.get_personal_credentials_by_prefix(
        "alice", "https://git.example.com/other/service.git"
    ) is None
    assert manager.get_personal_credentials_by_prefix(
        "alice", "http://git.example.com/acme/service-b.git"
    ) is None


def test_api_resolution_copies_reused_credentials_to_target_source(monkeypatch):
    calls = {}

    class FakeManager:
        def get_personal_source_by_url(self, team_id, user_id, git_url):
            return None

        def get_personal_credentials_by_prefix(self, user_id, git_url):
            return {"username": "alice", "password": "token"}

        def upsert_personal_credentials(self, **kwargs):
            calls.update(kwargs)
            return "source-new", True

    monkeypatch.setattr(git_sources, "GitSourceManager", FakeManager)
    monkeypatch.setattr(
        permissions,
        "grant_creator_admin",
        lambda db, resource_type, resource_id, user_id: calls.update(
            granted=(resource_type, resource_id, user_id)
        ),
    )

    result = routes._resolve_api_git_source(
        object(),
        "alice-id",
        "team-1",
        "https://git.example.com/acme/service-b.git",
    )

    assert result == ("source-new", None, None)
    assert calls["username"] == "alice"
    assert calls["password"] == "token"
    assert calls["granted"] == ("git_source", "source-new", "alice-id")
