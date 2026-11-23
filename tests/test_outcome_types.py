"""The Python API accepts only pass/fail values: bool, numpy bool, or the integers 0 and 1."""

import numpy as np
import pytest

from realdelta import case_changes, compare, macro_pass_rate, pass_rate_interval


@pytest.mark.parametrize("bad", ["fail", "False", "true", 0.3, 1.0, 2, -1, None, [True]])
def test_non_pass_fail_values_raise(bad):
    for call in (lambda o: pass_rate_interval(o), lambda o: macro_pass_rate(o)):
        with pytest.raises(TypeError, match="pass/fail"):
            call({"a": [True, bad, False]})
    with pytest.raises(TypeError, match="pass/fail"):
        compare({"a": [True, True]}, {"a": [bad, True]})
    with pytest.raises(TypeError, match="pass/fail"):
        case_changes({"a": [True, True]}, {"a": [bad, True]})


def test_error_does_not_echo_the_value():
    with pytest.raises(TypeError) as err:
        pass_rate_interval({"a": ["sk-secret-looking"]})
    assert "sk-secret" not in str(err.value)


def test_accepted_types_give_the_same_answer():
    ref = pass_rate_interval({"a": [True, False, True], "b": [True, True, True]})
    for outcomes in ({"a": [1, 0, 1], "b": [1, 1, 1]},
                     {"a": np.array([True, False, True]), "b": np.ones(3, dtype=bool)},
                     {"a": np.array([1, 0, 1]), "b": [np.int64(1)] * 3}):
        assert pass_rate_interval(outcomes) == ref
