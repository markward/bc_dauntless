import App
from engine.appc.ai import (
    ArtificialIntelligence,
    TGCondition, TGConditionHandler,
    ConditionScript, ConditionScript_Create, ConditionScript_Cast,
    PlainAI, PlainAI_Create,
    PriorityListAI, PriorityListAI_Create,
    SequenceAI, SequenceAI_Create,
    PreprocessingAI, PreprocessingAI_Create, PreprocessingAI_Cast,
    ConditionalAI, ConditionalAI_Create,
    ConditionEventCreator,
    BuilderAI, BuilderAI_Create,
    ProximityCheck, ProximityCheck_Create,
    CharacterAction, CharacterAction_Create,
    CSP_LOW, CSP_NORMAL, CSP_HIGH,
)
from engine.appc.ships import ShipClass
from engine.appc.objects import ObjectClass


# ── ArtificialIntelligence base ───────────────────────────────────────────────

def test_ai_status_constants_distinct():
    statuses = {
        ArtificialIntelligence.US_ACTIVE,
        ArtificialIntelligence.US_DONE,
        ArtificialIntelligence.US_DORMANT,
        ArtificialIntelligence.US_INVALID,
    }
    assert len(statuses) == 4


def test_ai_default_state():
    ai = ArtificialIntelligence(ShipClass(), "MyAI")
    assert ai.IsActive() == 1
    assert ai.IsPaused() == 0
    assert ai.IsInterruptable() == 1
    assert ai.HasFocus() == 0
    assert ai.GetName() == "MyAI"


def test_ai_pause_unpause():
    ai = ArtificialIntelligence(None, "X")
    ai.Pause()
    assert ai.IsPaused() == 1
    ai.Unpause()
    assert ai.IsPaused() == 0


def test_ai_interruptable_round_trip():
    ai = ArtificialIntelligence(None, "X")
    ai.SetInterruptable(0)
    assert ai.IsInterruptable() == 0


def test_ai_get_id_unique():
    a = ArtificialIntelligence(None, "A")
    b = ArtificialIntelligence(None, "B")
    assert a.GetID() != b.GetID()


def test_ai_get_ship_returns_constructor_arg():
    ship = ShipClass()
    ai = ArtificialIntelligence(ship, "X")
    assert ai.GetShip() is ship
    assert ai.GetObject() is ship


# ── PlainAI ────────────────────────────────────────────────────────────────────

def test_plain_ai_factory_returns_subclass():
    ship = ShipClass()
    ai = PlainAI_Create(ship, "ChaseEnemy")
    assert isinstance(ai, PlainAI)
    assert isinstance(ai, ArtificialIntelligence)
    assert ai.GetShip() is ship
    assert ai.GetName() == "ChaseEnemy"


def test_plain_ai_set_script_module_round_trip():
    ai = PlainAI_Create(None, "X")
    ai.SetScriptModule("FollowObject")
    assert ai.GetScriptModule() == "FollowObject"


def test_plain_ai_get_script_instance_persists():
    """Calling GetScriptInstance multiple times returns the same data bag
    so SDK chains like pAI.GetScriptInstance().SetX(); pAI.GetScriptInstance().SetY()
    accumulate state on a single object."""
    ai = PlainAI_Create(None, "X")
    ai.SetScriptModule("FollowObject")
    a = ai.GetScriptInstance()
    b = ai.GetScriptInstance()
    assert a is b


def test_plain_ai_script_instance_set_get_round_trip():
    """SDK pattern: pScript.SetCircleSpeed(30); pScript.GetCircleSpeed().

    Uses a non-existent module name so SetScriptModule falls back to the
    _AIScriptInstance data-bag — the path exercised here is the legacy
    Phase-1 stub for scripts we haven't validated yet.
    """
    ai = PlainAI_Create(None, "X")
    ai.SetScriptModule("NoSuchAIScript_DataBag")
    s = ai.GetScriptInstance()
    s.SetCircleSpeed(30)
    s.SetTargetObjectName("Enterprise")
    s.SetSpeed(120, 0.5)  # multi-arg form
    assert s.GetCircleSpeed() == 30
    assert s.GetTargetObjectName() == "Enterprise"
    assert s.GetSpeed() == (120, 0.5)


