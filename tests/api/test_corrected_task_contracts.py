"""Exercise corrected contracts through the public HAR evaluation API."""

import json
from pathlib import Path
from urllib.parse import urlencode

import pytest

from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig
from webarena_verified.types.eval import EvalStatus


def _event(url, *, method="GET", form=None, referer=None, navigation=False):
    headers = [{"name": "Referer", "value": referer}] if referer else []
    if navigation:
        headers += [
            {"name": "Accept", "value": "text/html"},
            {"name": "Sec-Fetch-Dest", "value": "document"},
            {"name": "Sec-Fetch-Mode", "value": "navigate"},
            {"name": "Sec-Fetch-User", "value": "?1"},
        ]
    request = {"method": method, "url": url, "headers": headers, "cookies": [], "queryString": []}
    if form is not None:
        request["postData"] = {"mimeType": "application/x-www-form-urlencoded", "text": urlencode(form)}
    return {
        "startedDateTime": "2026-01-01T00:00:00.000Z",
        "time": 1,
        "request": request,
        "response": {
            "status": 302 if form is not None else 200,
            "headers": [],
            "cookies": [],
            "content": {"size": 0, "mimeType": "text/html", "text": ""},
            "redirectURL": "",
        },
        "cache": {},
        "timings": {"send": 0, "wait": 1, "receive": 0},
    }


def _evaluate(tmp_path, task, entries, task_type):
    path = tmp_path / "network.har"
    path.write_text(
        json.dumps({"log": {"version": "1.2", "creator": {"name": "pytest", "version": "1"}, "entries": entries}})
    )
    evaluator = WebArenaVerified(
        config=WebArenaVerifiedConfig(
            test_data_file=Path(__file__).parents[2] / "assets/dataset/webarena-verified.json",
            environments={
                "__GITLAB__": {"urls": ["http://localhost:8023"]},
                "__SHOPPING_ADMIN__": {"urls": ["http://localhost:7780/admin"]},
            },
        )
    )
    return (
        evaluator.evaluate_task(
            task_id=task,
            agent_response={
                "task_type": task_type,
                "status": "SUCCESS",
                "retrieved_data": None,
            },
            network_trace=path,
        ).status
        == EvalStatus.SUCCESS
    )


@pytest.mark.parametrize("left_target", [False, True])
def test_navigation_must_end_on_the_requested_page(tmp_path, left_target):
    entries = [_event("http://localhost:8023/dashboard/todos", navigation=True)]
    if left_target:
        entries.append(_event("http://localhost:8023/dashboard/projects", navigation=True))
    assert _evaluate(tmp_path, 44, entries, "NAVIGATE") is (not left_target)


@pytest.mark.parametrize("route", ["issues", "issues/", "issues/123"])
def test_issue_list_route_does_not_accept_an_issue_detail(tmp_path, route):
    base = "http://localhost:8023"
    expected = base + "/a11yproject/a11yproject.com/-/issues/?state=opened&label_name%5B%5D=bug"
    entries = [
        _event(
            base + "/a11yproject/a11yproject.com/-/" + route + "?state=opened&label_name%5B%5D=bug", navigation=True
        ),
        _event(base + "/api/graphql", method="POST", referer=expected),
    ]
    assert _evaluate(tmp_path, 339, entries, "NAVIGATE") is (route != "issues/123")


@pytest.mark.parametrize("readme", [None, "0", "1"])
def test_empty_project_accepts_unchecked_but_rejects_enabled_readme(tmp_path, readme):
    form = {"project[name]": "chatgpt_plugin", "project[path]": "chatgpt_plugin", "project[namespace_id]": "2505"}
    if readme is not None:
        form["project[initialize_with_readme]"] = readme
    entries = [_event("http://localhost:8023/projects", method="POST", form=form)]
    assert _evaluate(tmp_path, 475, entries, "MUTATE") is (readme != "1")


@pytest.mark.parametrize(
    ("task", "name", "action", "amount"),
    [
        (699, "spring sale", "by_percent", 20),
        (700, "fall discount", "cart_fixed", 10),
    ],
)
@pytest.mark.parametrize("customer_group", ["1", "2"])
def test_price_rule_form_requires_the_requested_customer_group(tmp_path, task, name, action, amount, customer_group):
    form = {
        "name": name,
        "website_ids[0]": "1",
        "customer_group_ids[0]": customer_group,
        "simple_action": action,
        "discount_amount": amount,
    }
    entries = [_event("http://localhost:7780/admin/sales_rule/promo_quote/save/", method="POST", form=form)]
    assert _evaluate(tmp_path, task, entries, "MUTATE") is (customer_group == "1")
