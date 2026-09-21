"""The behaviour-bible harness: BC's measured contract, run against Dauntless.

Every test under tests/oracle/ encodes one assertion from §9 of
`../stbc-oracle/docs/bc-behaviour-bible.md` — numbers measured on the original
stbc.exe by an unattended oracle, each backed by a capture in that repo's
`docs/results/`.  A test's docstring names the assertion (B1, S2, M6 …) and
the capture file, and asserts with the bible's own tolerance.

The scenario geometry is the oracle's: a parked target (Galaxy unless stated)
at the origin facing +Y with its own weapons zeroed, the attacker parked
`range_gu` dead ahead facing −Y, both at red alert, no AI unless the test
attaches one, ONE thing commanded, then sampled every tick.

Assertions Dauntless does not yet meet are `xfail(strict=True)` with the
divergence in the reason, so the ledger is machine-checked: fixing one flips
exactly one xfail, and nothing can pass by accident.

Headless notes.  Ships have no realized hull here, so `SetRadius` is given the
bible's measured `GetRadius()` (Galaxy 4.366, Kessok Heavy 6.174) — without it
torpedoes never collide and collisions never trigger.  Hit points land on the
aim point, not a hull mesh, so subsystem FOOTPRINT (H2) is not testable here.
"""
import os

import pytest

from engine.core.loop import TICK_DELTA

# `GetRadius()` as the oracle read it off the running exe (bible §12.1a meta
# `player_radius` / `target radius`).  Others are estimates for collision only.
BIBLE_RADII_GU = {
    "Galaxy": 4.366,
    "KessokHeavy": 6.174,
    "Sovereign": 4.5,
    "BirdOfPrey": 2.0,
    "Warbird": 8.0,
}

TICKS_PER_SECOND = int(round(1.0 / TICK_DELTA))

# Bible index map (§5.1): 0 front, 1 rear, 2 top, 3 bottom, 4 port, 5 starboard.
FRONT, REAR, TOP, BOTTOM, PORT, STARBOARD = range(6)


def bible_xfail(assertion: str, bc: str, ours: str):
    """xfail(strict) marker naming the bible assertion and the measured gap."""
    return pytest.mark.xfail(
        strict=True,
        reason="bible %s: BC %s; Dauntless %s" % (assertion, bc, ours),
    )


class OracleScene:
    """One oracle scenario: two parked ships, the combat pumps, a sampler."""

    def __init__(self, attacker, target, range_gu, mission, episode):
        import App
        from engine.appc.ship_iter import iter_ships
        from engine.core.loop import GameLoop

        self.App = App
        self.mission = mission
        self.episode = episode
        self.range_gu = range_gu
        self.loop = GameLoop()
        self.atk = attacker
        self.tgt = target
        self._ships = list(iter_ships())
        self.t = 0.0

    # -- world stepping -----------------------------------------------------
    def step(self, ticks: int = 1) -> None:
        """Advance the sim exactly as host_loop orders it per frame: the game
        loop (AI, motion, subsystems), then weapons, combat, collisions."""
        from engine import host_loop
        from engine.appc import collisions

        for _ in range(ticks):
            self.loop.tick()
            host_loop._advance_weapons(self._ships, TICK_DELTA)
            host_loop._advance_combat(self._ships, TICK_DELTA)
            collisions.tick_collisions(TICK_DELTA)
            self.t += TICK_DELTA

    def run(self, seconds: float) -> None:
        self.step(int(round(seconds * TICKS_PER_SECOND)))

    # -- readouts -------------------------------------------------------------
    @property
    def hull(self):
        return self.tgt.GetHull()

    @property
    def shields(self):
        return self.tgt.GetShields()

    def hull_damage(self) -> float:
        return self.hull.GetMaxCondition() - self.hull.GetCondition()

    def face(self, i: int) -> float:
        return self.shields.GetCurShields(i)

    def face_max(self, i: int) -> float:
        return self.shields.GetMaxShields(i)

    def face_damage(self, i: int) -> float:
        return self.face_max(i) - self.face(i)

    def faces(self):
        return [self.face(i) for i in range(6)]

    def range_now(self) -> float:
        a = self.atk.GetWorldLocation()
        t = self.tgt.GetWorldLocation()
        return ((a.x - t.x) ** 2 + (a.y - t.y) ** 2 + (a.z - t.z) ** 2) ** 0.5

    @staticmethod
    def speed_of(ship) -> float:
        v = ship.GetVelocity()
        return (v.x * v.x + v.y * v.y + v.z * v.z) ** 0.5

    @staticmethod
    def turn_rate_of(ship) -> float:
        """|ω| from the motion integrator's own state (GetAngularVelocity does
        not reflect it — see the memory on the angular readout)."""
        w = getattr(ship, "_current_angular_velocity", None)
        if w is None:
            return 0.0
        return (w.x * w.x + w.y * w.y + w.z * w.z) ** 0.5

    def torpedoes_in_flight(self) -> int:
        from engine.appc import projectiles
        return len(projectiles._active)

    # -- the oracle's shield presets ---------------------------------------------
    def zero_shields(self) -> None:
        """The bible's `*_noshields` runs: every face at 0 (generator alive)."""
        for i in range(6):
            self.shields.SetCurShields(i, 0.0)

    def preset_face(self, i: int, fraction: float) -> None:
        self.shields.SetCurShields(i, self.face_max(i) * fraction)

    # -- the oracle's actions ---------------------------------------------------------
    def weapon_system(self, weapon: str):
        return {
            "phaser": self.atk.GetPhaserSystem,
            "pulse": self.atk.GetPulseWeaponSystem,
            "torpedo": self.atk.GetTorpedoSystem,
            "tractor": self.atk.GetTractorBeamSystem,
        }[weapon]()

    def emitters(self, weapon: str):
        ws = self.weapon_system(weapon)
        return [ws.GetWeapon(i) for i in range(ws.GetNumWeapons())]

    def fire(self, weapon: str, intensity=None, tractor_mode=None):
        """`OracleMission._act_weapon`: target by NAME, then StartFiring."""
        App = self.App
        ws = self.weapon_system(weapon)
        if weapon == "phaser" and intensity is not None:
            ws.SetPowerLevel(intensity)
        if weapon == "tractor":
            modes = {
                "hold": App.TractorBeamSystem.TBS_HOLD,
                "tow": App.TractorBeamSystem.TBS_TOW,
                "pull": App.TractorBeamSystem.TBS_PULL,
                "push": App.TractorBeamSystem.TBS_PUSH,
            }
            ws.SetMode(modes[tractor_mode or "hold"])
        self.atk.SetTarget(self.tgt.GetName())
        ws.StartFiring(self.tgt)
        return ws

    def full_impulse(self, ship=None, fraction: float = 1.0) -> None:
        App = self.App
        (ship or self.atk).SetImpulse(
            fraction, App.TGPoint3_GetModelForward(),
            App.PhysicsObjectClass.DIRECTION_MODEL_SPACE)

    def yaw_direct(self, rad_per_s: float, ship=None) -> None:
        v = self.App.TGPoint3()
        v.SetXYZ(0.0, 0.0, rad_per_s)
        (ship or self.atk).SetTargetAngularVelocityDirect(v)

    def attach_basic_attack(self, difficulty: float = 0.5) -> None:
        """The stock Quick Battle AI on the attacker, target weapons LIVE
        (bible §11: 'nobody at the controls')."""
        import importlib
        for g in ("GetPhaserSystem", "GetTorpedoSystem", "GetPulseWeaponSystem"):
            ws = getattr(self.tgt, g)()
            if ws is not None:
                ws.SetCondition(ws.GetMaxCondition())
        mod = importlib.import_module("AI.Compound.BasicAttack")
        ai = mod.CreateAI(self.atk, self.mission.GetEnemyGroup(),
                          Difficulty=difficulty)
        self.atk.SetAI(ai, 0, 0)

    # -- sampling helpers ----------------------------------------------------------------
    def sample_until(self, seconds: float, every_ticks: int = 1):
        """Yield (t, scene) after each `every_ticks` step for `seconds`."""
        n = int(round(seconds * TICKS_PER_SECOND))
        for i in range(0, n, every_ticks):
            self.step(every_ticks)
            yield self.t, self


