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
    assert "project[initialize_with_readme]" not in post_data


def test_reddit_contracts_accept_the_route_bound_to_the_required_forum_id(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    expected_routes = {
        600: "__REDDIT__/submit/gaming",
        605: "__REDDIT__/submit/gaming",
        609: "__REDDIT__/submit/technology",
        625: "__REDDIT__/submit/technology",
    }
    for task_id, route in expected_routes.items():
        assert route in _network_expectations(dataset_by_task_id[task_id])[0]["url"]


def test_order_grid_xhr_is_not_replaced_by_the_last_same_route_event(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    task = dataset_by_task_id[676]
    network_evaluator = next(item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator")
    assert network_evaluator["last_event_only"] is False


def test_indexed_form_fields_are_not_encoded_as_singleton_alternatives(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    for task_id in (699, 700):
        post_data = _network_expectations(dataset_by_task_id[task_id])[0]["post_data"]
        assert post_data["website_ids[0]"] == "1"
        assert post_data["customer_group_ids[0]"] == "1"
        assert "website_ids" not in post_data
        assert "customer_group_ids" not in post_data
