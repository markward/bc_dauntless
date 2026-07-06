"""Engineering power-transmission-grid panel (BC F5 top-right grid).

Renders LIVE engine state (not the PowerDisplay widget tree): sliders per
group, the banded Power Used bar, Warp Core / Main / Reserve columns, and
the tractor/cloak siphon lines. SDK PowerDisplay.py keeps owning the logic
(AdjustPower, refresh events); this panel is the display surface.
Payload semantics follow power-system.md §"The Power Used Bar":
  blue  = warp-core output / max bandwidth   (inside => batteries charging)
  yellow= main-conduit share                 (drawing Main)
  red   = backup-conduit share               (drawing Reserve)
"""
import json

from engine.ui.panel import Panel

_GROUPS = (
    ("weapons", "Weapons", ("GetPhaserSystem", "GetTorpedoSystem", "GetPulseWeaponSystem")),
    ("engines", "Engines", ("GetImpulseEngineSubsystem", "GetWarpEngineSubsystem")),
    ("sensors", "Sensor Array", ("GetSensorSubsystem",)),
    ("shields", "Shield Generator", ("GetShields",)),
)


class EngineeringPowerPanel(Panel):
    def __init__(self, get_player):
        super().__init__()
        self._get_player = get_player
        self._last_pushed = None

    @property
    def name(self) -> str:
        return "engpower"

    def _systems(self, player, getters):
        out = []
        for g in getters:
            getter = getattr(player, g, None)
            sys = getter() if getter else None
            if sys is not None:
                out.append(sys)
        return out

    def _snapshot(self):
        player = self._get_player()
        if player is None:
            return {"visible": False}
        power = player.GetPowerSubsystem()
        if power is None:
            return {"visible": False}
        sliders = []
        total_draw = 0.0
        for key, label, getters in _GROUPS:
            systems = self._systems(player, getters)
            pct = systems[0].GetPowerPercentageWanted() if systems else 0.0
            present = bool(systems)
            for s in systems:
                total_draw += s.GetNormalPowerWanted() * s.GetPowerPercentageWanted()
            sliders.append({"key": key, "label": label, "pct": round(pct, 4),
                            "present": present})
        bandwidth = power.GetMaxMainConduitCapacity() + power.GetBackupConduitCapacity()
        output = power.GetPowerOutput()
        main_cap = power.GetMainBatteryLimit()
        backup_cap = power.GetBackupBatteryLimit()
        tractor = player.GetTractorBeamSystem()
        cloak = player.GetCloakingSubsystem()
        tractor_active = bool(tractor is not None and tractor._wants_power())
        return {
            "visible": True,
            "power_used": {
                "fraction": round(min(total_draw / bandwidth, 1.0) if bandwidth > 0 else 0.0, 4),
                "bands": {
                    "blue": round(min(output / bandwidth, 1.0) if bandwidth > 0 else 0.0, 4),
                    "yellow": round(power.GetMainConduitCapacity() / bandwidth if bandwidth > 0 else 0.0, 4),
                    "red": round(power.GetBackupConduitCapacity() / bandwidth if bandwidth > 0 else 0.0, 4),
                },
            },
            "sliders": sliders,
            "columns": {
                "warp_core": round(power.GetConditionPercentage(), 4),
                "main": round(power.GetMainBatteryPower() / main_cap if main_cap > 0 else 0.0, 4),
                "backup": round(power.GetBackupBatteryPower() / backup_cap if backup_cap > 0 else 0.0, 4),
            },
            "tractor": {"present": tractor is not None, "active": tractor_active},
            "cloak": {"present": cloak is not None,
                      "active": bool(cloak is not None and cloak.IsTryingToCloak())},
        }

    def is_showing(self) -> bool:
        """True when the panel is rendering its grid (player + power present).

        The host loop gates CEF click-forwarding on this so clicks over the
        panel's top-right region reach the sliders instead of falling through
        to the game world. Mirrors crew_menu_panel.has_open_menu(). When it
        returns False the JS root has hidden itself, so there is nothing to
        click.
        """
        player = self._get_player()
        if player is None:
            return False
        return player.GetPowerSubsystem() is not None

    def render_payload(self):
        snap = self._snapshot()
        if snap == self._last_pushed:
            return None
        self._last_pushed = snap
        return "setEngineeringPower(" + json.dumps(snap) + ");"

    def dispatch_event(self, action: str) -> bool:
        parts = action.split(":")
        if len(parts) != 4 or parts[0] != "engpower" or parts[1] != "set":
            return False
        group, raw = parts[2], parts[3]
        player = self._get_player()
        if player is None:
            return True
        try:
            pct = float(raw)
        except ValueError:
            return True
        if group not in {key for key, _l, _g in _GROUPS}:
            return True   # groups only come from our own sliders; early-out keeps no-op events cheap
        for key, _label, getters in _GROUPS:
            if key == group:
                for sys in self._systems(player, getters):
                    sys.SetPowerPercentageWanted(pct)   # clamps internally
                break
        import App
        ctrl = App.EngPowerCtrl_GetPowerCtrl()
        if ctrl is not None:
            ctrl.Refresh()
        self._last_pushed = None
        return True
