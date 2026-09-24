"""Regression coverage for network contracts that depend on runtime events."""

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from webarena_verified import WebArenaVerified


def _entry(
    *,
    method: str,
    url: str,
    post_data: dict[str, Any],
    status: int,
    mime_type: str = "application/json",
) -> dict[str, Any]:
    body = json.dumps(post_data) if mime_type == "application/json" else urlencode(post_data, doseq=True)
    return {
        "startedDateTime": "2026-01-01T00:00:00.000Z",
        "time": 1,
        "request": {
            "method": method,
            "url": url,
            "headers": [],
            "cookies": [],
            "queryString": [],
            "postData": {"mimeType": mime_type, "text": body},
        },
        "response": {
            "status": status,
            "headers": [],
            "cookies": [],
            "content": {"size": 0, "mimeType": "application/json", "text": "{}"},
            "redirectURL": "",
        },
        "cache": {},
        "timings": {"send": 0, "wait": 1, "receive": 0},
    }


def _evaluate(wa: WebArenaVerified, tmp_path: Path, task_id: int, entries: list[dict[str, Any]]):
    trace = tmp_path / f"task-{task_id}.har"
    trace.write_text(
        json.dumps(
            {
                "log": {
                    "version": "1.2",
                    "creator": {"name": "pytest", "version": "1"},
                    "entries": entries,
                }
            }
        )
    )
    return wa.evaluate_task(
        task_id=task_id,
        agent_response={"task_type": "MUTATE", "status": "SUCCESS", "retrieved_data": None},
        network_trace=trace,
    )


def test_repeated_endpoint_contracts_match_distinct_request_bodies(wa: WebArenaVerified, tmp_path: Path) -> None:
    task = wa.get_task(567)
    expected = [item.expected for item in task.network_event_evaluator_cfgs]
    assert all(isinstance(item.url, str) for item in expected)
    entries = [
        _entry(
            method=item.http_method,
            url=str(item.url).replace("__GITLAB__", "http://localhost:8023"),
            post_data=dict(item.post_data or {}),
            status=item.response_status,
        )
        for item in expected
    ]

    assert float(_evaluate(wa, tmp_path, 567, entries).score) == 1.0
    assert float(_evaluate(wa, tmp_path, 567, entries[1:]).score) == 0.0


@pytest.mark.parametrize("task_id", [742, 743, 745, 746])
def test_project_creation_with_multiple_members_matches_complete_trace(
    wa: WebArenaVerified, tmp_path: Path, task_id: int
) -> None:
    task = wa.get_task(task_id)
    entries = []
    for config in task.network_event_evaluator_cfgs:
        expected = config.expected
        url = (
            "http://localhost:8023/api/v4/projects"
            if expected.url == "__GITLAB__/api/v4/projects"
            else "http://localhost:8023/api/v4/projects/4242/members"
        )
        entries.append(
            _entry(
                method=expected.http_method,
                url=url,
                post_data=dict(expected.post_data or {}),
                status=expected.response_status,
            )
        )

    assert float(_evaluate(wa, tmp_path, task_id, entries).score) == 1.0


@pytest.mark.parametrize(("origin", "expected_score"), [("http://localhost:9999", 1.0), ("http://wrong.test", 0.0)])
def test_markdown_form_values_derender_embedded_urls(
    wa: WebArenaVerified, tmp_path: Path, origin: str, expected_score: float
) -> None:
    task = wa.get_task(562)
    project, commit = [item.expected for item in task.network_event_evaluator_cfgs]
    assert project.post_data is not None
    assert commit.post_data is not None
    content = commit.post_data["$.actions[0].content"].replace("__REDDIT__", origin)
    entries = [
        _entry(
            method="POST",
            url="http://localhost:8023/projects",
            post_data={key: value for key, value in project.post_data.items() if value is not None},
            status=302,
            mime_type="application/x-www-form-urlencoded",
        ),
        _entry(
            method="POST",
            url="http://localhost:8023/api/v4/projects/byteblaze%2FAwesome_DIY_ideas/repository/commits",
            post_data={
                "branch": "main",
                "actions": [{"action": "create", "file_path": "README.md", "content": content}],
            },
            status=201,
        ),
    ]
    assert float(_evaluate(wa, tmp_path, 562, entries).score) == expected_score


