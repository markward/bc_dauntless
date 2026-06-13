import App
from engine.appc.characters import (
    CharacterClass, CharacterClass_Create, CharacterClass_Cast, CharacterClass_GetObject,
    CharacterClass_SetVolumeForLineType, CharacterClass_GetVolumeForLineType,
    STButton, STMenu, STTopLevelMenu,
    STButton_CreateW, STTopLevelMenu_CreateW, STMenu_Cast, STTopLevelMenu_Cast,
)
from engine.appc.objects import ObjectClass
from engine.appc.sets import SetClass


# ── CharacterClass basics ────────────────────────────────────────────────────

def test_character_class_inherits_object_class():
    c = CharacterClass_Create("body.nif", "head.nif")
    assert isinstance(c, ObjectClass)


def test_character_class_factory_records_nif_paths():
    c = CharacterClass_Create("Bodies/X.nif", "Heads/Y.nif")
    assert c.GetBodyNIF() == "Bodies/X.nif"
    assert c.GetHeadNIF() == "Heads/Y.nif"


def test_character_class_create_null_returns_empty():
    c = App.CharacterClass_CreateNull()
    assert isinstance(c, CharacterClass)
    assert c.GetBodyNIF() == ""


def test_character_name_round_trip():
    c = CharacterClass_Create()
    c.SetCharacterName("Picard")
    assert c.GetCharacterName() == "Picard"


def test_yes_sir_round_trip():
    c = CharacterClass_Create()
    c.SetYesSir("YesCaptain01.wav")
    assert c.GetYesSir() == "YesCaptain01.wav"


def test_replace_body_and_head():
    c = CharacterClass_Create("a.nif", "b.nif")
    c.ReplaceBodyAndHead("c.nif", "d.nif")
    assert c.GetBodyNIF() == "c.nif"
    assert c.GetHeadNIF() == "d.nif"


def test_database_round_trip():
    c = CharacterClass_Create()
    db = object()
    c.SetDatabase(db)
    assert c.GetDatabase() is db


# ── Animation / facial / phoneme registration ────────────────────────────────

def test_add_facial_image_keyed_by_type():
    c = CharacterClass_Create()
    c.AddFacialImage(0, "Picard_neutral.tga")
    c.AddFacialImage(1, "Picard_angry.tga")
    assert c._facial_images[0] == "Picard_neutral.tga"
    assert c._facial_images[1] == "Picard_angry.tga"


def test_add_animation_appends():
    c = CharacterClass_Create()
    c.AddAnimation("walk", 1.0)
    c.AddAnimation("idle", 0.5)
    assert len(c._animations) == 2


def test_clear_animations():
    c = CharacterClass_Create()
    c.AddAnimation("walk", 1.0)
    c.ClearAnimations()
    assert c._animations == []


def test_clear_animations_of_type_filters():
    c = CharacterClass_Create()
    c.AddAnimation(CharacterClass.CAT_BREATHE, 1.0)
    c.AddAnimation(CharacterClass.CAT_TURN, 1.0)
    c.ClearAnimationsOfType(CharacterClass.CAT_BREATHE)
    assert len(c._animations) == 1
    assert c._animations[0][0] == CharacterClass.CAT_TURN


# ── State flags ──────────────────────────────────────────────────────────────

def test_set_status_and_is_state_set():
    c = CharacterClass_Create()
    assert c.IsStateSet(CharacterClass.CS_HIDDEN) == 0
    c.SetStatus(CharacterClass.CS_HIDDEN)
    assert c.IsStateSet(CharacterClass.CS_HIDDEN) == 1
    c.ClearStatus(CharacterClass.CS_HIDDEN)
    assert c.IsStateSet(CharacterClass.CS_HIDDEN) == 0


def test_set_hidden_flips_is_hidden():
    c = CharacterClass_Create()
    c.SetHidden()
    assert c.IsHidden() == 1


def test_set_standing_no_arg_flips_state():
    c = CharacterClass_Create()
    c.SetStanding()
    assert c.IsStanding() == 1


def test_set_standing_with_mode_records_mode():
    c = CharacterClass_Create()
    c.SetStanding(CharacterClass.SITTING_ONLY)
    assert c._data["StandingMode"] == CharacterClass.SITTING_ONLY


# ── Speaking / animating queries (Phase 1 quiet defaults) ────────────────────

