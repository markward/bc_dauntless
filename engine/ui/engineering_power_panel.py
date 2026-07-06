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
    ("shields", "Shields", ("GetShields",)),
)


def _set_power_to_subsystem(sys, pct):
    """Apply the BC canonical SetPowerToSubsystem semantics to one subsystem.

    Mirrors sdk/Build/scripts/Bridge/EngineerMenuHandlers.py:442-452:
      1. SetPowerPercentageWanted(pct)           — also fires ET_SUBSYSTEM_POWER_CHANGED
      2. TurnOn() if IsOn()==0 and pct > 0.0    — re-enable when raising from 0
      3. TurnOff() if pct == 0.0                — disable when dragging to zero

    Prefers the SDK module directly when importable (live runtime, host tests).
    Falls back to an inline replica that is byte-equivalent in behaviour for
    plain unit-test contexts where the SDK finder may not have been initialised.
    NOTE: SetPowerPercentageWanted already posts ET_SUBSYSTEM_POWER_CHANGED; the
    SDK path posts a second TGFloatEvent with the float value — harmless duplicate.
    """
    try:
        import Bridge.EngineerMenuHandlers as _EMH
        _EMH.SetPowerToSubsystem(sys, pct)
    except (ImportError, AttributeError):
        # Inline replica of EngineerMenuHandlers.py:442-452
        sys.SetPowerPercentageWanted(pct)
        if not sys.IsOn() and pct > 0.0:
            sys.TurnOn()
        if pct == 0.0:
            sys.TurnOff()


