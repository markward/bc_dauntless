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
    # Pin the four bucket sizes (not just their sum) to catch regressions
    # in WC_/KY_ memoization or classification logic.
    assert len(ok) == 350, f"ok bucket: expected 350, got {len(ok)}"
    assert len(wrong) == 584, f"wrong bucket: expected 584, got {len(wrong)}"
    assert len(missing) == 1232, f"missing bucket: expected 1232, got {len(missing)}"
    assert len(noclass) == 1663, f"noclass bucket: expected 1663, got {len(noclass)}"
    assert len(ok) + len(wrong) + len(missing) + len(noclass) == len(rows)


def test_ct_constants_are_the_only_structural_mismatches():
    """Every non-numeric 'wrong' entry is a CT_ class object, not a number."""
    _, _, wrong, _, _ = load()
    structural = [r for r, _, have in wrong if not isinstance(have, (int, float))]
    assert len(structural) == 37
    assert all(r["name"].startswith("CT_") for r in structural)


def test_load_is_order_independent():
    """Audit results must not depend on prior getattr calls.

    WC_/KY_ constants are memoized into vars(App) on first getattr access.
    This test verifies that load() forces memoization upfront, making results
    deterministic independent of what was already accessed.
    """
    import App
    import importlib

    # Helper to find bucket name for a constant by its name
    def find_bucket(constant_name, buckets):
        """Return which bucket (ok/wrong/missing/noclass) contains constant_name."""
        for i, bucket in enumerate(buckets):
            if any(row["name"] == constant_name for row, _, _ in bucket):
                return i  # 0=ok, 1=wrong, 2=missing, 3=noclass
        return -1  # not found

    # First load: baseline
    rows1, ok1, wrong1, missing1, noclass1 = load()
    buckets1 = (ok1, wrong1, missing1, noclass1)
    ky_a_bucket1 = find_bucket("KY_A", buckets1)

    # Reload App to clear memoization from the first load
    importlib.reload(App)

    # Access KY_A before loading, triggering memoization
    getattr(App, "KY_A", None)

    # Second load: must produce same bucket membership as first
    rows2, ok2, wrong2, missing2, noclass2 = load()
    buckets2 = (ok2, wrong2, missing2, noclass2)
    ky_a_bucket2 = find_bucket("KY_A", buckets2)

    # Both accesses must land in the same bucket
    bucket_names = ("ok", "wrong", "missing", "noclass")
    assert ky_a_bucket1 == ky_a_bucket2, (
        f"KY_A moved buckets: first={bucket_names[ky_a_bucket1]}, "
        f"second={bucket_names[ky_a_bucket2]}. "
        "This indicates load() results depend on prior access history."
    )
