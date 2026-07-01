"""Pipeline resource package normalization and copy tests."""

import os
import shutil
import tempfile
import uuid
from unittest.mock import MagicMock, patch

from backend.handlers import (
    get_resource_packages_from_task_config,
    normalize_resource_package_configs,
    pipeline_to_task_config,
)
from backend.app2docker_config import config_to_build_params
from backend.resource_package_manager import RESOURCE_PACKAGE_DIR, ResourcePackageManager


def test_normalize_resource_package_configs_dict_list():
    configs = [{"package_id": "abc", "target_path": "settings.xml"}]
    assert normalize_resource_package_configs(configs) == [
        {"package_id": "abc", "target_path": "settings.xml"}
    ]


def test_normalize_resource_package_configs_id_list():
    assert normalize_resource_package_configs(["abc"]) == [
        {"package_id": "abc", "target_path": "resources"}
    ]


def test_normalize_resource_package_configs_target_dir_legacy():
    assert normalize_resource_package_configs(
        [{"package_id": "abc", "target_dir": "conf/settings.xml"}]
    ) == [{"package_id": "abc", "target_path": "conf/settings.xml"}]


def test_normalize_resource_package_configs_json_string():
    raw = '[{"package_id":"abc","target_path":"settings.xml"}]'
    assert normalize_resource_package_configs(raw) == [
        {"package_id": "abc", "target_path": "settings.xml"}
    ]


def test_normalize_resource_package_configs_strips_values():
    configs = [{"package_id": " abc \n", "target_path": " settings.xml "}]
    assert normalize_resource_package_configs(configs) == [
        {"package_id": "abc", "target_path": "settings.xml"}
    ]


def test_normalize_resource_package_configs_invalid():
    assert normalize_resource_package_configs({"bad": True}) == []
    assert normalize_resource_package_configs(None) == []


def test_get_resource_packages_from_task_config_both_keys():
    assert get_resource_packages_from_task_config(
        {"resource_package_configs": [{"package_id": "x", "target_path": "a.xml"}]}
    ) == [{"package_id": "x", "target_path": "a.xml"}]
    assert get_resource_packages_from_task_config(
        {"resource_package_ids": ["y"]}
    ) == [{"package_id": "y", "target_path": "resources"}]


def test_pipeline_to_task_config_resource_packages():
    pipeline = {
        "git_url": "https://example.com/repo.git",
        "image_name": "myapp/demo",
        "tag": "latest",
        "branch": "main",
        "project_type": "jar",
        "resource_package_configs": [
            {"package_id": "pkg-1", "target_path": "settings.xml"}
        ],
    }
    task = pipeline_to_task_config(pipeline, trigger_source="manual")
    assert task["resource_package_ids"] == [
        {"package_id": "pkg-1", "target_path": "settings.xml"}
    ]


def test_app2docker_config_extracts_resource_packages():
    params = config_to_build_params(
        {
            "build": {"project_type": "jar"},
            "image": {"name": "demo", "tag": "dev"},
            "resource_package_ids": [
                {"package_id": " pkg-1 ", "target_path": " settings.xml "}
            ],
        },
        {"branch": "dev"},
    )
    assert params["resource_package_ids"] == [
        {"package_id": "pkg-1", "target_path": "settings.xml"}
    ]


def _mock_db_with_package(mock_package):
    mock_db = MagicMock()
    mock_query = MagicMock()
    mock_query.filter.return_value.first.return_value = mock_package
    mock_db.query.return_value = mock_query
    return mock_db


def test_copy_single_settings_xml_file():
    package_id = str(uuid.uuid4())
    build_ctx = tempfile.mkdtemp()
    pkg_dir = os.path.join(RESOURCE_PACKAGE_DIR, package_id)
    os.makedirs(pkg_dir, exist_ok=True)
    settings_content = "<settings></settings>"
    with open(os.path.join(pkg_dir, "settings.xml"), "w", encoding="utf-8") as f:
        f.write(settings_content)

    mock_package = MagicMock()
    mock_package.package_id = package_id
    mock_package.filename = "settings.xml"
    mock_package.extracted = False

    try:
        with patch(
            "backend.resource_package_manager.get_db_session",
            return_value=_mock_db_with_package(mock_package),
        ):
            manager = ResourcePackageManager()
            copied, warnings = manager.copy_packages_to_build_context(
                [{"package_id": package_id, "target_path": "settings.xml"}],
                build_ctx,
            )
        assert package_id in copied
        assert not warnings
        dst = os.path.join(build_ctx, "settings.xml")
        assert os.path.isfile(dst)
        with open(dst, encoding="utf-8") as f:
            assert f.read() == settings_content
    finally:
        shutil.rmtree(build_ctx, ignore_errors=True)
        shutil.rmtree(pkg_dir, ignore_errors=True)


def test_copy_zip_nested_settings_xml():
    package_id = str(uuid.uuid4())
    build_ctx = tempfile.mkdtemp()
    pkg_dir = os.path.join(RESOURCE_PACKAGE_DIR, package_id)
    extracted = os.path.join(pkg_dir, "extracted", "conf")
    os.makedirs(extracted, exist_ok=True)
    settings_content = "<settings><mirrors/></settings>"
    with open(os.path.join(extracted, "settings.xml"), "w", encoding="utf-8") as f:
        f.write(settings_content)

    mock_package = MagicMock()
    mock_package.package_id = package_id
    mock_package.filename = "settings.zip"
    mock_package.extracted = True

    try:
        with patch(
            "backend.resource_package_manager.get_db_session",
            return_value=_mock_db_with_package(mock_package),
        ):
            manager = ResourcePackageManager()
            copied, warnings = manager.copy_packages_to_build_context(
                [{"package_id": package_id, "target_path": "settings.xml"}],
                build_ctx,
            )
        assert package_id in copied
        assert not warnings
        dst = os.path.join(build_ctx, "settings.xml")
        assert os.path.isfile(dst)
        with open(dst, encoding="utf-8") as f:
            assert "mirrors" in f.read()
    finally:
        shutil.rmtree(build_ctx, ignore_errors=True)
        shutil.rmtree(pkg_dir, ignore_errors=True)