def test_default_speaking_queries():
    c = CharacterClass_Create()
    assert c.IsSpeaking() == 0
    assert c.IsAnimating() == 0
    assert c.IsReadyToSpeak() == 1
    assert c.IsRandomAnimationEnabled() == 1
    assert c.IsMenuEnabled() == 1


# ── Menu wiring ──────────────────────────────────────────────────────────────

def test_get_menu_auto_vivifies():
    c = CharacterClass_Create()
    c.SetCharacterName("Tactical")
    menu = c.GetMenu()
    assert isinstance(menu, STTopLevelMenu)
    # Same instance on subsequent calls so handler registration sticks.
    assert c.GetMenu() is menu


def test_set_menu_replaces_default():
    c = CharacterClass_Create()
    custom = STTopLevelMenu("Custom")
    c.SetMenu(custom)
    assert c.GetMenu() is custom


def test_menu_get_submenu_w_auto_vivifies():
    """SDK pattern: pCharacter.GetMenu().GetSubmenuW("Helm") on a freshly-
    created menu returns a real submenu without explicit AddChild."""
    menu = STTopLevelMenu("Top")
    sub = menu.GetSubmenuW("Helm")
    assert isinstance(sub, STMenu)
    assert menu.GetSubmenuW("Helm") is sub


def test_menu_button_round_trip():
    menu = STMenu("Helm")
    btn = STButton_CreateW("Set Course", None, 0)
    menu.AddChild(btn)
    # After explicit AddChild, the same button comes back.
    assert menu.GetButtonW("Set Course") is btn
    # Strict lookup also finds it (no auto-vivification needed).
    assert menu.GetButtonWStrict("Set Course") is btn


def test_menu_kill_children_clears_everything():
    menu = STMenu("Top")
    menu.AddChild(STButton_CreateW("A"))
    menu.GetSubmenuW("Sub")  # vivify
    menu.KillChildren()
    # KillChildren wipes everything; lookups now auto-vivify fresh empty stubs.
    assert menu.GetButtonWStrict("A") is None
    # GetSubmenuW + GetButtonW vivified above don't survive KillChildren.
    assert "Sub" not in menu._submenus


def test_menu_get_button_w_auto_vivifies():
    """SDK callers (BridgeUtils.GetDockButton via MissionLib.CallWaiting)
    chain pMenu.GetButtonW("Dock").SetEnabled() without null-guarding —
    so GetButtonW must hand back a real STButton even on an empty menu."""
    menu = STMenu("Top")
    btn = menu.GetButtonW("Dock")
    assert isinstance(btn, STButton)
    assert btn.GetLabel() == "Dock"
    # Subsequent lookups return the same instance.
    assert menu.GetButtonW("Dock") is btn


def test_menu_get_button_w_strict_returns_none_when_missing():
    menu = STMenu("Top")
    assert menu.GetButtonWStrict("NotThere") is None


# ── STMenu / STTopLevelMenu casts ────────────────────────────────────────────

def test_st_menu_cast_passes_through_real_menu():
    menu = STMenu("X")
    assert STMenu_Cast(menu) is menu


def test_st_menu_cast_returns_none_for_none():
    assert STMenu_Cast(None) is None


def test_st_menu_cast_passes_through_duck_typed_stubs():
    """SDK pattern lets pButton flow through unchanged so its NamedStub
    __getattr__ absorbs the next .Close() call."""
    class DuckStub:
        def Close(self): pass
    stub = DuckStub()
    out = STMenu_Cast(stub)
    assert out is stub


def test_st_top_level_menu_cast_passes_through():
    top = STTopLevelMenu("Y")
    assert STTopLevelMenu_Cast(top) is top
    assert STTopLevelMenu_Cast(None) is None


# ── STButton ─────────────────────────────────────────────────────────────────

def test_st_button_enabled_round_trip():
    btn = STButton_CreateW("X")
    assert btn.IsEnabled() == 1
    btn.SetDisabled()
    assert btn.IsEnabled() == 0
    btn.SetEnabled()
    assert btn.IsEnabled() == 1


def test_st_button_send_activation_event_enqueues_event():
    from engine.appc.events import TGEvent
    evt = TGEvent()
    btn = STButton_CreateW("X", evt, 0)
    captured = []
    real = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda e: captured.append(e)
    try:
        btn.SendActivationEvent()
    finally:
        App.g_kEventManager.AddEvent = real
    assert captured == [evt]


