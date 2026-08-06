import pytest

from src.toptraders.copytrader import (
    size_for,
    load_copy_state,
    save_copy_state,
    DEFAULT_STATE,
)


@pytest.mark.parametrize(
    "wr,expected",
    [
        (0.50, 0.0),
        (0.75, 2500.0),
        (1.00, 5000.0),
        (0.40, 0.0),  # clamped
    ],
)
def test_size_for(wr, expected):
    assert size_for(wr) == expected


def test_copy_state_roundtrip(tmp_path, monkeypatch):
    import copy

    from src.toptraders import copytrader

    monkeypatch.setattr(copytrader, "COPY_STATE_FILE", tmp_path / "copy.json")
    state = copy.deepcopy(DEFAULT_STATE)
    state["positions"] = {"NVDA": {"status": "open"}}
    save_copy_state(state)
    assert load_copy_state()["positions"]["NVDA"]["status"] == "open"
