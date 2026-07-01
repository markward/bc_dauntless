"""engine.appc.weapon_tactical_commands — Surface 2 of the weapons-config
feature: equipment-gated command rows appended to the F2 Tactical officer menu.

`sync(player)` is idempotent (safe every tick): it locates the Tactical menu,
reads the weapon config, adds/removes command buttons by gate, updates their
labels dynamically, and re-adds them after a per-bridge-load menu rebuild.

Clicking a button drives the shared `weapon_config` mutators through a single
dispatcher keyed on the event subevent int.
"""
from unittest.mock import patch

import App
from engine.appc.characters import STTopLevelMenu, STButton
from engine.appc.math import TGPoint3
from engine.appc.properties import WeaponSystemProperty
from engine.appc.ships import ShipClass_Create
from engine.appc.subsystems import (
    CloakingSubsystem,
    PhaserSystem,
    PhaserBank,
    TorpedoSystem,
    TorpedoTube,
    TractorBeamSystem,
    TractorBeam,
)
from engine.appc.weapon_subsystems import TorpedoAmmoType
from engine.appc.windows import TacticalControlWindow
from engine.appc import weapon_config
from engine.appc import weapon_tactical_commands as wtc


# ── Construction helpers (mirror tests/unit/test_weapon_config.py) ───────────

def _bare_ship():
    ship = ShipClass_Create("Player")
    ship.SetWorldLocation(TGPoint3(0, 0, 0))
    return ship


def _attach_torpedoes(ship, *, num_tubes=2, ammo_names=("Photon", "Quantum"),
                      ready_per_tube=100):
    parent = TorpedoSystem("Torpedoes")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Torpedoes"))
    parent._parent_ship = ship
    for i, name in enumerate(ammo_names):
        parent.AddAmmoType(TorpedoAmmoType(name, power_cost=20.0 + i))
    for i in range(num_tubes):
        tube = TorpedoTube(f"Tube {i}")
        tube._max_ready = ready_per_tube
        tube._num_ready = ready_per_tube
        parent.AddChildSubsystem(tube)
    ship._torpedo_system = parent
    return parent


def _attach_phasers(ship, *, banks=2):
    parent = PhaserSystem("Phasers")
    parent.TurnOn()
    parent._parent_ship = ship
    for i in range(banks):
        parent.AddChildSubsystem(PhaserBank(f"Bank {i}"))
    ship._phaser_system = parent
    return parent


def _attach_tractor(ship):
    parent = TractorBeamSystem("Tractors")
    parent.TurnOn()
    parent.SetProperty(WeaponSystemProperty("Tractors"))
    parent.SetSingleFire(1)
    parent._parent_ship = ship
    em = TractorBeam("Aft Tractor")
    em._max_charge = 10.0
    em._min_firing_charge = 1.0
    em._charge_level = 10.0
    parent.AddChildSubsystem(em)
    ship._tractor_beam_system = parent
    return parent


def _attach_cloak(ship):
    cloak = CloakingSubsystem("Cloak")
    cloak.TurnOn()
    ship._cloaking_subsystem = cloak
    return cloak


TACTICAL_LABEL = wtc.TACTICAL_MENU_LABEL


def _make_tactical_menu():
    """A registered Tactical top-level menu, as CreateTacticalMenu produces."""
    TacticalControlWindow._instance = None
    tcw = TacticalControlWindow.GetInstance()
    menu = STTopLevelMenu(TACTICAL_LABEL)
    tcw.AddMenuToList(menu)
    return tcw, menu


def _menu_button_labels(menu):
    return [c.GetLabel() for c in menu._children if isinstance(c, STButton)]


def _with_current_player(ship):
    """Point Game_GetCurrentGame().GetPlayer() at `ship`."""
    from engine.core.game import Game_SetCurrentPlayer
    Game_SetCurrentPlayer(ship)


def setup_function(_):
    TacticalControlWindow._instance = None


# ── Gating: only equipped commands are added ─────────────────────────────────

def test_galaxy_like_ship_adds_phasers_spread_tractor_no_cloak_no_type():
    # Phasers + 4 tubes single-ammo (spread cyclable, type NOT cyclable) + tractor.
    ship = _bare_ship()
    _attach_phasers(ship)
    _attach_torpedoes(ship, num_tubes=4, ammo_names=("Photon",))
    _attach_tractor(ship)
    _tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    labels = _menu_button_labels(menu)

    assert any("Phasers" in l for l in labels)
    assert any("Spread" in l for l in labels)
    assert any("Tractor" in l for l in labels)
    assert not any("Cloak" in l for l in labels)
    # single ammo type -> no "Use ... Torpedoes" row
    assert not any("Torpedoes" in l for l in labels)