@pytest.mark.parametrize(("origin", "expected_score"), [("http://localhost:8023", 1.0), ("http://wrong.test", 0.0)])
def test_plain_form_values_derender_embedded_urls(
    wa: WebArenaVerified, tmp_path: Path, origin: str, expected_score: float
) -> None:
    expected = wa.get_task(684).network_event_evaluator_cfgs[0].expected
    assert expected.post_data is not None
    post_data = dict(expected.post_data)
    post_data["submission[url]"] = post_data["submission[url]"].replace("__GITLAB__", origin)
    entries = [
        _entry(
            method="POST",
            url="http://localhost:9999/submit/LifeProTips",
            post_data=post_data,
            status=302,
            mime_type="application/x-www-form-urlencoded",
        )
    ]
    assert float(_evaluate(wa, tmp_path, 684, entries).score) == expected_score


def test_last_event_only_rejects_a_later_wrong_request_to_the_same_endpoint(
    wa: WebArenaVerified, tmp_path: Path
) -> None:
    expected = wa.get_task(684).network_event_evaluator_cfgs[0].expected
    assert expected.post_data is not None
    correct = dict(expected.post_data)
    correct["submission[url]"] = correct["submission[url]"].replace("__GITLAB__", "http://localhost:8023")
    wrong = {**correct, "submission[title]": "wrong title"}
    entries = [
        _entry(
            method="POST",
            url="http://localhost:9999/submit/LifeProTips",
            post_data=post_data,
            status=302,
            mime_type="application/x-www-form-urlencoded",
        )
        for post_data in (correct, wrong)
    ]

    assert float(_evaluate(wa, tmp_path, 684, entries).score) == 0.0


def test_dynamic_contract_binds_one_value_across_url_and_form_key(wa: WebArenaVerified, tmp_path: Path) -> None:
    entries = [
        _entry(
            method="POST",
            url="http://localhost:9999/submit/books",
            post_data={"submission[title]": "Harry Potter", "submission[forum]": "10037"},
            status=302,
            mime_type="application/x-www-form-urlencoded",
        ),
        _entry(
            method="POST",
            url="http://localhost:9999/f/books/1111/-/comment",
            post_data={"reply_to_submission_2222[comment]": "Wonderful journey"},
            status=302,
            mime_type="application/x-www-form-urlencoded",
        ),
        _entry(
            method="POST",
            url="http://localhost:9999/f/books/4242/-/comment",
            post_data={"reply_to_submission_4242[comment]": "Wonderful journey"},
            status=302,
            mime_type="application/x-www-form-urlencoded",
        ),
    ]
    assert float(_evaluate(wa, tmp_path, 611, entries).score) == 1.0

    entries.append(
        _entry(
            method="POST",
            url="http://localhost:9999/f/books/4242/-/comment",
            post_data={"reply_to_submission_4242[comment]": "wrong final comment"},
            status=302,
            mime_type="application/x-www-form-urlencoded",
        )
    )
    assert float(_evaluate(wa, tmp_path, 611, entries).score) == 0.0

    entries.pop()
    entries[2]["request"]["postData"]["text"] = urlencode({"reply_to_submission_9999[comment]": "Wonderful journey"})
    assert float(_evaluate(wa, tmp_path, 611, entries).score) == 0.0


def test_dynamic_post_binding_does_not_split_last_event_stream(wa: WebArenaVerified, tmp_path: Path) -> None:
    entries = [
        _entry(
            method="POST",
            url="http://localhost:9999/submit/MachineLearning",
            post_data={
                "submission[title]": "what is the SOTA web navigation agent repo",
                "submission[forum]": "10037",
            },
            status=302,
            mime_type="application/x-www-form-urlencoded",
        ),
        _entry(
            method="POST",
            url="http://localhost:9999/submit/MachineLearning",
            post_data={"submission[title]": "wrong final title", "submission[forum]": "99999"},
            status=302,
            mime_type="application/x-www-form-urlencoded",
        ),
    ]

    assert float(_evaluate(wa, tmp_path, 604, entries).score) == 0.0


def test_singleton_array_post_contract_is_an_array_not_an_alternative(wa: WebArenaVerified, tmp_path: Path) -> None:
    config = wa.get_task(811).network_event_evaluator_cfgs[0]
    assert config.post_data_schema == {
        "type": "object",
        "properties": {"$.issue.assignee_ids": {"type": "array", "items": {"type": "integer"}}},
    }
    entries = [
        _entry(
            method="PUT",
            url="http://localhost:8023/a11yproject/a11yproject.com/-/issues/1478.json",
            post_data={"issue": {"assignee_ids": [2330]}},
            status=200,
        )
    ]
    assert float(_evaluate(wa, tmp_path, 811, entries).score) == 1.0

    entries[0]["request"]["postData"]["text"] = json.dumps({"issue": {"assignee_ids": ["2330"]}})
    assert float(_evaluate(wa, tmp_path, 811, entries).score) == 0.0