def test_plain_ai_script_instance_unknown_method_no_op():
    """Methods like WarpBlindly, PrepareToWarp absorb without raising.

    Uses a non-existent module name to exercise the data-bag fallback.
    """
    ai = PlainAI_Create(None, "X")
    ai.SetScriptModule("NoSuchAIScript_DataBag")
    s = ai.GetScriptInstance()
    s.WarpBlindly()  # must not raise
    s.PrepareToWarp("DestSet", "DestPlacement")


def test_plain_ai_set_script_module_replaces_instance():
    ai = PlainAI_Create(None, "X")
    ai.SetScriptModule("FollowObject")
    s1 = ai.GetScriptInstance()
    ai.SetScriptModule("CircleObject")
    s2 = ai.GetScriptInstance()
    assert s1 is not s2


# ── PriorityListAI ────────────────────────────────────────────────────────────

def test_priority_list_ai_add_keeps_priority_order():
    pl = PriorityListAI_Create(None, "List")
    a = PlainAI_Create(None, "A")
    b = PlainAI_Create(None, "B")
    c = PlainAI_Create(None, "C")
    pl.AddAI(a, 10)
    pl.AddAI(b, 5)
    pl.AddAI(c, 20)
    assert pl.GetAIs() == [b, a, c]


def test_priority_list_ai_remove():
    pl = PriorityListAI_Create(None, "List")
    a = PlainAI_Create(None, "A")
    b = PlainAI_Create(None, "B")
    pl.AddAI(a, 1)
    pl.AddAI(b, 2)
    pl.RemoveAI(a)
    assert pl.GetAIs() == [b]


def test_priority_list_ai_remove_by_priority():
    pl = PriorityListAI_Create(None, "List")
    a = PlainAI_Create(None, "A")
    pl.AddAI(a, 5)
    pl.RemoveAIByPriority(5)
    assert pl.GetAIs() == []


# ── SequenceAI ────────────────────────────────────────────────────────────────

def test_sequence_ai_add_get_in_order():
    seq = SequenceAI_Create(None, "Seq")
    a = PlainAI_Create(None, "A")
    b = PlainAI_Create(None, "B")
    seq.AddAI(a)
    seq.AddAI(b)
    assert seq.GetAI(0) is a
    assert seq.GetAI(1) is b
    assert seq.GetAI(2) is None


def test_sequence_ai_loop_count_round_trip():
    seq = SequenceAI_Create(None, "Seq")
    seq.SetLoopCount(SequenceAI.LOOP_INFINITE)
    assert seq.GetLoopCount() == SequenceAI.LOOP_INFINITE
    seq.SetLoopCount(3)
    assert seq.GetLoopCount() == 3


def test_sequence_ai_remove_by_index():
    seq = SequenceAI_Create(None, "Seq")
    a, b, c = PlainAI_Create(None, "a"), PlainAI_Create(None, "b"), PlainAI_Create(None, "c")
    for ai in (a, b, c):
        seq.AddAI(ai)
    seq.RemoveAIByIndex(1)
    assert seq.GetAI(0) is a
    assert seq.GetAI(1) is c


def test_sequence_ai_flag_setters_are_quiet():
    """SDK calls these on every SequenceAI; round-trip via private state."""
    seq = SequenceAI_Create(None, "Seq")
    seq.SetResetIfInterrupted(1)
    seq.SetDoubleCheckAllDone(1)
    seq.SetSkipDormant(1)
    assert seq._reset_if_interrupted is True
    assert seq._double_check_all_done is True
    assert seq._skip_dormant is True


# ── PreprocessingAI ───────────────────────────────────────────────────────────

def test_preprocessing_ai_factory_and_contained():
    pp = PreprocessingAI_Create(None, "Prep")
    inner = PlainAI_Create(None, "Inner")
    pp.SetContainedAI(inner)
    assert pp.GetContainedAI() is inner


