import pytest
hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given, strategies as st
from recoveryai_sim.safety import Context, eligible_actions, select_action


@given(st.text(max_size=30), st.booleans(), st.floats(min_value=0, max_value=.999999, allow_nan=False))
def test_arbitrary_decline_is_conservative(decline, consent, u):
    legal = eligible_actions(Context(decline=decline, consent=consent))
    action, propensity = select_action("randomized", legal, u)
    assert action in legal and 0 < propensity <= 1
    if decline not in {"insufficient_funds", "issuer_not_available", "processing_error"}:
        assert "retry_day3" not in legal
