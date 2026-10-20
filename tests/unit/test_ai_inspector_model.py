"""Tests for the AI-tree introspection helpers used by AIInspectorPanel.

serialize_ai_tree turns a live AI subtree into a JSON-able nested dict;
collect_all_ship_ai walks every ship via ship_iter and pairs each ship
name with its serialized tree (or None when the ship has no AI).
"""
import pytest

import App
from engine.appc.sets import SetClass
from engine.appc.ships import ShipClass_Create
from engine.appc import ai as ai_mod
from engine.ui.ai_inspector_model import serialize_ai_tree, collect_all_ship_ai


# ---- serialize_ai_tree ----------------------------------------------------

def test_serialize_plain_ai_leaf():
    leaf = ai_mod.PlainAI_Create(None, "ChaseEnemy")
    leaf.SetScriptModule("FollowObject")
    leaf._next_update_time = 12.5
    d = serialize_ai_tree(leaf)
    assert d["name"] == "ChaseEnemy"
    assert d["type"] == "PlainAI"
    assert d["status"] == "ACTIVE"
    assert d["focus"] is False
    assert d["script_module"] == "FollowObject"
    assert d["next_update_time"] == 12.5


def test_serialize_status_mapping():
    leaf = ai_mod.PlainAI_Create(None, "L")
    leaf._status = ai_mod.ArtificialIntelligence.US_DONE
    assert serialize_ai_tree(leaf)["status"] == "DONE"
    leaf._status = ai_mod.ArtificialIntelligence.US_DORMANT
    assert serialize_ai_tree(leaf)["status"] == "DORMANT"
    leaf._status = ai_mod.ArtificialIntelligence.US_INVALID
    assert serialize_ai_tree(leaf)["status"] == "INVALID"


def test_serialize_focus_true():
    leaf = ai_mod.PlainAI_Create(None, "L")
    leaf._has_focus = True
    assert serialize_ai_tree(leaf)["focus"] is True


def test_serialize_sequence_with_children():
    seq = ai_mod.SequenceAI_Create(None, "Seq")
    plain = ai_mod.PlainAI_Create(None, "Step1")
    plain.SetScriptModule("Flee")
    cond = ai_mod.ConditionalAI_Create(None, "Gate")
    c = ai_mod.TGCondition()
    c._name = "InRange"
    c.SetStatus(1)
    cond.AddCondition(c)
    inner = ai_mod.PlainAI_Create(None, "Inner")
    cond.SetContainedAI(inner)
    seq.AddAI(plain)
    seq.AddAI(cond)
    seq._current_index = 1

    d = serialize_ai_tree(seq)
    assert d["name"] == "Seq"
    assert d["type"] == "SequenceAI"
    assert d["current_index"] == 1
    assert len(d["children"]) == 2
    assert d["children"][0]["name"] == "Step1"
    assert d["children"][0]["script_module"] == "Flee"
    # ConditionalAI child carries conditions + contained AI.
    gate = d["children"][1]
    assert gate["type"] == "ConditionalAI"
    # `class` rides alongside `name`: real SDK conditions carry neither a
    # GetName nor a _name, so name falls back to the class and an exported
    # tree that used to read `?:1, ?:0, ?:0` now says WHICH gate is shut.
    assert gate["conditions"] == [
        {"name": "InRange", "class": "TGCondition", "status": 1}]
    assert gate["contained"]["name"] == "Inner"


def test_serialize_sequence_default_current_index():
    seq = ai_mod.SequenceAI_Create(None, "Seq")
    d = serialize_ai_tree(seq)
    assert d["current_index"] == 0


def test_serialize_priority_list_marks_active_child():
    pl = ai_mod.PriorityListAI_Create(None, "PL")
    low = ai_mod.PlainAI_Create(None, "Low")
    low._status = ai_mod.ArtificialIntelligence.US_DONE
    high = ai_mod.PlainAI_Create(None, "High")  # ACTIVE -> first non-done
    pl.AddAI(low, 10)
    pl.AddAI(high, 20)
    d = serialize_ai_tree(pl)
    assert d["type"] == "PriorityListAI"
    assert len(d["children"]) == 2
    prios = [(c["priority"], c["name"], c["active"]) for c in d["children"]]
    assert (10, "Low", False) in prios
    assert (20, "High", True) in prios


