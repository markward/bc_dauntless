"""Tests for the AI-tree introspection helpers used by AIInspectorPanel.

serialize_ai_tree turns a live AI subtree into a JSON-able nested dict;
collect_all_ship_ai walks every ship via ship_iter and pairs each ship
name with its serialized tree (or None when the ship has no AI).
"""
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
    assert gate["conditions"] == [{"name": "InRange", "status": 1}]
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
