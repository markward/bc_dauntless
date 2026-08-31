from tools.constant_surface_audit import load, real_attr


def test_real_attr_ignores_getattr_stubs():
    """A _NamedStub vended by __getattr__ must not count as 'defined'."""
    import App
    # App has no such name; module __getattr__ vends a _NamedStub for it.
    assert getattr(App, "ZZ_NOT_A_REAL_CONSTANT") is not None
    assert real_attr(App, "ZZ_NOT_A_REAL_CONSTANT") == (False, None)


def test_load_partitions_every_usable_row():
    rows, ok, wrong, missing, noclass = load()
    assert len(rows) == 3829, "usable rows excl. __name__/__file__"
    assert len(ok) + len(wrong) + len(missing) + len(noclass) == len(rows)


def test_ct_constants_are_the_only_structural_mismatches():
    """Every non-numeric 'wrong' entry is a CT_ class object, not a number."""
    _, _, wrong, _, _ = load()
    structural = [r for r, _, have in wrong if not isinstance(have, (int, float))]
    assert len(structural) == 37
    assert all(r["name"].startswith("CT_") for r in structural)