def test_preprocessing_ai_method_instance_data_bag():
    pp = PreprocessingAI_Create(None, "Prep")
    pp.SetPreprocessingMethod("SelectTarget")
    inst = pp.GetPreprocessingInstance()
    inst.SetThreshold(0.7)
    assert inst.GetThreshold() == 0.7


def test_preprocessing_ai_cast():
    plain = PlainAI_Create(None, "X")
    prep = PreprocessingAI_Create(None, "Y")
    assert PreprocessingAI_Cast(plain) is None
    assert PreprocessingAI_Cast(prep) is prep


# ── ConditionalAI + TGCondition + ConditionScript ─────────────────────────────

def test_condition_status_round_trip():
    c = TGCondition()
    assert c.GetStatus() == 0
    c.SetStatus(1)
    assert c.GetStatus() == 1


def test_condition_handlers_fire_only_when_active_and_changed():
    c = TGCondition()
    fired = []

    class H(TGConditionHandler):
        def ConditionChanged(self, cond):
            fired.append(cond.GetStatus())

    h = H()
    c.AddHandler(h)
    c.SetStatus(1)        # inactive — no fire
    assert fired == []
    c.SetActive()
    c.SetStatus(0)        # changed: 1 -> 0 — fires
    assert fired == [0]
    c.SetStatus(0)        # unchanged — no fire
    assert fired == [0]
    c.SetStatus(1)        # changed — fires
    assert fired == [0, 1]


def test_condition_remove_handler():
    c = TGCondition()
    fired = []

    class H(TGConditionHandler):
        def ConditionChanged(self, cond):
            fired.append(1)
    h = H()
    c.AddHandler(h)
    c.RemoveHandler(h)
    c.SetActive()
    c.SetStatus(1)
    assert fired == []


def test_condition_script_create_records_args():
    cs = ConditionScript_Create("Conditions.ConditionInRange", "ConditionInRange", 60, "JonKa", "Chairo")
    assert isinstance(cs, ConditionScript)
    assert cs.GetModuleName() == "Conditions.ConditionInRange"
    assert cs.GetClassName() == "ConditionInRange"
    assert cs.GetArguments() == (60, "JonKa", "Chairo")


def test_condition_script_cast():
    plain = TGCondition()
    cs = ConditionScript("m", "c")
    assert ConditionScript_Cast(plain) is None
    assert ConditionScript_Cast(cs) is cs


def test_conditional_ai_subscribes_as_handler():
    """SDK pattern: cond.AddHandler is called automatically by AddCondition."""
    ai = ConditionalAI_Create(None, "X")
    cond = TGCondition()
    ai.AddCondition(cond)
    assert cond._handlers == [ai]


def test_conditional_ai_evaluation_function_round_trip():
    ai = ConditionalAI_Create(None, "X")
    fn = lambda c: True
    ai.SetEvaluationFunction(fn)
    assert ai.GetEvaluationFunction() is fn


def test_conditional_ai_contained():
    ai = ConditionalAI_Create(None, "X")
    inner = PlainAI_Create(None, "Inner")
    ai.SetContainedAI(inner)
    assert ai.GetContainedAI() is inner


# ── ConditionEventCreator ─────────────────────────────────────────────────────

def test_condition_event_creator_subscribes_and_fires_event():
    """When the condition flips while active, the stored event should be
    enqueued via App.g_kEventManager.AddEvent."""
    from engine.appc.events import TGEvent
    creator = ConditionEventCreator()
    cond = TGCondition()
    creator.AddCondition(cond)
    evt = TGEvent()
    creator.SetEvent(evt)

    captured = []
    real_add = App.g_kEventManager.AddEvent
    App.g_kEventManager.AddEvent = lambda e: captured.append(e)
    try:
        cond.SetActive()
        cond.SetStatus(1)  # change → fires
    finally:
        App.g_kEventManager.AddEvent = real_add
    assert captured == [evt]


def test_condition_event_creator_set_event_round_trip():
    creator = ConditionEventCreator()
    sentinel = object()
    creator.SetEvent(sentinel)
    assert creator.GetEvent() is sentinel


# ── BuilderAI ─────────────────────────────────────────────────────────────────