# ── CharacterClass_GetObject + SetClass integration ──────────────────────────

def test_get_object_finds_character_in_set():
    """SDK pattern: pCharacter = App.CharacterClass_GetObject(pBridge, "Tactical")."""
    pSet = SetClass()
    pSet.SetName("bridge")
    tactical = CharacterClass_Create()
    pSet.AddObjectToSet(tactical, "Tactical")
    assert CharacterClass_GetObject(pSet, "Tactical") is tactical


def test_get_object_auto_vivifies_when_missing():
    """SDK callers chain pCharacter.GetMenu() / .ClearAnimations() without
    null-guarding; CharacterClass_GetObject must hand back a real character
    even when the set hasn't been populated (headless harness)."""
    pSet = SetClass()
    pSet.SetName("bridge")
    out = CharacterClass_GetObject(pSet, "Tactical")
    assert isinstance(out, CharacterClass)
    assert out.GetCharacterName() == "Tactical"
    # Subsequent calls return the same instance (now registered in the set).
    assert CharacterClass_GetObject(pSet, "Tactical") is out


def test_get_object_does_not_overwrite_non_character_in_set():
    """If something non-Character squats the name in the set, don't
    overwrite it — return a free-floating character instead."""
    pSet = SetClass()
    other = ObjectClass()
    pSet.AddObjectToSet(other, "JustAnObject")
    char = CharacterClass_GetObject(pSet, "JustAnObject")
    assert isinstance(char, CharacterClass)
    # The set still holds the original object — the character is free-floating.
    assert pSet.GetObject("JustAnObject") is other


def test_get_object_strict_returns_none_when_missing():
    from engine.appc.characters import CharacterClass_GetObjectStrict
    pSet = SetClass()
    assert CharacterClass_GetObjectStrict(pSet, "NotThere") is None


def test_get_object_with_none_set_returns_free_floating_character():
    """When pSet is None (BridgeSet_Cast on a missing bridge), we still hand
    back a real character — mission scripts assert it's non-None."""
    from engine.appc.characters import _free_characters
    _free_characters.clear()
    char = CharacterClass_GetObject(None, "TacticalNew")
    assert isinstance(char, CharacterClass)
    # Cached so repeat lookups return the same instance.
    assert CharacterClass_GetObject(None, "TacticalNew") is char


def test_set_status_accepts_string_label():
    """Bridge handlers call SetStatus("Waiting") / SetStatus("Ready to Advise")."""
    c = CharacterClass_Create()
    c.SetStatus("Waiting")
    assert c.IsStateSet("Waiting") == 1
    c.ClearStatus("Waiting")
    assert c.IsStateSet("Waiting") == 0


def test_set_status_int_and_string_independent():
    c = CharacterClass_Create()
    c.SetStatus(CharacterClass.CS_HIDDEN)
    c.SetStatus("Waiting")
    assert c.IsStateSet(CharacterClass.CS_HIDDEN) == 1
    assert c.IsStateSet("Waiting") == 1


def test_character_class_cast():
    plain = ObjectClass()
    char = CharacterClass_Create()
    assert CharacterClass_Cast(plain) is None
    assert CharacterClass_Cast(char) is char


# ── Module-level volume mixer ────────────────────────────────────────────────

def test_set_volume_for_line_type_round_trip():
    CharacterClass_SetVolumeForLineType(5, 0.75)
    assert CharacterClass_GetVolumeForLineType(5) == 0.75


def test_volume_default_is_one():
    assert CharacterClass_GetVolumeForLineType(99999) == 1.0


# ── Data-bag fallback ────────────────────────────────────────────────────────

def test_unknown_setter_round_trips_via_data_bag():
    c = CharacterClass_Create()
    c.SetGender(CharacterClass.MALE)
    c.SetSize(CharacterClass.MEDIUM)
    c.SetBlinkChance(0.05)
    assert c.GetGender() == CharacterClass.MALE
    assert c.GetSize() == CharacterClass.MEDIUM
    assert c.GetBlinkChance() == 0.05


def test_unknown_method_no_op():
    """Methods like ToolTip, MorphBody just absorb without raising."""
    c = CharacterClass_Create()
    c.ToolTip("hello")
    c.MorphBody(0.5)


# ── App namespace ────────────────────────────────────────────────────────────

