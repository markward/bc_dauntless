"""The constant surface must match the game, and only shrink away from it.

Two ratchets, both lower-only.  When a task lands a family, lower the relevant
counter by exactly that family's size.  A test failing because a number is too
HIGH means someone re-invented a value or re-stubbed a name.

The floor for REMAINING_WRONG is NOT zero: the PI-family DEVIATIONS are defined
by us at double precision and differ from BC's float32 permanently by design.
The terminal assertion is therefore "everything still wrong is a declared
deviation", which is self-describing and cannot be satisfied by miscounting.
"""
from engine.appc.constants_apply import DEVIATIONS
from tools.constant_surface_audit import load

# Lower me. Never raise me.
#   585 at Task 4 -> 437 (T5 ET_ 148) -> 435 (T6 CSP_ 2)
#       -> 88 (T7 keyboard 347) -> 41 (T8 UI 47) -> 4 (T9 CT_ 37)
# 4 is the floor: the four PI-family deviations.
REMAINING_WRONG = 585

# Keyboard names deferred to Task 7, which drives this to 0.
REMAINING_MISSING = 105


def test_missing_constants_only_ever_shrink():
    """An undefined App constant silently degrades to a truthy _NamedStub or
    int()==0 -- the bug class this whole sweep exists to eliminate."""
    _, _, _, missing, _ = load()
    named = sorted(r["qualified_name"] for r, _, _ in missing)
    assert len(missing) == REMAINING_MISSING, (
        "%d measured constants undefined, ratchet says %d -- if lower, set "
        "REMAINING_MISSING to %d\n%s"
        % (len(missing), REMAINING_MISSING, len(missing), "\n".join(named)))


def test_every_measured_class_exists():
    _, _, _, _, noclass = load()
    assert noclass == [], "%d constants have no owner class" % len(noclass)


def test_wrong_values_only_ever_shrink():
    _, _, wrong, _, _ = load()
    named = sorted(r["qualified_name"] for r, _, _ in wrong)
    assert len(wrong) == REMAINING_WRONG, (
        "%d wrong values remain but the ratchet says %d -- if lower, set "
        "REMAINING_WRONG to %d\n%s"
        % (len(wrong), REMAINING_WRONG, len(wrong), "\n".join(named)))


def test_the_only_permanent_deviations_are_declared_ones():
    """The terminal invariant.  Once every correction task has landed, the ONLY
    constants still differing from the measured game must be ones we declared
    in DEVIATIONS on purpose.  Skipped until the ratchet bottoms out."""
    import pytest
    if REMAINING_WRONG > len(DEVIATIONS):
        pytest.skip("correction tasks still outstanding (%d wrong, %d declared)"
                    % (REMAINING_WRONG, len(DEVIATIONS)))
    _, _, wrong, _, _ = load()
    undeclared = sorted(r["qualified_name"] for r, _, _ in wrong
                        if r["name"] not in DEVIATIONS)
    assert undeclared == [], (
        "these differ from the game but are not declared deviations:\n%s"
        % "\n".join(undeclared))


def test_every_deviation_is_justified():
    for name, reason in DEVIATIONS.items():
        assert len(reason) > 40, "%s needs a real reason, not '%s'" % (name, reason)


def test_every_deviation_is_actually_defined():
    """A DEVIATIONS entry suppresses injection.  Naming a constant we do not
    define therefore CREATES the stub it was meant to avoid -- which is exactly
    what FOURTH_PI did before Task 3's fix round."""
    import App
    from tools.constant_surface_audit import real_attr
    for name in DEVIATIONS:
        owner, _, attr = name.rpartition(".")
        target = getattr(App, owner) if owner else App
        defined, _ = real_attr(target, attr)
        assert defined, (
            "%s is declared a deviation but is not defined -- it is a stub"
            % name)