class EngineeringPowerPanel(Panel):
    def __init__(self, get_player, is_engineering_open=None):
        super().__init__()
        self._get_player = get_player
        # Callable[[], bool] — True when the Engineering crew menu is the open
        # top-level station menu.  When None the panel always hides (the host
        # loop passes a live crew_menu_panel check; None is the safe fallback
        # when the panel is constructed without the crew-menu context, e.g. in
        # unit tests that only exercise dispatch/slider logic).
        self._is_engineering_open = is_engineering_open
        self._last_pushed = None
        # Battery trend tracking (v2): persist direction across snapshots so
        # draining=True persists until the value reverses.
        self._batt_prev = {}
        self._batt_dir = {"main": False, "reserve": False}

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
        if not self._engineering_is_open():
            return {"visible": False}

        # ── Sliders ───────────────────────────────────────────────────────────
        sliders = []
        for key, label, getters in _GROUPS:
            systems = self._systems(player, getters)
            pct = systems[0].GetPowerPercentageWanted() if systems else 0.0
            present = bool(systems)
            sliders.append({"key": key, "label": label, "pct": round(pct, 4),
                            "present": present})

        # ── Grid fractions (v2) ───────────────────────────────────────────────
        # Shared denominator D = authored_output + main_conduit_cap + backup_conduit_cap
        prop = power.GetProperty()
        authored_out = float(prop.GetPowerOutput() or 0.0) if prop is not None else 0.0
        main_cond = float(prop.GetMainConduitCapacity() or 0.0) if prop is not None else 0.0
        back_cond = float(prop.GetBackupConduitCapacity() or 0.0) if prop is not None else 0.0
        denom = authored_out + main_cond + back_cond

        live_out = float(power.GetPowerOutput() or 0.0)   # health-scaled

        # Damage column: fraction of denom lost to damage
        damage = round((authored_out - live_out) / denom, 4) if denom > 0 else 0.0

        # Battery charge fractions
        main_limit = power.GetMainBatteryLimit()
        res_limit = power.GetBackupBatteryLimit()
        main_batt = power.GetMainBatteryPower()
        res_batt = power.GetBackupBatteryPower()
        main_frac = main_batt / main_limit if main_limit > 0 else 0.0
        res_frac = res_batt / res_limit if res_limit > 0 else 0.0

        available = {
            "warp_core": round(live_out / denom, 4) if denom > 0 else 0.0,
            "main": round(main_cond * main_frac / denom, 4) if denom > 0 else 0.0,
            "reserve": round(back_cond * res_frac / denom, 4) if denom > 0 else 0.0,
        }

        # Used segments per group: Σ(normal × pct) / D
        used = []
        for key, _label, getters in _GROUPS:
            demand = sum(
                s.GetNormalPowerWanted() * s.GetPowerPercentageWanted()
                for s in self._systems(player, getters)
            )
            used.append({"key": key, "frac": demand / denom if denom > 0 else 0.0})

        # Overload: clamp used to available, set flag
        # summed from 4dp-rounded segments — borderline used==avail can flag overload spuriously by <=3e-4; harmless for real ship data
        avail_total = sum(available.values())
        used_total = sum(u["frac"] for u in used)
        overload = used_total > avail_total > 0.0
        if overload:
            scale = avail_total / used_total
            for u in used:
                u["frac"] *= scale
        for u in used:
            u["frac"] = round(u["frac"], 4)

        # ── Battery trend ─────────────────────────────────────────────────────
        for batt_key, new_val in (("main", main_batt), ("reserve", res_batt)):
            prev = self._batt_prev.get(batt_key)
            if prev is not None and new_val != prev:
                self._batt_dir[batt_key] = (new_val < prev)
            self._batt_prev[batt_key] = new_val

        batteries = {
            "main":    {"charge": round(main_frac, 4), "draining": self._batt_dir["main"]},
            "reserve": {"charge": round(res_frac, 4),  "draining": self._batt_dir["reserve"]},
        }

        # ── Tractor / cloak presence ──────────────────────────────────────────
        tractor = player.GetTractorBeamSystem()
        cloak = player.GetCloakingSubsystem()
        tractor_present = tractor is not None and tractor.GetNumWeapons() > 0
        tractor_active = bool(tractor is not None and tractor._wants_power())

        return {
            "visible": True,
            "sliders": sliders,
            "grid": {
                "damage": damage,
                "available": available,
                "used": used,
                "overload": overload,
            },
            "batteries": batteries,
            "tractor": {"present": tractor_present, "active": tractor_active},
            "cloak": {"present": cloak is not None,
                      "active": bool(cloak is not None and cloak.IsTryingToCloak())},
        }

    def _engineering_is_open(self) -> bool:
        """True when the Engineering crew menu is the currently open station menu.

        Delegates to the injected ``is_engineering_open`` callable when one was
        provided; otherwise returns False (safe default — no crew-menu context
        means the panel must stay hidden).
        """
        if self._is_engineering_open is None:
            return False
        return bool(self._is_engineering_open())

    def is_showing(self) -> bool:
        """True when the panel is rendering its grid: player present, power
        present, AND the Engineering crew menu is the currently open station menu.

        The host loop gates CEF click-forwarding on this so clicks over the
        panel's top-right region reach the sliders instead of falling through
        to the game world. Mirrors crew_menu_panel.has_open_menu(). When it
        returns False the JS root has hidden itself, so there is nothing to
        click.
        """
        if not self._engineering_is_open():
            return False
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
        # PanelRegistry routes "engpower/<action>" here with the "engpower/"
        # prefix already stripped, so ``action`` is "set:<group>:<value>" or
        # "toggle:tractor" / "toggle:cloak".

        # Handle tractor/cloak toggles
        if action in ("toggle:tractor", "toggle:cloak"):
            player = self._get_player()
            if player is not None:
                from engine.appc import weapon_config
                if action == "toggle:tractor":
                    weapon_config.toggle_tractor(player)
                else:
                    weapon_config.toggle_cloak(player)
                self._last_pushed = None
            return True

        # Handle slider events (set:group:pct)
        parts = action.split(":")
        if len(parts) != 3 or parts[0] != "set":
            return False
        group, raw = parts[1], parts[2]
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
                    _set_power_to_subsystem(sys, pct)
                break
        import App
        ctrl = App.EngPowerCtrl_GetPowerCtrl()
        if ctrl is not None:
            ctrl.Refresh()
        self._last_pushed = None
        return True
