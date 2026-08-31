"""Task 8 definition-site guards.

Per ruling PT6-2 (carried from Task 7's KBT_/GET_ finding): a value-regression
guard for a class-scope constant must read the class's actual definition
site, not `App.<Class>.<CONST>` -- when that class is a real implementation
imported into App.py BY REFERENCE (shared identity), `App.py`'s
`CORRECT_EXISTING` deliberately excludes these names (see App.py's comment
block), so there is no self-heal to hide behind: these tests are the ONLY
thing that would catch a future regression in the class body's own literal.

Every value asserted here is cross-checked against the measured table
(`engine.appc.constants_generated.CLASS_CONSTANTS`) rather than a
hand-copied literal, so a future re-generation of that table cannot silently
drift out of step with this file.
"""
from engine.appc.constants_generated import CLASS_CONSTANTS


def test_tg_paragraph_flags_are_the_measured_bit_positions():
    from engine.appc.tg_ui.widgets import TGParagraph
    measured = CLASS_CONSTANTS["TGParagraph"]
    for name in ("TGPF_READ_ONLY", "TGPF_INSERT_MODE", "TGPF_WORD_WRAP",
                 "TGPF_RECALC_BOUNDS", "TGPF_FLAGS_MASK"):
        assert getattr(TGParagraph, name) == measured[name], name


def test_tg_frame_no_stretch_lr_is_the_measured_value():
    from engine.appc.tg_ui.widgets import TGFrame
    assert TGFrame.NO_STRETCH_LR == CLASS_CONSTANTS["TGFrame"]["NO_STRETCH_LR"]


def test_tg_sound_loadspec_constants_are_the_measured_values():
    from engine.audio.tg_sound import TGSound
    measured = CLASS_CONSTANTS["TGSound"]
    for name in ("LS_3D", "LS_STREAMED", "LS_DELAY_LOADING"):
        assert getattr(TGSound, name) == measured[name], name


def test_effect_controller_levels_are_the_measured_values_and_ordered():
    from engine.appc.particles import EffectController
    measured = CLASS_CONSTANTS["EffectController"]
    for name in ("LOW", "MEDIUM", "HIGH"):
        assert getattr(EffectController, name) == measured[name], name
    # EffectController_GetEffectLevel always returns HIGH and
    # hull_hit_smoke.maybe_emit gates on `level < MEDIUM` -- ordering must
    # survive the correction (it does: 1 < 2 < 3, same as the old 0 < 1 < 2).
    assert EffectController.LOW < EffectController.MEDIUM < EffectController.HIGH


def test_model_property_manager_scopes_are_the_measured_values():
    from engine.appc.properties import TGModelPropertyManager
    measured = CLASS_CONSTANTS["TGModelPropertyManager"]
    assert TGModelPropertyManager.LOCAL_TEMPLATES == measured["LOCAL_TEMPLATES"]
    assert TGModelPropertyManager.GLOBAL_TEMPLATES == measured["GLOBAL_TEMPLATES"]


def test_float_range_watcher_directions_are_the_measured_values():
    from engine.appc.float_range_watcher import FloatRangeWatcher
    measured = CLASS_CONSTANTS["FloatRangeWatcher"]
    for name in ("FRW_BELOW", "FRW_ABOVE", "FRW_BOTH"):
        assert getattr(FloatRangeWatcher, name) == measured[name], name


def test_object_group_flags_are_the_measured_values_and_inherited():
    from engine.appc.objects import ObjectGroup, ObjectGroupWithInfo
    measured = CLASS_CONSTANTS["ObjectGroup"]
    for name in ("GROUP_CHANGED", "ENTERED_SET", "EXITED_SET", "DESTROYED"):
        assert getattr(ObjectGroup, name) == measured[name], name
        # ObjectGroupWithInfo defines none of these itself -- it inherits
        # ObjectGroup's, so fixing ObjectGroup alone also fixes both of
        # Task 8's "ObjectGroup"/"ObjectGroupWithInfo" families.
        assert name not in vars(ObjectGroupWithInfo)
        assert getattr(ObjectGroupWithInfo, name) == measured[name], name


def test_tguiobject_align_bc_measured_anchors_come_from_layout_py():
    """The real definition site for TGUIObject.ALIGN_UR/BL/BR/UL is
    engine.appc.tg_ui.layout's own module constants, NOT a CORRECT_EXISTING
    entry (see App.py's comment for the ANCHOR_FRACTIONS collision this
    would otherwise cause)."""
    from engine.appc.tg_ui import layout
    measured = CLASS_CONSTANTS["TGUIObject"]
    assert layout.ALIGN_UL == measured["ALIGN_UL"] == 0
    assert layout.ALIGN_UR == measured["ALIGN_UR"] == 1
    assert layout.ALIGN_BL == measured["ALIGN_BL"] == 2
    assert layout.ALIGN_BR == measured["ALIGN_BR"] == 3
    # The five Dauntless-only compass points must stay distinct from BC's
    # four AND from each other, or ANCHOR_FRACTIONS silently aliases two
    # anchors together.
    all_anchors = [layout.ALIGN_UL, layout.ALIGN_UC, layout.ALIGN_UR,
                   layout.ALIGN_CL, layout.ALIGN_CC, layout.ALIGN_CR,
                   layout.ALIGN_BL, layout.ALIGN_BC, layout.ALIGN_BR]
    assert len(set(all_anchors)) == len(all_anchors)


def test_app_tguiobject_align_matches_layout_by_construction():
    """App.TGUIObject.ALIGN_X = engine.appc.tg_ui.layout.ALIGN_X (a plain int
    copy at class-body-execution time) -- there is no CORRECT_EXISTING entry
    for TGUIObject.ALIGN_*, so this equality is the ONLY thing that keeps
    App's copy in step with layout.py after a future edit there."""
    import App
    from engine.appc.tg_ui import layout
    for name in ("ALIGN_UL", "ALIGN_UC", "ALIGN_UR", "ALIGN_CL", "ALIGN_CC",
                 "ALIGN_CR", "ALIGN_BL", "ALIGN_BC", "ALIGN_BR"):
        assert getattr(App.TGUIObject, name) == getattr(layout, name), name
