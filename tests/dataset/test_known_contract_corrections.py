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

    for task_id in (699, 700):
        task = dataset_by_task_id[task_id]
        post_data = _network_expectations(task)[0]["post_data"]
        assert task["revision"] == 4
        assert [post_data[f"customer_group_ids[{index}]"] for index in range(3)] == [
            "1",
            "2",
            "3",
        ]


def test_mass_status_contract_targets_the_filtered_magento_mutation(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    task = dataset_by_task_id[423]
    evaluator = next(item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator")
    assert task["revision"] == 3
    assert evaluator["last_event_only"] is True
    assert evaluator["navigation_only"] is False
    assert evaluator["expected"] == {
        "url": r"^__SHOPPING_ADMIN__/catalog/product/massStatus/status/1/?$",
        "http_method": "POST",
        "post_data": {
            "excluded": "false",
            "search": "hollister",
            "namespace": "product_listing",
        },
        "response_status": 302,
    }


def test_existing_color_options_require_only_the_new_product_variations(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    expected = {
        547: ("Phoebe Zipper Sweatshirt", ["size: s, color: brown"]),
        548: ("Frankie  Sweatshirt", ["size: s, color: blue", "size: m, color: blue"]),
    }
    matrix_key = "$['configurable-matrix-serialized'][?(@.newProduct == 1)].attributes"
    for task_id, (product_name, variations) in expected.items():
        task = dataset_by_task_id[task_id]
        evaluators = [item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator"]
        assert task["revision"] == 3
        assert len(evaluators) == 1
        assert "product_attribute/save" not in evaluators[0]["expected"]["url"]
        assert evaluators[0]["expected"]["post_data"]["product[name]"] == product_name
        assert evaluators[0]["expected"]["post_data"][matrix_key] == variations


def test_new_size_options_use_the_native_configurable_product_endpoint(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    for task_id, label in ((549, "XXXL"), (550, "XXS")):
        task = dataset_by_task_id[task_id]
        evaluator = next(
            item
            for item in task["eval"]
            if item["evaluator"] == "NetworkEventEvaluator" and "createOptions" in item["expected"]["url"]
        )
        assert task["revision"] == 3
        assert evaluator["last_event_only"] is True
        assert evaluator["navigation_only"] is False
        assert evaluator["ignored_query_params"] == ["isAjax"]
        assert evaluator["expected"] == {
            "url": r"^__SHOPPING_ADMIN__/catalog/product_attribute/createOptions/?$",
            "http_method": "POST",
            "response_status": 200,
            "post_data": {
                "options[0][label]": label,
                "options[0][attribute_id]": "144",
                "options[0][is_new]": "true",
            },
        }


def test_readme_commit_targets_the_created_repository(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    task = dataset_by_task_id[566]
    commit = _network_expectations(task)[1]
    assert task["revision"] == 3
    assert commit["url"] == "__GITLAB__/api/v4/projects/byteblaze%2Fdo-it-myself/repository/commits"


def test_order_grid_status_contracts_evaluate_the_xhr(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    for task_id in (677, 678, 679, 680):
        task = dataset_by_task_id[task_id]
        evaluator = next(item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator")
        assert task["revision"] == 3
        assert evaluator["navigation_only"] is False
        assert "mui/index/render/" in evaluator["expected"]["url"]


def test_route_contracts_follow_the_intent_origin_to_destination(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    coordinates = {
        265: "-71.0579762,42.3603713;-68.2177005,44.3494709",
        266: "-70.2545299,43.6599147;-68.2177005,44.3494709",
        267: "-68.767507,44.8030715;-68.2177005,44.3494709",
        268: "-68.8315387,44.0478975;-68.2177005,44.3494709",
        737: "-79.9427192,40.4441897;-75.1718916,39.9011873",
        738: "-79.9427192,40.4441897;-75.1712951,39.9042046",
        739: "-79.9427192,40.4441897;-73.9265212,40.8295828",
        740: "-79.9427192,40.4441897;-73.9935443,40.7505085",
        741: "-79.9427192,40.4441897;-71.0621475,42.3662922",
        759: "-71.060511,42.3554334;-74.0060152,40.7127281",
        760: "-75.44225386838299,40.651163100000005;-74.0323752,40.7433066",
    }
    for task_id, coordinate_pair in coordinates.items():
        task = dataset_by_task_id[task_id]
        evaluator = next(item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator")
        expected_revision = 6 if task_id == 760 else 5 if task_id in {265, 266, 267, 268} else 4 if task_id == 759 else 3
        assert task["revision"] == expected_revision
        if task_id not in {265, 266, 267, 268}:
            assert evaluator["navigation_only"] is False
        assert coordinate_pair in evaluator["expected"]["url"]

    task_760_url = next(
        item for item in dataset_by_task_id[760]["eval"] if item["evaluator"] == "NetworkEventEvaluator"
    )["expected"]["url"]
    assert "-74.4041622,40.0757384" not in task_760_url


def test_replay_specific_changes_do_not_weaken_canonical_contracts(
    dataset_by_task_id: dict[int, dict[str, Any]],
) -> None:
    for task_id in (448, 744):
        task = dataset_by_task_id[task_id]
        evaluators = [item for item in task["eval"] if item["evaluator"] == "NetworkEventEvaluator"]
        assert task["revision"] == 2
        assert all(item.get("last_event_only", True) is True for item in evaluators)

    cart_totals = _network_expectations(dataset_by_task_id[510])[1]
    assert cart_totals["response_content"]["items_qty"] == 1


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
