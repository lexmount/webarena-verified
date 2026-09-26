"""Regression coverage for navigation tasks accepted through an XHR event."""

import json
from pathlib import Path
from typing import Any

import pytest

from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig
from webarena_verified.types.eval import EvalStatus


def _entry(url: str, *, referer: str, navigation: bool) -> dict[str, Any]:
    headers = [{"name": "Referer", "value": referer}]
    if navigation:
        headers.extend(
            [
                {"name": "Accept", "value": "text/html"},
                {"name": "Sec-Fetch-Dest", "value": "document"},
                {"name": "Sec-Fetch-Mode", "value": "navigate"},
                {"name": "Sec-Fetch-User", "value": "?1"},
            ]
        )
    return {
        "startedDateTime": "2026-01-01T00:00:00.000Z",
        "time": 1,
        "request": {"method": "GET", "url": url, "headers": headers, "cookies": [], "queryString": []},
        "response": {
            "status": 200,
            "headers": [],
            "cookies": [],
            "content": {"size": 0, "mimeType": "application/json", "text": "{}"},
            "redirectURL": "",
        },
        "cache": {},
        "timings": {"send": 0, "wait": 1, "receive": 0},
    }


@pytest.mark.parametrize("ending", ["fraud", "notification", "cleared", "left_page", "reloaded"])
def test_navigate_task_checks_the_final_order_grid(tmp_path: Path, ending: str) -> None:
    base_url = "http://localhost:7780/admin"
    trace = {
        "log": {
            "version": "1.2",
            "creator": {"name": "pytest", "version": "1"},
            "entries": [
                _entry(
                    f"{base_url}/sales/order/",
                    referer=f"{base_url}/admin/dashboard/",
                    navigation=True,
                ),
                _entry(
                    f"{base_url}/mui/index/render/?namespace=sales_order_grid&search="
                    "&keywordUpdated=false&filters%5Bplaceholder%5D=true&filters%5Bstatus%5D=fraud",
                    referer=f"{base_url}/sales/order/",
                    navigation=False,
                ),
            ],
        }
    }
    if ending == "notification":
        trace["log"]["entries"].append(
            _entry(
                f"{base_url}/mui/index/render/?namespace=notification_area",
                referer=f"{base_url}/sales/order/",
                navigation=False,
            )
        )
    elif ending == "cleared":
        trace["log"]["entries"].append(
            _entry(
                f"{base_url}/mui/index/render/?namespace=sales_order_grid&search="
                "&keywordUpdated=false&filters%5Bplaceholder%5D=true",
                referer=f"{base_url}/sales/order/",
                navigation=False,
            )
        )
    elif ending in {"left_page", "reloaded"}:
        path = "admin/dashboard/" if ending == "left_page" else "sales/order/"
        trace["log"]["entries"].append(
            _entry(
                f"{base_url}/{path}",
                referer=f"{base_url}/sales/order/",
                navigation=True,
            )
        )
    trace_path = tmp_path / "network.har"
    trace_path.write_text(json.dumps(trace))

    evaluator = WebArenaVerified(
        config=WebArenaVerifiedConfig(
            test_data_file=Path(__file__).parents[2] / "assets/dataset/webarena-verified.json",
            environments={
                "__SHOPPING_ADMIN__": {
                    "urls": [base_url],
                    "active_url_idx": 0,
                    "use_header_login": True,
                    "credentials": {"username": "admin", "password": "admin1234"},
                }
            },
        )
    )
    result = evaluator.evaluate_task(
        task_id=676,
        agent_response={"task_type": "NAVIGATE", "status": "SUCCESS", "retrieved_data": None},
        network_trace=trace_path,
    )

    assert (result.status == EvalStatus.SUCCESS) is (ending in {"fraud", "notification"})


def test_navigate_task_with_empty_har_is_a_normal_failure(tmp_path: Path) -> None:
    """A valid empty capture must reach the evaluator instead of crashing as Playwright JSONL."""
    base_url = "http://localhost:7780/admin"
    trace_path = tmp_path / "network.har"
    trace_path.write_text(
        json.dumps(
            {
                "log": {
                    "version": "1.2",
                    "creator": {"name": "pytest", "version": "1"},
                    "entries": [],
                }
            }
        )
    )
    evaluator = WebArenaVerified(
        config=WebArenaVerifiedConfig(
            test_data_file=Path(__file__).parents[2] / "assets/dataset/webarena-verified.json",
            environments={
                "__SHOPPING_ADMIN__": {
                    "urls": [base_url],
                    "active_url_idx": 0,
                    "use_header_login": True,
                    "credentials": {"username": "admin", "password": "admin1234"},
                }
            },
        )
    )

    result = evaluator.evaluate_task(
        task_id=676,
        agent_response={"task_type": "NAVIGATE", "status": "SUCCESS", "retrieved_data": None},
        network_trace=trace_path,
    )

    assert result.status == EvalStatus.FAILURE
    assert result.score == 0
    assert result.error_msg is None
