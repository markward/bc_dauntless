"""Viseme-table loader + basis-weight model.

The table maps each BC .LIP phoneme code to weights over the texture basis
{neutral, a, e, u}. Coverage of all 35 corpus codes is an invariant; the
placeholder weight values are refined later by the RE tooling.
"""
import json

import pytest

from engine.appc.lip_visemes import (
    BASIS,
    load_viseme_table,
    viseme_weights,
    dominant_pair,
)

# Every distinct code that appears across the 593 game .LIP files.
KNOWN_CODES = [
    0, 1, 29, 31, 32, 33, 35, 36, 37, 38, 39, 40, 41, 42, 43, 46, 47, 48, 49,
    50, 53, 54, 56, 59, 64, 65, 66, 81, 96, 106, 113, 115, 121, 139, 142,
]


def test_basis_is_neutral_a_e_u():
    assert BASIS == ("neutral", "a", "e", "u")


def test_shipped_table_covers_all_known_codes():
    table = load_viseme_table()
    for code in KNOWN_CODES:
        assert code in table, f"code {code} missing from shipped viseme table"
    assert all(isinstance(k, int) for k in table)


def test_code_zero_is_neutral():
    table = load_viseme_table()
    w = viseme_weights(table, 0)
    assert w["neutral"] == pytest.approx(1.0)
    assert sum(w.values()) == pytest.approx(1.0)


def test_weights_are_normalized_and_nonnegative():
    table = load_viseme_table()
    for code in KNOWN_CODES:
        w = viseme_weights(table, code)
        assert sum(w.values()) == pytest.approx(1.0)
        assert all(v >= 0.0 for v in w.values())


def test_unknown_code_falls_back_to_neutral():
    table = load_viseme_table()
    assert viseme_weights(table, 9999) == {"neutral": 1.0}


def test_custom_path_round_trips(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"5": {"a": 2.0, "e": 2.0}}))  # unnormalized on purpose
    table = load_viseme_table(f)
    w = viseme_weights(table, 5)
    assert w["a"] == pytest.approx(0.5)
    assert w["e"] == pytest.approx(0.5)


def test_dominant_pair_picks_two_strongest_with_mix():
    # neutral 0.2, a 0.5, e 0.3 -> dominant a, second e, mix = e/(a+e).
    tex_a, tex_b, mix = dominant_pair({"neutral": 0.2, "a": 0.5, "e": 0.3})
    assert tex_a == "a"
    assert tex_b == "e"
    assert mix == pytest.approx(0.3 / 0.8)


def test_dominant_pair_single_weight_is_pure():
    tex_a, tex_b, mix = dominant_pair({"a": 1.0})
    assert tex_a == "a"
    assert mix == pytest.approx(0.0)  # fully tex_a