def test_builder_ai_inherits_preprocessing():
    b = BuilderAI_Create(None, "Build")
    assert isinstance(b, PreprocessingAI)


def test_builder_ai_blocks_and_dependencies_round_trip():
    b = BuilderAI_Create(None, "Build")
    b.AddAIBlock("Damage1Pct", PlainAI_Create(None, "D1"))
    b.AddAIBlock("Damage10Pct", PlainAI_Create(None, "D10"))
    b.AddDependency("Damage10Pct", "Damage1Pct")
    b.AddDependencyObject("Damage1Pct", "sMissionModuleName", "Maelstrom.E5M2")
    assert b.GetAIBlock("Damage1Pct") is not None
    assert b.GetDependencies() == [("Damage10Pct", "Damage1Pct")]
    assert b.GetDependencyObjects() == [("Damage1Pct", "sMissionModuleName", "Maelstrom.E5M2")]


# ── ProximityCheck ────────────────────────────────────────────────────────────

def test_proximity_check_factory_is_object_class():
    pc = ProximityCheck_Create(42)
    assert isinstance(pc, ObjectClass)
    assert pc.GetEventType() == 42


def test_proximity_check_radius_round_trip():
    pc = ProximityCheck_Create()
    pc.SetRadius(150.0)
    assert pc.GetRadius() == 150.0


def test_proximity_check_check_list_add_remove():
    pc = ProximityCheck_Create()
    o1, o2 = ObjectClass(), ObjectClass()
    pc.AddObjectToCheckList(o1)
    pc.AddObjectToCheckList(o2)
    assert pc.IsObjectInCheckList(o1) == 1
    pc.RemoveObjectFromCheckList(o1)
    assert pc.IsObjectInCheckList(o1) == 0
    assert pc.IsObjectInCheckList(o2) == 1


def test_proximity_check_ignore_object_size_round_trip():
    pc = ProximityCheck_Create()
    pc.SetIgnoreObjectSize(1)
    assert pc.GetIgnoreObjectSize() == 1


def test_proximity_check_trigger_type_round_trip():
    pc = ProximityCheck_Create()
    pc.SetTriggerType(ProximityCheck.TT_OUTSIDE)
    assert pc.GetTriggerType() == ProximityCheck.TT_OUTSIDE
    pc.SetTriggerType(ProximityCheck.TT_INSIDE)
    assert pc.GetTriggerType() == ProximityCheck.TT_INSIDE


def test_proximity_check_add_object_list():
    pc = ProximityCheck_Create()
    objs = [ObjectClass(), ObjectClass(), ObjectClass()]
    pc.AddObjectListToCheckList(objs)
    for o in objs:
        assert pc.IsObjectInCheckList(o) == 1


def test_proximity_check_inside_outside_constants():
    """SDK constants from sdk/.../App.py:6140-6141, used by E6M3/E6M4/E6M5
    and Conditions/ConditionInRange.py."""
    assert ProximityCheck.TT_INSIDE == 0
    assert ProximityCheck.TT_OUTSIDE == 1


def test_proximity_check_add_object_to_check_list_with_trigger_type():
    """SDK pattern: pProximity.AddObjectToCheckList(pObj, App.ProximityCheck.TT_INSIDE)."""
    pc = ProximityCheck_Create()
    obj = ObjectClass()
    pc.AddObjectToCheckList(obj, ProximityCheck.TT_INSIDE)
    assert pc.IsObjectInCheckList(obj) == 1
    # Stored tuple records the per-object trigger type.
    assert pc._check_objects[0][1] == ProximityCheck.TT_INSIDE


# ── BuilderAI 3-arg signature ─────────────────────────────────────────────────

def test_builder_ai_create_accepts_module_name_third_arg():
    """SDK pattern (CallDamageAI.py:18): BuilderAI_Create(pShip, name, __name__)."""
    b = BuilderAI_Create(None, "AlertLevel Builder", "AI.Compound.NonFedAttack")
    assert b.GetModuleName() == "AI.Compound.NonFedAttack"


