from backend.handlers import resolve_multi_service_stage_selection


def test_multi_service_stage_selection_skips_missing_services():
    stage_map, matched, missing = resolve_multi_service_stage_selection(
        ["api", "web"], [{"name": "api"}]
    )

    assert stage_map == {"api": "api"}
    assert matched == ["api"]
    assert missing == ["web"]


def test_multi_service_stage_selection_keeps_all_matched_services():
    stage_map, matched, missing = resolve_multi_service_stage_selection(
        ["api", "web"], [{"name": "api"}, {"name": "web"}]
    )

    assert stage_map == {"api": "api", "web": "web"}
    assert matched == ["api", "web"]
    assert missing == []


def test_multi_service_stage_selection_reports_all_missing_services():
    stage_map, matched, missing = resolve_multi_service_stage_selection(
        ["api", "web"], [{"name": "worker"}]
    )

    assert stage_map == {}
    assert matched == []
    assert missing == ["api", "web"]


def test_missing_service_with_push_config_is_not_selected_for_build_or_push():
    service_push_config = {
        "api": {"push": False, "imageName": "repo/api", "tag": "latest"},
        "web": {"push": True, "imageName": "repo/web", "tag": "latest"},
    }

    _, matched, missing = resolve_multi_service_stage_selection(
        ["api", "web"], [{"name": "api"}]
    )
    push_candidates = [
        service
        for service in matched
        if service_push_config.get(service, {}).get("push")
    ]

    assert missing == ["web"]
    assert push_candidates == []