def test_cloak_multitype_ship_adds_all_five():
    ship = _bare_ship()
    _attach_phasers(ship)
    _attach_torpedoes(ship, num_tubes=4, ammo_names=("Photon", "Quantum"))
    _attach_tractor(ship)
    _attach_cloak(ship)
    _tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    labels = _menu_button_labels(menu)

    assert any("Phasers" in l for l in labels)
    assert any("Torpedoes" in l for l in labels)   # type cycle
    assert any("Spread" in l for l in labels)
    assert any("Tractor" in l for l in labels)
    assert any("Cloak" in l for l in labels)


def test_no_tactical_menu_is_noop():
    ship = _bare_ship()
    _attach_phasers(ship)
    TacticalControlWindow._instance = None
    # No menu registered — must not raise.
    wtc.sync(ship)


def test_none_player_is_noop():
    _make_tactical_menu()
    wtc.sync(None)  # must not raise


# ── Idempotency + rebuild self-heal ──────────────────────────────────────────

def test_sync_twice_does_not_duplicate_buttons():
    ship = _bare_ship()
    _attach_phasers(ship)
    _attach_cloak(ship)
    _tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    first = _menu_button_labels(menu)
    wtc.sync(ship)
    second = _menu_button_labels(menu)

    assert first == second
    assert len(second) == len(set(second))  # no duplicates


def test_rebuilt_menu_gets_commands_readded():
    ship = _bare_ship()
    _attach_cloak(ship)
    tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    assert any("Cloak" in l for l in _menu_button_labels(menu))

    # Bridge reload: fresh Tactical menu replaces the old one.
    tcw._menus = []
    fresh = STTopLevelMenu(TACTICAL_LABEL)
    tcw.AddMenuToList(fresh)

    wtc.sync(ship)
    assert any("Cloak" in l for l in _menu_button_labels(fresh))


# ── Dynamic labels ───────────────────────────────────────────────────────────

def _find_button(menu, needle):
    for c in menu._children:
        if isinstance(c, STButton) and needle in c.GetLabel():
            return c
    return None


def test_cloak_label_flips_after_toggle():
    ship = _bare_ship()
    _attach_cloak(ship)
    _tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    assert _find_button(menu, "Cloak").GetLabel() == "Engage Cloak"

    weapon_config.toggle_cloak(ship)
    wtc.sync(ship)
    assert _find_button(menu, "Cloak").GetLabel() == "Disengage Cloak"


def test_phaser_label_flips_after_toggle():
    ship = _bare_ship()
    _attach_phasers(ship)
    _tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    assert _find_button(menu, "Phasers").GetLabel() == "Set Phasers to Light"

    weapon_config.toggle_phaser_intensity(ship)  # -> Light
    wtc.sync(ship)
    assert _find_button(menu, "Phasers").GetLabel() == "Set Phasers to Full"


def test_spread_label_advances_after_cycle():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=4, ammo_names=("Photon",))
    _tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    assert _find_button(menu, "Spread").GetLabel() == "Torpedo Spread Single"

    weapon_config.cycle_torpedo_spread(ship)  # -> 2
    wtc.sync(ship)
    assert _find_button(menu, "Spread").GetLabel() == "Torpedo Spread Dual"

    weapon_config.cycle_torpedo_spread(ship)  # -> 4
    wtc.sync(ship)
    assert _find_button(menu, "Spread").GetLabel() == "Torpedo Spread Quad"


def test_type_label_shows_next_ammo_name():
    ship = _bare_ship()
    _attach_torpedoes(ship, num_tubes=2, ammo_names=("Photon", "Quantum"))
    _tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    # current == Photon, next == Quantum
    assert _find_button(menu, "Torpedoes").GetLabel() == "Use Quantum Torpedoes"

    weapon_config.cycle_torpedo_type(ship)  # current == Quantum, next == Photon
    wtc.sync(ship)
    assert _find_button(menu, "Torpedoes").GetLabel() == "Use Photon Torpedoes"