@pytest.fixture
def oracle(monkeypatch):
    """Factory: `oracle(attacker="KessokHeavy", target="Galaxy", range_gu=57)`.

    Builds the oracle geometry inside a fresh Game/Episode/Mission on the
    QuickBattle region, settles one second (the oracle's spawn settle), and
    returns an OracleScene.  One scene per test — the SDK globals are reset
    by the root conftest's autouse leak guard between tests.
    """
    monkeypatch.setenv("OPEN_STBC_HOST_HEADLESS", "1")
    from tools import mission_harness
    mission_harness.setup_sdk()

    import App
    import loadspacehelper
    from engine.core.game import Game, Episode, Mission, _set_current_game

    built = []

    def _build(attacker="KessokHeavy", target="Galaxy", range_gu=57.0,
               settle_s=1.0):
        game, ep, mission = Game(), Episode(), Mission()
        ep.SetCurrentMission(mission)
        game.SetCurrentEpisode(ep)
        _set_current_game(game)
        App.Game_SetDifficultyMultipliers(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)

        import Systems.QuickBattle.QuickBattleRegion
        Systems.QuickBattle.QuickBattleRegion.Initialize()
        pSet = App.g_kSetManager.GetSet("QuickBattleRegion")

        tgt = loadspacehelper.CreateShip(target, pSet, "Target", "")
        atk = loadspacehelper.CreateShip(attacker, pSet, "Attacker", "")
        mission.GetEnemyGroup().AddName("Target")
        mission.GetFriendlyGroup().AddName("Attacker")

        def place(ship, x, y, z, fy):
            ship.SetTranslateXYZ(x, y, z)
            f = App.TGPoint3(); f.SetXYZ(0.0, fy, 0.0)
            u = App.TGPoint3(); u.SetXYZ(0.0, 0.0, 1.0)
            ship.AlignToVectors(f, u)
            ship.UpdateNodeOnly()

        place(tgt, 0.0, 0.0, 0.0, 1.0)
        place(atk, 0.0, range_gu, 0.0, -1.0)
        tgt.SetRadius(BIBLE_RADII_GU.get(target, 4.0))
        atk.SetRadius(BIBLE_RADII_GU.get(attacker, 4.0))
        for s in (tgt, atk):
            s.SetAlertLevel(App.ShipClass.RED_ALERT)
        # The oracle's `_zero_weapons(target)`: the target never shoots back.
        for g in ("GetPhaserSystem", "GetTorpedoSystem", "GetPulseWeaponSystem"):
            ws = getattr(tgt, g)()
            if ws is not None:
                ws.SetCondition(0.0)

        evt = App.TGEvent()
        evt.SetEventType(App.ET_MISSION_START)
        evt.SetDestination(ep)
        App.g_kEventManager.AddEvent(evt)

        scene = OracleScene(atk, tgt, range_gu, mission, ep)
        scene.run(settle_s)
        scene.t = 0.0
        built.append(scene)
        return scene

    yield _build

    from engine.appc import projectiles, hit_vfx
    projectiles._active.clear()
    hit_vfx._active.clear()
    _set_current_game(None)