def test_serialize_random_ai_marks_current_child():
    r = ai_mod.RandomAI_Create(None, "Rnd")
    a = ai_mod.PlainAI_Create(None, "A")
    b = ai_mod.PlainAI_Create(None, "B")
    r.AddAI(a)
    r.AddAI(b)
    r._current_child = b
    d = serialize_ai_tree(r)
    assert d["type"] == "RandomAI"
    names_current = [(c["name"], c["current"]) for c in d["children"]]
    assert ("A", False) in names_current
    assert ("B", True) in names_current


def test_serialize_preprocessing_ai_contained_and_method():
    pre = ai_mod.PreprocessingAI_Create(None, "Pre")
    pre.SetPreprocessingMethod("DoStuff")
    inner = ai_mod.PlainAI_Create(None, "Body")
    pre.SetContainedAI(inner)
    d = serialize_ai_tree(pre)
    assert d["type"] == "PreprocessingAI"
    assert d["preprocessing_method"] == "DoStuff"
    assert d["contained"]["name"] == "Body"


def test_serialize_never_raises_on_bare_node():
    """A bare ArtificialIntelligence with no extra shape still serializes."""
    bare = ai_mod.ArtificialIntelligence(None, "Bare")
    d = serialize_ai_tree(bare)
    assert d["name"] == "Bare"
    assert d["type"] == "ArtificialIntelligence"
    assert d["status"] == "ACTIVE"


# ---- collect_all_ship_ai --------------------------------------------------

def test_collect_all_ship_ai_pairs_name_and_tree():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")

    with_ai = ShipClass_Create("Galaxy")
    tree = ai_mod.SequenceAI_Create(with_ai, "Root")
    with_ai.SetAI(tree)
    # AddObjectToSet overwrites the name with the identifier, so name last.
    pSet.AddObjectToSet(with_ai, "ship_with_ai")
    with_ai.SetName("Enterprise")

    no_ai = ShipClass_Create("Galaxy")
    pSet.AddObjectToSet(no_ai, "ship_no_ai")
    no_ai.SetName("Lonely")

    entries = collect_all_ship_ai()
    by_name = {e["ship_name"]: e for e in entries}
    assert "Enterprise" in by_name
    assert "Lonely" in by_name
    assert by_name["Enterprise"]["tree"]["name"] == "Root"
    assert by_name["Lonely"]["tree"] is None


def test_collect_all_ship_ai_empty_when_no_ships():
    App.g_kSetManager._sets.clear()
    assert collect_all_ship_ai() == []


# ---- ship-level facts the tree cannot show --------------------------------
#
# Added after an export of three QuickBattle Akiras "holding instead of
# attacking" could not answer the question it was taken for: every ship sat in
# FedAttack's RearTorpRun, but the file held no position, speed, distance to
# target or tube contents, and its weapon section read stubbed system-level
# GetAmmo/CanFire (ammo 0 / can_fire True on every ship, both fake).

from engine.appc.math import TGPoint3
from engine.appc.subsystems import PhaserSystem, TorpedoSystem, TorpedoTube
from engine.appc.weapon_subsystems import PhaserBank, TorpedoAmmoType


def _two_ship_set():
    App.g_kSetManager._sets.clear()
    pSet = SetClass()
    App.g_kSetManager.AddSet(pSet, "test_set")
    a = ShipClass_Create("Akira")
    pSet.AddObjectToSet(a, "Akira-1")
    a.SetName("Akira-1")
    b = ShipClass_Create("Galaxy")
    pSet.AddObjectToSet(b, "Player")
    b.SetName("Player")
    return a, b


def _row(name):
    return {e["ship_name"]: e for e in collect_all_ship_ai()}[name]


def test_motion_reports_position_velocity_and_speed():
    a, _ = _two_ship_set()
    a.SetTranslateXYZ(10.0, 20.0, 30.0)
    a.SetVelocity(TGPoint3(3.0, 4.0, 0.0))

    m = _row("Akira-1")["motion"]
    assert m["position_gu"] == [10.0, 20.0, 30.0]
    assert m["velocity_gups"] == [3.0, 4.0, 0.0]
    assert m["speed_gups"] == pytest.approx(5.0)
    # The world-forward of an unrotated ship is model +Y.
    assert m["forward"] == [0.0, 1.0, 0.0]