# ── PreprocessingAI two-arg signature ────────────────────────────────────────

def test_set_preprocessing_method_two_arg_form_keeps_caller_instance():
    """SDK pattern: pAI.SetPreprocessingMethod(pScript, "Update").  pScript is
    a Python object the caller already constructed; it must come back from
    GetPreprocessingInstance unchanged."""
    pp = PreprocessingAI_Create(None, "X")
    script = object()
    pp.SetPreprocessingMethod(script, "Update")
    assert pp.GetPreprocessingInstance() is script
    assert pp._preprocessing_method == "Update"


def test_set_preprocessing_method_one_arg_form_creates_data_bag():
    pp = PreprocessingAI_Create(None, "X")
    pp.SetPreprocessingMethod("UpdateMethod")
    inst = pp.GetPreprocessingInstance()
    inst.SetDelta(0.5)
    assert inst.GetDelta() == 0.5


# ── Script-instance kwargs absorption ────────────────────────────────────────

def test_script_instance_setter_absorbs_kwargs():
    """Some compound AI scripts pass kwargs through wrappers — must not raise."""
    ai = PlainAI_Create(None, "X")
    ai.SetScriptModule("BasicAttack")
    s = ai.GetScriptInstance()
    s.SetTargets("Galaxy 2", Difficulty=0.7, AvoidTorps=1)
    # Stored as (args, kwargs) tuple when kwargs present.
    stored = s._data["Targets"]
    assert stored == (("Galaxy 2",), {"Difficulty": 0.7, "AvoidTorps": 1})


# ── CharacterAction ──────────────────────────────────────────────────────────

def test_character_action_action_type_constants_distinct():
    types = {
        CharacterAction.AT_SPEAK_LINE,
        CharacterAction.AT_SAY_LINE,
        CharacterAction.AT_LOOK_AT_ME,
        CharacterAction.AT_PLAY_ANIMATION,
        CharacterAction.AT_SET_LOCATION,
    }
    assert len(types) == 5


def test_character_action_factory_round_trip():
    ca = CharacterAction_Create(None, CharacterAction.AT_SPEAK_LINE, "Hello", "bridge", 0, None, CSP_NORMAL)
    assert isinstance(ca, CharacterAction)
    assert ca.GetActionType() == CharacterAction.AT_SPEAK_LINE
    assert ca.GetDetail() == "Hello"
    assert ca.GetPriority() == CSP_NORMAL


def test_character_action_play_completes():
    """Inherited TGAction.Play() flips _playing and runs Completed."""
    ca = CharacterAction_Create(None, CharacterAction.AT_BREATHE)
    ca.Play()
    assert ca.IsPlaying() is False


def test_character_action_priority_round_trip():
    ca = CharacterAction_Create()
    ca.SetPriority(CSP_HIGH)
    ca.SetSubPriority(5)
    assert ca.GetPriority() == CSP_HIGH
    assert ca.GetSubPriority() == 5


def test_csp_constants_distinct():
    assert len({CSP_LOW, CSP_NORMAL, CSP_HIGH}) == 3


# ── App namespace exposure ───────────────────────────────────────────────────

def test_app_exposes_ai_factories():
    assert App.PlainAI_Create is PlainAI_Create
    assert App.ConditionalAI_Create is ConditionalAI_Create
    assert App.SequenceAI_Create is SequenceAI_Create
    assert App.PriorityListAI_Create is PriorityListAI_Create
    assert App.PreprocessingAI_Create is PreprocessingAI_Create
    assert App.BuilderAI_Create is BuilderAI_Create
    assert App.ConditionScript_Create is ConditionScript_Create
    assert App.ProximityCheck_Create is ProximityCheck_Create
    assert App.CharacterAction_Create is CharacterAction_Create


def test_app_exposes_ai_classes_and_constants():
    assert App.ArtificialIntelligence.US_ACTIVE == 0
    assert App.SequenceAI.LOOP_INFINITE == -1
    assert App.PreprocessingAI.PS_NORMAL == 0
    assert App.CharacterAction.AT_SPEAK_LINE == 10
    assert App.CSP_NORMAL == 1