def test_app_exposes_character_factories():
    assert App.CharacterClass_Create is CharacterClass_Create
    assert App.CharacterClass_GetObject is CharacterClass_GetObject
    assert App.CharacterClass_Cast is CharacterClass_Cast


def test_app_exposes_character_constants():
    assert App.CharacterClass.MALE == 0
    assert App.CharacterClass.FEMALE == 1
    assert App.CharacterClass.CS_HIDDEN == 5
    assert App.CharacterClass.CAT_BREATHE == 1


def test_app_exposes_menu_classes():
    assert App.STMenu is STMenu
    assert App.STTopLevelMenu is STTopLevelMenu
    assert App.STButton_CreateW is STButton_CreateW


def test_speakline_routes_text_and_speaker_to_subtitle():
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase
    from engine.appc.ai import CSP_NORMAL

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("Tactical")
    db = TGLocalizationDatabase("x.tgl", strings={"L1": "Shields holding"})

    char.SpeakLine(db, "L1", CSP_NORMAL)

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    snap = sub._snapshot(now=0.0)
    assert snap["speaker"] == "Tactical"
    assert snap["speech"] == "Shields holding"


def test_speakline_without_string_shows_no_subtitle():
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("Eng")
    db = TGLocalizationDatabase("x.tgl")  # no strings -> HasString False

    char.SpeakLine(db, "ge119")  # 2-arg form, default priority

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    assert sub._snapshot(now=0.0) is None  # nothing displayed


def test_sayline_4arg_sdk_form_sets_no_subtitle_and_does_not_raise():
    # Real SDK call shape: SayLine(db, lineID, addressee, priority) — e.g.
    # g_pMiguel.SayLine(pMissionDatabase, "E7M1EnterpriseDestroyed", "Captain", 1).
    # The "Captain" addressee must NOT be coerced into the priority slot
    # (int("Captain") would raise). Voice-only: no subtitle.
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("Miguel")
    db = TGLocalizationDatabase("x.tgl", strings={"ack": "Aye sir"})

    char.SayLine(db, "ack", "Captain", 1)  # must not raise

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    assert sub._snapshot(now=0.0) is None


def test_sayline_2arg_form_sets_no_subtitle():
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("XO")
    db = TGLocalizationDatabase("x.tgl", strings={"ack": "Aye sir"})

    char.SayLine(db, "ack")  # voice-only -- must NOT set a subtitle slot

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    assert sub._snapshot(now=0.0) is None


def test_sayline_5arg_form_extracts_explicit_priority():
    # Dominant SDK form (59 call sites): the real priority is the OPTIONAL 5th
    # arg, e.g. SayLine(pDatabase, "Shields05", "Captain", 1, App.CSP_SPONTANEOUS).
    # arg4 (1) is a flag and must NOT be read as the priority.
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.localization import TGLocalizationDatabase
    from engine.appc.ai import CSP_SPONTANEOUS

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("Engineering")
    # SayLine is voice-only, so the line needs a registered wav or the bus
    # drops it as "nothing to say" before recording a priority.
    db = TGLocalizationDatabase(
        "x.tgl", strings={"Shields05": "Shields at 5%"},
        sounds={"Shields05": "shields05.wav"})

    char.SayLine(db, "Shields05", "Captain", 1, CSP_SPONTANEOUS)  # must not raise

    # The explicit arg5 priority reached the bus (not the arg4 flag value 1).
    assert crew_speech.bus()._active_priority == CSP_SPONTANEOUS


def test_speakline_with_stub_database_shows_no_subtitle():
    # GetEpisode().GetDatabase() resolves to a _NamedStub when no episode is
    # live; its HasString/GetString/GetFilename return truthy stubs that must
    # never be rendered as subtitle text.
    import App
    from engine.appc import top_window, crew_speech
    from engine.appc.characters import CharacterClass
    from engine.appc.ai import CSP_NORMAL

    top_window.reset_for_tests()
    crew_speech.bus().reset()

    char = CharacterClass()
    char.SetCharacterName("Felix")
    stub_db = App.NoSuchManager.GetDatabase()  # a _NamedStub chain

    char.SpeakLine(stub_db, "E6M1Line", CSP_NORMAL)

    sub = App.TopWindow_GetTopWindow().FindMainWindow(App.MWT_SUBTITLE)
    assert sub._snapshot(now=0.0) is None
