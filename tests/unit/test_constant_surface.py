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
#
# Task 7 corrected the 347 keyboard-family constants (WC_ 234, KY_ 104,
# KBT_ 4, KS_ 3, GET_ 2), separating BC's WC_ (character codes) and KY_ (a
# small, unrelated key-index enum) -- previously conflated as aliases of the
# same invented Windows-VK value -- and restoring KBT_'s bitmask (1/2/4/8,
# not sequential 0-3).
#
# Task 8 corrected the 47 UI-class-constant values across thirteen families
# (WeaponsDisplay 20, TGParagraph 5, TGUIObject.ALIGN_* 3, TGSound 3,
# EffectController 3, TGModelPropertyManager 2, FloatRangeWatcher 2,
# ObjectGroup 2, ObjectGroupWithInfo 2, EngRepairPane.DIVIDER 1, TGFrame 1,
# STBSF_SIZE_TO_TEXT 1, SPECIES_GALAXY/SPECIES_SOVEREIGN 2). See App.py's
# CORRECT_EXISTING comment block for which of those thirteen families are
# corrected there versus fixed directly at an engine/ definition site (the
# TGUIObject.ALIGN_* / ANCHOR_FRACTIONS coupling in particular).
REMAINING_WRONG = 41

# Task 7 also defined the 105 genuinely-missing keyboard names (101 WC_ +
# 4 KY_ international/accented codepoints our table never covered), driving
# this to its floor of 0.
REMAINING_MISSING = 0


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


def test_event_types_are_the_measured_values():
    """Task 5: the 148 ET_* names we already defined now carry BC's real
    values instead of our invented ones."""
    import App
    assert App.ET_AI_TIMER == 0x800020
    assert App.ET_OBJECT_DESTROYED == 0x80004F
    assert App.ET_SET_TARGET == 0x8000E1
    assert App.ET_TACTICAL_SHIELD_0_LEVEL_CHANGE == 0x800041


def test_no_two_event_types_collide_except_the_known_aliases():
    """ET_CLOAKED_COLLISION == ET_POWER_FRACTION_CHANGED == 1075 was a live
    bug in our invented numbering: two unrelated events sharing a handler
    chain. Task 5 corrects ET_CLOAKED_COLLISION to its real measured value,
    which resolves that collision. Four pairs legitimately remain:

      0x800037 -- ET_CANT_FIRE / ET_WEAPON_FIRE_FAILED: OUR deliberate alias
                  (the dump shows BC has no distinct "fire failed" event --
                  0x800037 IS ET_CANT_FIRE).
      0x80110D -- ET_FIRST_APP_SCRIPT_EVENT / ET_FIRST_SCRIPT_EVENT: BC's OWN
                  range marker, two names for one boundary value.
      0x80010C -- ET_FIRST_INPUT_EVENT / ET_INPUT_TOGGLE_MAP_MODE: likewise
                  BC's own range marker doubling as the first input event.
      0x800067 -- ET_PLAYER_TORPEDO_COUNT_CHANGED / ET_TORPEDO_AMMO_CONSUMED:
                  pre-existing, NOT touched by Task 5. ET_TORPEDO_AMMO_CONSUMED
                  is Dauntless's own name (RE'd from the binary by probe q12,
                  engine/appc/events.py) for the exact same event the later
                  q13 dump independently measured and named
                  ET_PLAYER_TORPEDO_COUNT_CHANGED (additively injected by
                  Task 3, since App never defined that name itself). Same
                  shape as the ET_CANT_FIRE alias above -- one real BC event,
                  two names, neither invented -- but outside this task's
                  scope (the 148 corrections are all names that were WRONG;
                  this pair was already present and already agreeing on the
                  value before Task 5 touched anything).
    """
    import App
    by_value = {}
    for name in dir(App):
        if name.startswith("ET_") and isinstance(getattr(App, name), int):
            by_value.setdefault(getattr(App, name), set()).add(name)
    dupes = {v: n for v, n in by_value.items() if len(n) > 1}
    assert dupes == {
        0x800037: {"ET_CANT_FIRE", "ET_WEAPON_FIRE_FAILED"},
        0x80110D: {"ET_FIRST_APP_SCRIPT_EVENT", "ET_FIRST_SCRIPT_EVENT"},
        0x80010C: {"ET_FIRST_INPUT_EVENT", "ET_INPUT_TOGGLE_MAP_MODE"},
        0x800067: {"ET_PLAYER_TORPEDO_COUNT_CHANGED", "ET_TORPEDO_AMMO_CONSUMED"},
    }


def test_ui_class_constants_are_the_measured_values():
    """Task 8: WeaponsDisplay/EngRepairPane/STBSF_SIZE_TO_TEXT/SPECIES_* are
    corrected via App.py's CORRECT_EXISTING (they have no engine/ definition
    site of their own); TGUIObject.ALIGN_* is corrected at its real numeric
    source, engine/appc/tg_ui/layout.py (see App.py's CORRECT_EXISTING
    comment for why -- ALIGN_* is NOT itself in CORRECT_EXISTING)."""
    import App
    assert App.TGUIObject.ALIGN_UR == 1 and App.TGUIObject.ALIGN_BL == 2
    assert App.EngRepairPane.DIVIDER == 6
    assert App.STBSF_SIZE_TO_TEXT == 0x40000000, "a flag bit, not 1"
    assert App.SPECIES_GALAXY == 101 and App.SPECIES_SOVEREIGN == 102


def test_weapons_display_keeps_bcs_intentional_duplicates():
    """BC shares one class namespace between a border enum and a pane enum;
    the repeated indices are real and must not be 'fixed'."""
    import App
    wd = App.WeaponsDisplay
    assert wd.TORPEDO_PANE == wd.TOP_RIGHT_BORDER == 0
    assert wd.GLASS == wd.LOWER_DISRUPTOR_INDICATOR_PANE == 8


def test_species_constants_agree_with_the_icon_table_and_hardpoints():
    """The whole point of correcting SPECIES_GALAXY/SPECIES_SOVEREIGN: before
    this task App.SPECIES_GALAXY==0 and App.SPECIES_SOVEREIGN==2 silently
    disagreed with both engine.ui.species_icons's stem table (keyed by BC's
    real hardpoint SetSpecies() integers) and every symbolic SDK comparison
    against them (e.g. MissionLib.py's `kSpecies == App.SPECIES_GALAXY`,
    TacticalCharacterHandlers.py's `pShipProp.GetSpecies() == App.SPECIES_GALAXY`)
    -- both always False, since a real ship's GetSpecies() returns 101/102,
    never 0/2."""
    import App
    from engine.ui.species_icons import _SPECIES_TO_STEM
    assert _SPECIES_TO_STEM[App.SPECIES_GALAXY] == "Galaxy"
    assert _SPECIES_TO_STEM[App.SPECIES_SOVEREIGN] == "Sovereign"
