"""Crew 'raise shields' prompts on entering asteroids or radiation.

Dauntless-authored dialogue (no BC original): when the player's ship is in
asteroids (radial-profile `asteroids` or a rock field's strength above 0.05)
or radiation (any profile `radiation` above 0 -- where radiation.py starts
doing damage) with its shields down, an
officer recommends raising them. Lines live in our own TGL, generated from
tools/dialogue/dauntless_crew.json by tools/gen_dauntless_tgl.py, and are
spoken through the officer's SpeakLine like any SDK line.

Skipped in E3M2 and E3M4, whose scripts already prompt for shields
(E3M2ProdRaiseShields, E3M4ShouldRaiseShields), during a cinematic, and while
warping or dashing. One prompt per exposure: it re-arms once the level
falls to half its threshold or below (radiation: back to 0) or the shields
go up, and never sooner than
COOLDOWN_S after the last prompt for that hazard.

Never spoken over dialogue (Mark, 2026-10-07): if a scripted sequence still
has a line to come, or any crew line ended less than QUIET_S ago, the prompt
is DROPPED for this exposure -- not deferred. A line started in a gap of a
mission conversation was cut off by the conversation's next line.

Polled at POLL_S from host_loop on game time; reset on mission swap.
"""
from __future__ import annotations

import random

import engine.dev_mode as dev_mode

DATABASE = "data/TGL/Dauntless Crew.tgl"

POLL_S = 1.0
COOLDOWN_S = 120.0
QUIET_S = 5.0

# hazard -> (threshold, [(bridge-set object name, line key), ...]).
# Object names are the stations (engine/bridge_officers.py): Brex is the
# Engineer, Miguel is Science.
# Radiation warns at the first damage: radiation.py drains at any level
# above 0, and at 0.1 a ship crossing the linear ramp toward a star took
# 1,600-2,800 GU (4-7 min at full impulse) of damage before Brex spoke.
THRESHOLDS = {"radiation": 0.0, "asteroids": 0.05}
HAZARDS = {
    "radiation": [("Engineer", "BrexRadiationShields1"),
                  ("Engineer", "BrexRadiationShields2")],
    "asteroids": [("Engineer", "BrexAsteroidShields1"),
                  ("Science", "MiguelAsteroidShields2")],
}

# Last component of the mission module; these script their own shield prompt.
SKIP_MISSIONS = frozenset({"E3M2", "E3M4"})


class HazardLatch:
    """When one hazard's prompt is due. `due` observes; `fire` commits, so a
    prompt with no one to speak it stays pending; `drop` gives up on it for
    this exposure without starting the cooldown."""

    def __init__(self, threshold: float, cooldown_s: float = COOLDOWN_S):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._prompted = False
        self._last = None

    def due(self, level, shields_up, blocked, now) -> bool:
        # <=, so a zero threshold re-arms once the ship is fully out.
        if level <= self.threshold * 0.5 or shields_up:
            self._prompted = False
        return (level > self.threshold and not shields_up and not blocked
                and not self._prompted
                and (self._last is None or now - self._last >= self.cooldown_s))

    def fire(self, now) -> None:
        self._prompted = True
        self._last = now

    def drop(self) -> None:
        self._prompted = True

    def step(self, level, shields_up, blocked, now) -> bool:
        if self.due(level, shields_up, blocked, now):
            self.fire(now)
            return True
        return False


class CrewHazardPrompts:
    def __init__(self, rng=None):
        self._rng = rng if rng is not None else random.Random()
        self.reset()

    def reset(self) -> None:
        self._latches = {h: HazardLatch(t) for h, t in THRESHOLDS.items()}
        self._next_poll = None

    def update(self, player, now) -> None:
        if player is None:
            return
        if self._next_poll is not None and now < self._next_poll:
            return
        self._next_poll = now + POLL_S
        asteroids, radiation = _levels(player)
        shields_up = _shields_up(player)
        blocked = (_mission_name().rsplit(".", 1)[-1] in SKIP_MISSIONS
                   or _cinematic() or _travelling(player))
        for hazard, level in (("radiation", radiation), ("asteroids", asteroids)):
            latch = self._latches[hazard]
            if not latch.due(level, shields_up, blocked, now):
                continue
            if _dialogue_active():
                latch.drop()
                continue
            if self._speak(hazard):
                latch.fire(now)
                return   # one line per poll

    def _speak(self, hazard) -> bool:
        from engine.appc.ai import CSP_SPONTANEOUS
        options = HAZARDS[hazard]
        for station, key in self._rng.sample(options, len(options)):
            officer = _officer(station)
            if officer is not None:
                officer.SpeakLine(_database(), key, CSP_SPONTANEOUS)
                return True
        return False


# ── Engine probes (module-level so tests can monkeypatch them) ──────────────

def _levels(player):
    """(asteroids, radiation) at the player."""
    from engine.rocks import far_tier
    from engine.systems import profile
    s = profile.sample_for_object(player)
    return max(s.asteroids, far_tier.field_strength_at(player)), s.radiation


def _shields_up(player) -> bool:
    from engine.appc.nebula_runtime import _shields_up as shields
    return shields(player) is not None


def _mission_name() -> str:
    try:
        import MissionLib
        return getattr(MissionLib.GetMission(), "_module_name", "") or ""
    except Exception as exc:
        dev_mode.log_swallowed("crew_hazard_prompts mission name", exc)
        return ""


def _cinematic() -> bool:
    try:
        import App
        return bool(App.TopWindow_GetTopWindow().is_cinematic_active())
    except Exception as exc:
        dev_mode.log_swallowed("crew_hazard_prompts cinematic", exc)
        return False


def _travelling(player) -> bool:
    from engine.appc import dash, warp_state
    return bool(warp_state.is_ship_warping(player) or dash.is_dashing(player))


def _dialogue_active() -> bool:
    """A scripted line still to come, or crew speech within QUIET_S."""
    from engine.appc import actions, crew_speech
    return bool(actions.scripted_line_pending()
                or crew_speech.silent_for() < QUIET_S)


def _officer(station):
    """The station's character, or None. Strict: CharacterClass_GetObject
    vivifies a blank character when the bridge set isn't real."""
    import App
    from engine.appc.characters import CharacterClass_GetObjectStrict
    return CharacterClass_GetObjectStrict(App.g_kSetManager.GetSet("bridge"), station)


_db = None


def _database():
    global _db
    if _db is None:
        import App
        _db = App.g_kLocalizationManager.Load(DATABASE)
    return _db
