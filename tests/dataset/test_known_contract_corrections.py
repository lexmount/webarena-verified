"""Regression tests for evaluator contracts corrected from observed valid traces."""

from typing import Any


def _network_expectations(task: dict[str, Any]) -> list[dict[str, Any]]:
    return [item["expected"] for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator"]


def test_issue_list_route_accepts_the_query_bearing_page_url(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    route = _network_expectations(dataset_by_task_id[339])[0]["url"]
    assert route == r"^__GITLAB__/a11yproject/a11yproject\.com/-/issues/?$"


def test_empty_project_does_not_require_an_unchecked_checkbox_field(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    post_data = _network_expectations(dataset_by_task_id[475])[0]["post_data"]
    assert post_data["project[initialize_with_readme]"] == [None, "0"]


def test_order_grid_checks_the_last_xhr_on_the_final_page(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    task = dataset_by_task_id[676]
    network_evaluator = next(item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator")
    assert network_evaluator["navigation_only"] is False
    assert network_evaluator.get("last_event_only", True) is True


def test_indexed_form_fields_are_not_encoded_as_singleton_alternatives(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    for task_id in (699, 700):
        post_data = _network_expectations(dataset_by_task_id[task_id])[0]["post_data"]
        assert post_data["website_ids[0]"] == "1"
        assert post_data["customer_group_ids[0]"] == "1"
        assert "website_ids" not in post_data
        assert "customer_group_ids" not in post_data


def test_repeated_member_requests_explicitly_match_any_event(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    for task_id in (567, 568, 569, 570):
        task = dataset_by_task_id[task_id]
        evaluators = [item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator"]
        assert task["revision"] == 3
        assert all(item["last_event_only"] is False for item in evaluators)

    for task_id in (742, 743, 745, 746):
        task = dataset_by_task_id[task_id]
        member_evaluators = [
            item
            for item in task["eval"]
            if item["evaluator"] == "NetworkEventEvaluator" and item["expected"]["url"].endswith("/members$")
        ]
        assert task["revision"] == 3
        assert len(member_evaluators) > 1
        assert all(item["last_event_only"] is False for item in member_evaluators)


def test_issue_assignee_array_has_an_explicit_integer_contract(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    task = dataset_by_task_id[811]
    evaluator = next(item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator")
    assert task["revision"] == 3
    assert evaluator["post_data_schema"] == {
        "type": "object",
        "properties": {"$.issue.assignee_ids": {"type": "array", "items": {"type": "integer"}}},
    }
