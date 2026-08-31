from engine.appc.constants_generated import MODULE_CONSTANTS, CLASS_CONSTANTS


def test_counts_match_the_measured_dump():
    assert len(MODULE_CONSTANTS) == 1317
    assert sum(len(v) for v in CLASS_CONSTANTS.values()) == 2512
    # 314 distinct owner classes carry constants.  (The q13 header's "classes =
    # 630" counts every class in dir(App), most of which carry none.)
    assert len(CLASS_CONSTANTS) == 314


def test_module_internals_are_excluded():
    assert "__name__" not in MODULE_CONSTANTS
    assert "__file__" not in MODULE_CONSTANTS


def test_spot_values_are_the_measured_ones():
    assert MODULE_CONSTANTS["ET_CANT_FIRE"] == 0x800037
    assert MODULE_CONSTANTS["ET_SET_WARP_SEQUENCE"] == 0x8000EE
    assert MODULE_CONSTANTS["CSP_MISSION_CRITICAL"] == 0
    assert MODULE_CONSTANTS["STBSF_SIZE_TO_TEXT"] == 0x40000000
    assert CLASS_CONSTANTS["TGUIObject"]["ALIGN_UR"] == 1
    assert CLASS_CONSTANTS["KeyboardBinding"]["KBT_LOCKOUT_CHANGE"] == 8


def test_weapons_display_duplicates_are_preserved():
    """BC shares one class namespace between a border enum and a pane enum."""
    wd = CLASS_CONSTANTS["WeaponsDisplay"]
    assert wd["TORPEDO_PANE"] == wd["TOP_RIGHT_BORDER"] == 0
    assert wd["GLASS"] == wd["LOWER_DISRUPTOR_INDICATOR_PANE"] == 8


def test_generator_output_is_byte_identical_to_the_checked_in_file():
    """Guards against hand-editing the generated module."""
    import pathlib
    from tools.gen_app_constants import render
    path = (pathlib.Path(__file__).resolve().parents[2]
            / "engine/appc/constants_generated.py")
    assert path.read_text() == render()
