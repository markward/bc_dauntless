"""ET_PLAYER_TORPEDO_TYPE_CHANGED — the player switched torpedo type.

BC's C++ side posts this; the SDK listens on the PLAYER instance and has Felix
speak the callout:

  Bridge/TacticalCharacterHandlers.py:59  (inside AttachMenuToTactical, which
      Bridge/Characters/Felix.py:187 calls when the bridge loads)
        pPlayer.AddPythonFuncHandlerForInstance(
            App.ET_PLAYER_TORPEDO_TYPE_CHANGED, __name__ + ".PlayerTorpChanged")

  Bridge/TacticalCharacterHandlers.py:262  PlayerTorpChanged
        pTorps = App.TorpedoSystem_Cast(pEvent.GetSource())   # SOURCE = the system
        ... AT_SAY_LINE "LoadingPhoton" / "LoadingQuantum" / "LoadingTorps",
            or "PhotonsOnlyDaunt" for a 1-type Galaxy

That registration was already running live — docs/stub_heatmap.md recorded
`EventType | ET_PLAYER_TORPEDO_TYPE_CHANGED` at 498 hits across 103 runs, which is
events._validate_event_type logging it as UNDEFINED. Undefined meant App vended a
fresh _NamedStub per access, so the SDK's handler was keyed on an object that
could never be matched: the type switch worked, Felix just never spoke.

Event id 0x00800068 is BC's own, read from the live constant dump
tools/probes/results/q13_constants_battle.txt:523
(`App.ET_PLAYER_TORPEDO_TYPE_CHANGED = 8388712 (0x800068)`) — and it lands exactly
in the measured torpedo cluster: ...65 reload, ...66 fired, ...67 ammo-consumed,
...68 type-changed. Not invented.
"""
import pytest

import App
from engine.appc.subsystems import TorpedoSystem
from engine.appc.weapon_subsystems import TorpedoAmmoType


@pytest.fixture
def captured():
    """Every ET_PLAYER_TORPEDO_TYPE_CHANGED the engine posts, in order."""
    seen = []
    globals()["_collect"] = lambda _obj, evt: seen.append(evt)
    App.g_kEventManager.AddBroadcastPythonFuncHandler(
        App.ET_PLAYER_TORPEDO_TYPE_CHANGED, object(), __name__ + "._collect")
    yield seen
    App.g_kEventManager._broadcast_handlers.pop(
        App.ET_PLAYER_TORPEDO_TYPE_CHANGED, None)


def _two_type_ship():
    """A ship with Photon in slot 0 and Quantum in slot 1, both stocked so both
    are selectable (CycleAmmoType skips empty declared types)."""
    from engine.appc.ships import ShipClass_Create

    ship = ShipClass_Create("Test")
    system = TorpedoSystem("Torpedoes")
    system.TurnOn()
    for slot, name in ((0, "Photon"), (1, "Quantum")):
        ammo = TorpedoAmmoType(name, max_torpedoes=50)
        ammo.SetAvailable(50)
        system.AddAmmoType(ammo)
    system._parent_ship = ship
    ship._torpedo_system = system
    return ship, system


def _player_ship():
    ship, system = _two_type_ship()
    App.Game_SetCurrentPlayer(ship)
    return ship, system


# ── The id itself ──────────────────────────────────────────────────────────

def test_event_id_matches_the_real_game():
    from engine.appc import events
    assert events.ET_PLAYER_TORPEDO_TYPE_CHANGED == 0x00800068


def test_app_reexports_it_as_a_real_int_not_a_stub():
    """The whole bug: an undefined App.ET_* is a _NamedStub whose hash is fresh
    per access, so the SDK's handler is registered under an unmatchable key."""
    assert isinstance(App.ET_PLAYER_TORPEDO_TYPE_CHANGED, int)


# ── Dispatch ───────────────────────────────────────────────────────────────

def test_cycling_the_players_torpedo_type_posts_the_event(captured):
    """Source = the TORPEDO SYSTEM (PlayerTorpChanged casts it with
    TorpedoSystem_Cast), destination = the ship (so the handler the SDK
    registered on the player instance is reached)."""
    ship, system = _player_ship()

    system.CycleAmmoType()

    assert len(captured) == 1, f"expected one event, got {len(captured)}"
    assert captured[0].GetSource() is system
    assert captured[0].GetDestination() is ship


def test_direct_slot_selection_posts_the_event(captured):
    """Not only cycling: AI/Preprocessors ChooseTorpType and the HUD both select
    a slot outright via SetAmmoType/SetCurrentAmmoSlot."""
    _, system = _player_ship()

    system.SetCurrentAmmoSlot(1)

    assert len(captured) == 1


def test_reselecting_the_same_type_posts_nothing(captured):
    """Only a real CHANGE is announced.

    Load-bearing: Actions.ShipScriptActions.ReloadShip:400 ends every starbase
    dock with SetAmmoType(GetAmmoTypeNumber(), 0) — re-selecting whatever is
    already current. Firing on that would have Felix announce a torpedo switch
    every time the player docks."""
    _, system = _player_ship()
    current = system.GetCurrentAmmoSlot()

    system.SetCurrentAmmoSlot(current)

    assert captured == []


def test_unselectable_cycle_posts_nothing(captured):
    """CycleAmmoType is a no-op with fewer than two selectable slots, so there is
    no change to announce."""
    from engine.appc.ships import ShipClass_Create
    ship = ShipClass_Create("Solo")
    system = TorpedoSystem("Torpedoes")
    ammo = TorpedoAmmoType("Photon", max_torpedoes=50)
    ammo.SetAvailable(50)
    system.AddAmmoType(ammo)
    system._parent_ship = ship
    ship._torpedo_system = system
    App.Game_SetCurrentPlayer(ship)

    system.CycleAmmoType()

    assert captured == []


def test_npc_torpedo_type_change_posts_nothing(captured):
    """BC's ET_PLAYER_ locality gate — the same rule ET_TORPEDO_AMMO_CONSUMED
    already follows (weapon_subsystems._broadcast_ammo_consumed_if_player).
    Without it, every NPC that switches ammo makes Felix talk about it."""
    player, _ = _player_ship()
    _, npc_system = _two_type_ship()          # a different ship, not the player
    assert App.Game_GetCurrentPlayer() is player

    npc_system.CycleAmmoType()

    assert captured == []


# ── The wiring the SDK depends on ──────────────────────────────────────────

def test_handler_registered_the_way_the_sdk_registers_it_actually_fires():
    """End of the chain: register on the player instance using the very
    expression TacticalCharacterHandlers.py:59 uses, and confirm dispatch
    reaches it. This is what a fresh-stub key made impossible."""
    ship, system = _player_ship()
    hits = []
    globals()["_sdk_style_handler"] = lambda obj, evt: hits.append(evt)
    ship.AddPythonFuncHandlerForInstance(
        App.ET_PLAYER_TORPEDO_TYPE_CHANGED, __name__ + "._sdk_style_handler")
    try:
        system.CycleAmmoType()
    finally:
        ship.RemoveHandlerForInstance(
            App.ET_PLAYER_TORPEDO_TYPE_CHANGED, __name__ + "._sdk_style_handler")

    assert len(hits) == 1, "the SDK-style instance handler never fired"
    assert App.TorpedoSystem_Cast(hits[0].GetSource()) is system, (
        "PlayerTorpChanged casts the source with TorpedoSystem_Cast")
