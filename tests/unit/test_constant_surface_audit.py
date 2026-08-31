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
    #
    # These were 350/584/1232/1663 before engine.appc.constants_apply started
    # injecting the measured table into App.py (q13 sweep Task 3). `wrong`
    # (584) is unchanged by design -- Task 3 is additive-only and, per ruling,
    # deliberately does NOT inject WC_*/KY_* module names so App.py's existing
    # __getattr__ memoization path (engine.appc.input) keeps resolving them;
    # those 313 names (already "wrong" against this dump before Task 3) stay
    # "wrong" after it. `ok` rose and `missing`/`noclass` fell because
    # everything else that was absent is now really defined.
    #
    # `wrong` is 585, not 584: fix-round-1 defined FOURTH_PI in App.py
    # (alongside PI/HALF_PI/TWO_PI, its DEVIATIONS siblings) at double
    # precision, deliberately differing from BC's float32-rounded measured
    # value -- so it moved from `missing` straight to `wrong`, exactly like
    # its three siblings did before this task ever ran. That is additive
    # (a name that didn't exist now does, and legitimately still disagrees
    # with the dump on purpose), not a correction of a pre-existing value.
    #
    # The 105 that remain `missing` are all WC_* codepoints (e.g.
    # WC_POUND_SIGN) that engine.appc.input's table itself does not define
    # -- a WC_/KY_-family fix, out of scope for Task 3.
    #
    # Task 5 corrected the 148 ET_* event-type constants (moved `wrong` ->
    # `ok`; nothing else changes), so as of Task 5: ok 3139 -> 3287,
    # wrong 585 -> 437. missing/noclass are untouched -- ET_ names were all
    # already defined (just wrong), never missing.
    #
    # Task 6 corrected the 2 CSP_* constants (CSP_MISSION_CRITICAL,
    # CSP_SPONTANEOUS -- moved `wrong` -> `ok`): ok 3287 -> 3289,
    # wrong 437 -> 435.
    assert len(ok) == 3289, f"ok bucket: expected 3289, got {len(ok)}"
    assert len(wrong) == 435, f"wrong bucket: expected 435, got {len(wrong)}"
    assert len(missing) == 105, f"missing bucket: expected 105, got {len(missing)}"
    assert len(noclass) == 0, f"noclass bucket: expected 0, got {len(noclass)}"
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

    # Helper to find bucket index for a constant by its name
    def find_bucket(constant_name, buckets):
        """Return which bucket (0=ok, 1=wrong, 2=missing, 3=noclass) contains constant_name."""
        for i, bucket in enumerate(buckets):
            if any(row["name"] == constant_name for row, _, _ in bucket):
                return i
        return -1  # not found

    # Save and remove the memoized entry if it exists, to simulate unmemoized state
    saved_memoized = vars(App).pop("KY_A", None)

    try:
        # First load: KY_A is NOT memoized yet, but load() forces resolution
        rows1, ok1, wrong1, missing1, noclass1 = load()
        buckets1 = (ok1, wrong1, missing1, noclass1)
        ky_a_bucket1 = find_bucket("KY_A", buckets1)

        # Now KY_A has been memoized by load()'s pre-resolution loop
        assert "KY_A" in vars(App), "load() should have memoized KY_A"

        # Access KY_A explicitly (redundant since load() already memoized, but makes
        # the test's intent clear: we're testing that prior touches don't break things)
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
    finally:
        # Restore vars(App) to its pre-test state
        if saved_memoized is not None:
            vars(App)["KY_A"] = saved_memoized
        else:
            # If it wasn't there before, remove it again (clean up memoization from the test)
            vars(App).pop("KY_A", None)