# ── Clicking a command drives the shared mutator ─────────────────────────────

def test_click_cloak_command_toggles_cloak_via_dispatcher():
    ship = _bare_ship()
    cloak = _attach_cloak(ship)
    _tcw, menu = _make_tactical_menu()
    _with_current_player(ship)

    wtc.sync(ship)
    btn = _find_button(menu, "Cloak")
    assert cloak.IsTryingToCloak() == 0
    # Full click path: SendActivationEvent -> AddEvent -> menu.ProcessEvent
    # -> dispatcher reads subevent int -> toggle_cloak(current player).
    btn.SendActivationEvent()
    assert cloak.IsTryingToCloak() == 1


def test_click_cloak_command_end_to_end_via_crew_menu_panel():
    # Drive the real inbound path: CrewMenuPanel.render_payload assigns widget
    # ids, then dispatch_event("click:<wid>") fires the button's activation.
    from engine.ui.crew_menu_panel import CrewMenuPanel
    ship = _bare_ship()
    cloak = _attach_cloak(ship)
    _tcw, menu = _make_tactical_menu()
    _with_current_player(ship)

    wtc.sync(ship)
    panel = CrewMenuPanel()
    panel.render_payload()  # populates panel._widgets_by_id
    btn = _find_button(menu, "Cloak")
    from engine.appc.tg_ui.widgets import ensure_widget_id
    wid = ensure_widget_id(btn)

    assert cloak.IsTryingToCloak() == 0
    panel.dispatch_event(f"click:{wid}")
    assert cloak.IsTryingToCloak() == 1


def test_dispatcher_registered_once_across_repeated_syncs():
    # Repeated syncs must not re-register the handler (a double registration
    # would toggle the subsystem twice per click).
    ship = _bare_ship()
    cloak = _attach_cloak(ship)
    _tcw, menu = _make_tactical_menu()
    _with_current_player(ship)

    wtc.sync(ship)
    wtc.sync(ship)
    wtc.sync(ship)
    btn = _find_button(menu, "Cloak")
    btn.SendActivationEvent()
    assert cloak.IsTryingToCloak() == 1  # exactly one toggle, not three


def test_click_phaser_command_toggles_intensity_via_dispatcher():
    ship = _bare_ship()
    p = _attach_phasers(ship)
    _tcw, menu = _make_tactical_menu()
    _with_current_player(ship)

    wtc.sync(ship)
    btn = _find_button(menu, "Phasers")
    assert p.GetPowerLevel() == PhaserSystem.PP_HIGH
    btn.SendActivationEvent()
    assert p.GetPowerLevel() == PhaserSystem.PP_LOW


def test_dispatcher_resolves_current_player_not_stale_ship():
    # sync run against ship A; dispatcher must act on whoever is current player.
    ship_a = _bare_ship()
    _attach_cloak(ship_a)
    ship_b = _bare_ship()
    cloak_b = _attach_cloak(ship_b)
    _tcw, menu = _make_tactical_menu()

    _with_current_player(ship_a)
    wtc.sync(ship_a)
    btn = _find_button(menu, "Cloak")

    # Player swaps to ship_b before the click.
    _with_current_player(ship_b)
    btn.SendActivationEvent()
    assert cloak_b.IsTryingToCloak() == 1


def test_click_tractor_command_engages_via_dispatcher():
    ship = _bare_ship()
    tractor = _attach_tractor(ship)
    tgt = ShipClass_Create("Enemy")
    tgt.SetWorldLocation(TGPoint3(0, 40, 0))
    ship._target = tgt
    _tcw, menu = _make_tactical_menu()
    _with_current_player(ship)

    wtc.sync(ship)
    btn = _find_button(menu, "Tractor")
    with patch("engine.audio.tg_sound.TGSoundManager.instance"):
        btn.SendActivationEvent()
    assert tractor.IsFiring() == 1


# ── Ungating removes the command ─────────────────────────────────────────────

def test_removing_subsystem_ungates_command():
    ship = _bare_ship()
    _attach_cloak(ship)
    _tcw, menu = _make_tactical_menu()

    wtc.sync(ship)
    assert _find_button(menu, "Cloak") is not None

    # Cloak subsystem removed (e.g. destroyed / swapped hull).
    ship._cloaking_subsystem = None
    wtc.sync(ship)
    assert _find_button(menu, "Cloak") is None
