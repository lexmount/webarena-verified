"""Books retrieval answers must use titles present in post descriptions."""

import json
from pathlib import Path

import pytest

from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig
from webarena_verified.types.eval import EvalStatus


@pytest.mark.parametrize(
    ("task_id", "answer", "accepted"),
    [
        (67, ["The Hobbit"], True),
        (67, ["The Hobbit", "A Christmas Carol"], False),
        (68, [{"book": "The Hobbit", "author": "Tolkien"}], True),
        (
            68,
            [
                {"book": "The Hobbit", "author": "Tolkien"},
                {"book": "A Christmas Carol", "author": None},
            ],
            False,
        ),
    ],
)
def test_books_description_reference(
    task_id: int, answer: list, accepted: bool, tmp_path: Path
) -> None:
    trace = tmp_path / "network.har"
    trace.write_text(json.dumps({"log": {"version": "1.2", "creator": {"name": "pytest", "version": "1"}, "entries": [{
        "startedDateTime": "2026-01-01T00:00:00.000Z", "time": 1,
        "request": {"method": "GET", "url": "http://localhost:9999/f/books", "headers": [], "cookies": [], "queryString": []},
        "response": {"status": 200, "headers": [], "cookies": [], "content": {"size": 0, "mimeType": "text/html", "text": ""}, "redirectURL": ""},
        "cache": {}, "timings": {"send": 0, "wait": 1, "receive": 0},
    }]}}))
    evaluator = WebArenaVerified(
        config=WebArenaVerifiedConfig(
            test_data_file=Path(__file__).parents[2] / "assets/dataset/webarena-verified.json",
            environments={
                "__REDDIT__": {
                    "urls": ["http://localhost:9999"],
                    "active_url_idx": 0,
                }
            },
        )
    )
    result = evaluator.evaluate_task(
        task_id=task_id,
        agent_response={"task_type": "RETRIEVE", "status": "SUCCESS", "retrieved_data": answer},
        network_trace=trace,
    )
    assert (result.status == EvalStatus.SUCCESS) is accepted