def test_target_geometry_distance_bearing_and_closing_speed():
    a, b = _two_ship_set()
    a.SetTranslateXYZ(0.0, 0.0, 0.0)
    b.SetTranslateXYZ(0.0, -60.0, 0.0)       # dead astern of Akira-1
    a.SetVelocity(TGPoint3(0.0, 2.0, 0.0))    # flying away from it
    a.SetTarget("Player")

    g = _row("Akira-1")["target_geometry"]
    assert g["distance_gu"] == pytest.approx(60.0)
    # Tail-on: 180 degrees off the nose -- what a rear torpedo run looks like.
    assert g["bearing_deg"] == pytest.approx(180.0)
    # Opening at 2 GU/s, so closing speed is negative.
    assert g["closing_speed_gups"] == pytest.approx(-2.0)


def test_target_geometry_is_none_without_a_target():
    _two_ship_set()
    assert _row("Akira-1")["target_geometry"] is None


def test_nearest_ship_names_the_closest_other_ship():
    a, b = _two_ship_set()
    a.SetTranslateXYZ(0.0, 0.0, 0.0)
    b.SetTranslateXYZ(0.0, 25.0, 0.0)         # dead ahead

    n = _row("Akira-1")["nearest_ship"]
    assert n["name"] == "Player"
    assert n["distance_gu"] == pytest.approx(25.0)
    assert n["bearing_deg"] == pytest.approx(0.0)


def test_weapons_report_per_tube_readiness_not_system_stubs():
    a, _ = _two_ship_set()
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    system.AddAmmoType(TorpedoAmmoType("Photon", max_torpedoes=150))
    system.AddAmmoType(TorpedoAmmoType("Quantum", max_torpedoes=50))
    for name, loaded in (("Forward Torp 1", 1), ("Aft Torp 1", 0)):
        tube = TorpedoTube(name)
        tube._max_ready = 1
        tube._reload_delay = 40.0
        tube._resize_slots()
        tube.SetNumReady(loaded)          # syncs the reload slots, unlike _num_ready
        system.AddChildSubsystem(tube)
    a.SetTorpedoSystem(system)

    w = _row("Akira-1")["weapons"]
    torps = [s for s in w["systems"] if s["type"] == "TorpedoSystem"][0]
    assert torps["on"] is True
    assert torps["ammo_slot"] == 0
    assert [(t["name"], t["available"]) for t in torps["ammo"]] == [
        ("Photon", 150), ("Quantum", 50)]
    tubes = {t["name"]: t for t in torps["tubes"]}
    assert tubes["Forward Torp 1"]["num_ready"] == 1
    assert tubes["Aft Torp 1"]["num_ready"] == 0
    assert tubes["Aft Torp 1"]["max_ready"] == 1
    assert tubes["Aft Torp 1"]["reload_delay"] == 40.0
    # The aft tube is cooling, so it reports how far along its reload is.
    assert tubes["Aft Torp 1"]["reload_progress"] is not None
    assert tubes["Forward Torp 1"]["reload_progress"] is None
    assert w["ready_tubes"] == 1


def test_weapons_report_phaser_bank_charge():
    a, _ = _two_ship_set()
    system = PhaserSystem("Phasers")
    system.TurnOn()
    bank = PhaserBank("Dorsal Phaser 1")
    bank._max_charge = 5.0
    bank._charge_level = 0.0              # run dry: a drained bank cannot fire
    bank._min_firing_charge = 3.0
    system.AddChildSubsystem(bank)
    a.SetPhaserSystem(system)

    w = _row("Akira-1")["weapons"]
    phasers = [s for s in w["systems"] if s["type"] == "PhaserSystem"][0]
    (b,) = phasers["banks"]
    assert b["name"] == "Dorsal Phaser 1"
    assert (b["charge"], b["max_charge"], b["min_firing_charge"]) == (0.0, 5.0, 3.0)
    assert b["can_fire"] is False
    assert b["firing"] is False
    assert w["ready_banks"] == 0


def test_condition_names_its_script_and_arguments():
    ship = ShipClass_Create("Akira")
    ship.SetName("Akira-1")
    back = TGPoint3(0.0, -1.0, 0.0)
    cond = ai_mod.ConditionScript_Create(
        "Conditions.ConditionTorpsReady", "ConditionTorpsReady", "Akira-1", back)
    node = ai_mod.ConditionalAI_Create(ship, "RearTorpsReadyRearShieldOk")
    node.AddCondition(cond)

    (c,) = serialize_ai_tree(node)["conditions"]
    # The rear-tube gate and the forward-tube gate are the same class; only
    # the direction argument tells them apart.
    assert c["script"] == "ConditionTorpsReady"
    assert c["args"] == ["Akira-1", [0.0, -1.0, 0.0]]
