"""Null alternatives must be explicit; empty strings do not make a field optional."""

import pytest

from webarena_verified.core.evaluation.data_types import NormalizedString
from webarena_verified.core.evaluation.value_comparator import ValueComparator


@pytest.mark.parametrize(("expected", "accepted"), [([None, "0"], True), (["", "0"], False), (["0", "1"], False)])
def test_absence_requires_an_explicit_null_alternative(expected, accepted):
    failures = ValueComparator().compare(actual=None, expected=NormalizedString(expected))
    assert (not failures) is accepted
