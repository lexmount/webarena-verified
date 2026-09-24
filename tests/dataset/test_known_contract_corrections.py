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


def test_multiple_collaborator_invites_match_each_required_request(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    for task_id in (567, 568, 569, 570):
        evaluators = [
            item
            for item in dataset_by_task_id[task_id]["eval"]
            if item["evaluator"] == "NetworkEventEvaluator"
        ]
        assert len(evaluators) > 1
        assert all(item["last_event_only"] is False for item in evaluators)


def test_single_assignee_id_is_typed_as_an_array(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    evaluator = next(
        item
        for item in dataset_by_task_id[811]["eval"]
        if item["evaluator"] == "NetworkEventEvaluator"
    )
    assert evaluator["post_data_schema"]["properties"]["$.issue.assignee_ids"] == {
        "type": "array",
        "items": {"type": "integer"},
    }
