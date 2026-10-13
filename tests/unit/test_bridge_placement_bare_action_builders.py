"""SDK animation builders may return ONE action, not a TGSequence.

Every officer-to-officer turn builder (`<Station>Turn<X>` / `<Station>Back<X>`,
80 registrations across the stock crew) returns a bare TGAnimAction, e.g.
MediumAnimations.DBHTalkT -> `return pAnimAction1`. The clip-capture helpers
iterated GetNumActions()/GetAction(i), which a TGAnimAction does not have, so
they walked stubs and returned None -- the officer's turn clip never played.
This was the heatmap's regressed `TGAnimAction._anim_node.kind` row.

These drive the REAL SDK builders (Kiska's registrations), not fake sequences:
the fake-sequence chair tests are exactly why this went unseen.
"""
import App
from engine.appc import bridge_placement as bp
from engine.core import stub_telemetry


def _kiska_at_helm():
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyFemM/BodyFemM.nif",
        "data/Models/Characters/Heads/HeadKiska/kiska_head.nif",
    )
    c.SetCharacterName("Kiska")
    c.SetLocation("DBHelm")
    c.AddAnimation("DBHelmTurnT", "Bridge.Characters.MediumAnimations.DBHTalkT")
    c.AddAnimation("DBHelmBackT", "Bridge.Characters.MediumAnimations.DBHTalkFinT")
    return c


def test_officer_turn_builder_clip_is_captured():
    # Fails if capture_registered_clip only walks TGSequence actions.
    out = bp.capture_registered_clip(_kiska_at_helm(), "TurnT")
    assert out == {"clip_nif": "data/animations/DB_H_Talk_X_M.NIF"}


def test_officer_turn_back_builder_clip_is_captured():
    out = bp.capture_registered_clip(_kiska_at_helm(), "BackT")
    assert out == {"clip_nif": "data/animations/DB_H_Talk_fin_T_M.NIF"}


def test_bare_action_builder_has_no_chair_clip():
    # A single character-node action carries no chair (object) clip.
    assert bp.capture_chair_clip(_kiska_at_helm(), "TurnT") is None


def test_walk_action_of_bare_character_action_is_itself():
    # Fails if walk_action_of only walks TGSequence actions.
    action = bp.resolve_builder(_kiska_at_helm(), "DBHelmTurnT")
    assert isinstance(action, App.TGAnimAction)
    assert bp.walk_action_of(action) is action


def test_capturing_a_bare_action_touches_no_stub(monkeypatch):
    # The heatmap signal itself: GetNumActions/GetAction on a TGAnimAction.
    monkeypatch.setattr(stub_telemetry, "ENABLED", True)
    stub_telemetry.reset()
    try:
        c = _kiska_at_helm()
        bp.capture_registered_clip(c, "TurnT")
        bp.capture_chair_clip(c, "TurnT")
        hits = {k for k in stub_telemetry._attr_hits if k[0] == "TGAnimAction"}
    finally:
        stub_telemetry.reset()
    assert hits == set()


def test_empty_sequence_builder_still_resolves_to_none(monkeypatch):
    # The emptiness check must keep rejecting an empty TGSequence.
    import types
    mod = types.ModuleType("_empty_builder_mod")
    mod.Build = lambda character: App.TGSequence_Create()
    monkeypatch.setitem(__import__("sys").modules, "_empty_builder_mod", mod)
    c = _kiska_at_helm()
    c.AddAnimation("DBHelmEmpty", "_empty_builder_mod.Build")
    assert bp.resolve_builder(c, "DBHelmEmpty") is None
