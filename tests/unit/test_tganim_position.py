from engine.appc.actions import (
    TGAnimPosition, TGAnimPosition_Create, TGSequence_Create,
)


def test_factory_records_clip_name():
    node = object()  # SDK passes an anim node; the action only keeps the name
    act = TGAnimPosition_Create(node, "db_stand_t_l")
    assert isinstance(act, TGAnimPosition)
    assert act.name == "db_stand_t_l"


def test_appended_action_is_readable_off_the_sequence():
    seq = TGSequence_Create()
    seq.AppendAction(TGAnimPosition_Create(None, "db_StoL1_S"))
    last = seq.GetAction(seq.GetNumActions() - 1)
    assert last.name == "db_StoL1_S"


def test_app_exposes_factory():
    import App
    act = App.TGAnimPosition_Create(None, "EB_stand_s_s")
    assert act.name == "EB_stand_s_s"
