"""TGMatrix3 uses flat slotted storage, not a list-of-lists.

The list-of-lists form cost ~6 allocations per instance (object + __dict__ +
outer list + three rows). ObjectClass.GetWorldRotation builds one on every
call at 70 call sites, per object, per frame.
"""
import pytest

from engine.appc.math import TGMatrix3, TGPoint3


def test_has_slots_and_no_dict():
    m = TGMatrix3()
    assert not hasattr(m, "__dict__"), "TGMatrix3 must not carry a __dict__"
    assert TGMatrix3.__slots__ == (
        "m00", "m01", "m02", "m10", "m11", "m12", "m20", "m21", "m22")


def test_underscore_m_is_gone():
    m = TGMatrix3()
    assert not hasattr(m, "_m"), (
        "_m must not survive as a compatibility shim: it would rebuild a "
        "list-of-lists and silently reintroduce the allocation, in the "
        "places we can no longer see")


def test_default_is_identity_by_attribute():
    m = TGMatrix3()
    assert (m.m00, m.m01, m.m02) == (1.0, 0.0, 0.0)
    assert (m.m10, m.m11, m.m12) == (0.0, 1.0, 0.0)
    assert (m.m20, m.m21, m.m22) == (0.0, 0.0, 1.0)


def test_as_tuple_is_row_major():
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    assert m.as_tuple() == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)


def test_set_from_tuple_round_trips():
    src = (0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
    m = TGMatrix3()
    m.set_from_tuple(src)
    assert m.as_tuple() == src


def test_get_entry_matches_attributes():
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    expected = [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [7.0, 8.0, 9.0]]
    for i in range(3):
        for j in range(3):
            assert m.GetEntry(i, j) == expected[i][j]


def test_get_col_reads_columns_not_rows():
    """Column-vector convention: GetCol(1) is forward. Regression guard for
    the row/column split unified on 2026-06-18."""
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    col1 = m.GetCol(1)
    assert (col1.x, col1.y, col1.z) == (2.0, 5.0, 8.0)


def test_set_col_writes_columns():
    m = TGMatrix3()
    m.MakeZero()
    m.SetCol(2, TGPoint3(7.0, 8.0, 9.0))
    assert (m.m02, m.m12, m.m22) == (7.0, 8.0, 9.0)


def test_set_row_writes_rows():
    m = TGMatrix3()
    m.MakeZero()
    m.SetRow(1, TGPoint3(4.0, 5.0, 6.0))
    assert (m.m10, m.m11, m.m12) == (4.0, 5.0, 6.0)


def test_transpose_swaps_indices():
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    t = m.Transpose()
    assert t.as_tuple() == (1.0, 4.0, 7.0, 2.0, 5.0, 8.0, 3.0, 6.0, 9.0)


def test_transpose_does_not_mutate_source():
    m = TGMatrix3()
    m.Set(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
    m.Transpose()
    assert m.as_tuple() == (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0)
