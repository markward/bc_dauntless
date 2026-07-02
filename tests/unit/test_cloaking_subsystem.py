"""CloakingSubsystem state machine (W5.T1) — logic only, no renderer VFX.

The SDK CloakShip preprocessor (sdk/Build/scripts/AI/Preprocessors.py:2068,
method CheckCloak) drives a ship's cloak purely through the cloaking
subsystem's method surface:

    pCloak = pOurShip.GetCloakingSubsystem()
    if pCloak:
        if self.bCloakOn:
            if (not pCloak.IsCloaked()) and (not pCloak.IsCloaking()):
                pCloak.StartCloaking()
        else:
            if pCloak.IsCloaked():
                pCloak.StopCloaking()

These tests pin the four-state machine (DECLOAKED / CLOAKING / CLOAKED /
DECLOAKING), the transition timer advanced from the per-tick Update(dt), and
the ET_CLOAK_COMPLETED / ET_DECLOAK_COMPLETED completion events.
"""
import App

from engine.appc.subsystems import CloakingSubsystem, PowerSubsystem


class _CapturedEvents:
    """Registers global broadcast handlers for the cloak BEGINNING and COMPLETED
    events and records which ones fired (with their source), so a test can assert
    that each was emitted exactly once via App.g_kEventManager.  BC fires the
    BEGINNING event at transition start and the COMPLETED event at the end."""

    def __init__(self):
        self.cloak = []
        self.decloak = []
        self.cloak_begin = []
        self.decloak_begin = []
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_CLOAK_COMPLETED, self, __name__ + "._on_cloak"
        )
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_DECLOAK_COMPLETED, self, __name__ + "._on_decloak"
        )
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_CLOAK_BEGINNING, self, __name__ + "._on_cloak_begin"
        )
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_DECLOAK_BEGINNING, self, __name__ + "._on_decloak_begin"
        )


def _on_cloak(handler, event):
    handler.cloak.append(event.GetSource())


def _on_decloak(handler, event):
    handler.decloak.append(event.GetSource())


def _on_cloak_begin(handler, event):
    handler.cloak_begin.append(event.GetSource())


def _on_decloak_begin(handler, event):
    handler.decloak_begin.append(event.GetSource())


def _make_capture():
    return _CapturedEvents()


# ── Initial state ─────────────────────────────────────────────────────────────

def test_initial_state_is_decloaked():
    cloak = CloakingSubsystem("Cloak")
    assert cloak.IsCloaked() == 0
    assert cloak.IsCloaking() == 0
    assert cloak.IsDecloaking() == 0
    assert cloak.IsTryingToCloak() == 0


# ── StartCloaking → CLOAKING → (timer) → CLOAKED ──────────────────────────────

def test_start_cloaking_enters_transition():
    cloak = CloakingSubsystem("Cloak")
    cloak.StartCloaking()
    assert cloak.IsCloaking() == 1
    assert cloak.IsCloaked() == 0
    assert cloak.IsTryingToCloak() == 1


def test_cloaking_completes_after_duration_and_fires_event_once():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    cloak.StartCloaking()
    # Advance just short of the duration: still in transition.
    cloak.Update(cloak._transition_duration - 0.01)
    assert cloak.IsCloaking() == 1
    assert cloak.IsCloaked() == 0
    assert cap.cloak == []
    # Advance past the duration: now cloaked, event fired once.
    cloak.Update(0.02)
    assert cloak.IsCloaked() == 1
    assert cloak.IsCloaking() == 0
    assert len(cap.cloak) == 1
    assert cap.cloak[0] is cloak
    # Further ticks do not re-fire.
    cloak.Update(1.0)
    assert len(cap.cloak) == 1


# ── StopCloaking from CLOAKED → DECLOAKING → DECLOAKED ────────────────────────

def test_stop_cloaking_from_cloaked_decloaks_after_duration():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()
    assert cloak.IsCloaked() == 1
    cloak.StopCloaking()
    assert cloak.IsDecloaking() == 1
    assert cloak.IsCloaked() == 0
    assert cloak.IsTryingToCloak() == 0
    cloak.Update(cloak._transition_duration + 0.01)
    assert cloak.IsCloaked() == 0
    assert cloak.IsDecloaking() == 0
    assert len(cap.decloak) == 1
    assert cap.decloak[0] is cloak


# ── Instant transitions ───────────────────────────────────────────────────────

def test_instant_cloak_jumps_and_fires_completion():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()
    assert cloak.IsCloaked() == 1
    assert cloak.IsCloaking() == 0
    assert len(cap.cloak) == 1


def test_instant_decloak_jumps_and_fires_completion():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()
    cloak.InstantDecloak()
    assert cloak.IsCloaked() == 0
    assert cloak.IsDecloaking() == 0
    assert len(cap.decloak) == 1


# ── No-op idempotency ─────────────────────────────────────────────────────────

def test_start_cloaking_is_noop_when_already_cloaked():
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()
    cloak.StartCloaking()   # already cloaked — must not re-enter CLOAKING
    assert cloak.IsCloaked() == 1
    assert cloak.IsCloaking() == 0


def test_start_cloaking_is_noop_when_already_cloaking():
    cloak = CloakingSubsystem("Cloak")
    cloak.StartCloaking()
    cloak.Update(cloak._transition_duration * 0.5)
    cloak.StartCloaking()   # second call must not reset the transition
    # Finishing the remaining half should complete the (un-reset) cloak.
    cloak.Update(cloak._transition_duration * 0.5 + 0.01)
    assert cloak.IsCloaked() == 1


def test_stop_cloaking_is_noop_when_decloaked():
    cloak = CloakingSubsystem("Cloak")
    cloak.StopCloaking()    # already decloaked — no-op
    assert cloak.IsDecloaking() == 0
    assert cloak.IsCloaked() == 0


# ── Disabled subsystem cannot stay cloaked ────────────────────────────────────

def test_disabled_subsystem_does_not_complete_cloak_and_forces_decloak():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    # Give it condition so IsDisabled() is meaningful, then start a cloak.
    cloak.SetMaxCondition(100.0)
    cloak.StartCloaking()
    assert cloak.IsCloaking() == 1
    # Disable it (condition at/below the disabled threshold).
    cloak.SetCondition(0.0)
    assert cloak.IsDisabled() == 1
    # The pending cloak must not complete; instead it is forced toward decloak.
    cloak.Update(cloak._transition_duration + 0.01)
    assert cloak.IsCloaked() == 0
    assert cap.cloak == []


# ── BEGINNING events fire at transition start (BC: PowerDisplay / E2 missions) ──

def test_start_cloaking_fires_beginning_once():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    cloak.StartCloaking()
    assert len(cap.cloak_begin) == 1
    assert cap.cloak_begin[0] is cloak
    # Still mid-transition: no COMPLETED yet, and BEGINNING does not re-fire.
    cloak.Update(cloak._transition_duration * 0.5)
    assert len(cap.cloak_begin) == 1
    assert cap.cloak == []


def test_stop_cloaking_fires_decloak_beginning_once():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()
    cloak.StopCloaking()
    assert len(cap.decloak_begin) == 1
    assert cap.decloak_begin[0] is cloak


def test_noop_start_does_not_fire_beginning():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()            # already CLOAKED
    cloak.StartCloaking()          # no-op
    assert cap.cloak_begin == []
    # Re-calling StartCloaking mid-CLOAKING must not re-fire BEGINNING either.
    cloak2 = CloakingSubsystem("Cloak")
    cap2 = _make_capture()
    cloak2.StartCloaking()
    cloak2.StartCloaking()
    assert len(cap2.cloak_begin) == 1


def test_instant_transitions_fire_no_beginning():
    cap = _make_capture()
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()
    cloak.InstantDecloak()
    # Instant jumps have no transition to "begin" — only COMPLETED events.
    assert cap.cloak_begin == []
    assert cap.decloak_begin == []
    assert len(cap.cloak) == 1
    assert len(cap.decloak) == 1


# ── Cloak power drain — only while trying-to-cloak ────────────────────────────

class _StubShip:
    """Minimal ship exposing only GetCloakingSubsystem, so PowerSubsystem's
    _compute_idle_drain walks the cloak branch (the other _IDLE_DRAIN_SLOTS
    getters are absent and skipped via getattr default)."""

    def __init__(self, cloak):
        self._cloak = cloak

    def GetCloakingSubsystem(self):
        return self._cloak


def test_cloak_drains_power_only_while_trying_to_cloak():
    cloak = CloakingSubsystem("Cloak")
    cloak.SetNormalPowerPerSecond(1000.0)   # warbird authors 1000 power/sec
    power = PowerSubsystem("Power")
    power.SetParentShip(_StubShip(cloak))

    # Decloaked: cloak draws nothing.
    assert power._compute_idle_drain() == 0.0
    # CLOAKING (fading out) — trying to cloak, so it draws.
    cloak.StartCloaking()
    assert power._compute_idle_drain() == 1000.0
    # CLOAKED — still engaged, still draws.
    cloak.InstantCloak()
    assert power._compute_idle_drain() == 1000.0
    # DECLOAKING (fading back in) — no longer trying, drain stops.
    cloak.StopCloaking()
    assert power._compute_idle_drain() == 0.0


# ── Cloak transition SFX ──────────────────────────────────────────────────────

class _FakeSound:
    def __init__(self):
        self.plays = []

    def Play(self, attach_node=0, position=None):
        self.plays.append(position)


class _FakeSoundManager:
    """Records GetSound lookups and hands back a fake sound per name."""

    def __init__(self):
        self.requested = []
        self.sounds = {"Cloak": _FakeSound(), "Uncloak": _FakeSound()}

    def GetSound(self, name):
        self.requested.append(name)
        return self.sounds.get(name)


def _install_fake_sound_manager(monkeypatch):
    mgr = _FakeSoundManager()
    monkeypatch.setattr(App, "g_kSoundManager", mgr, raising=False)
    return mgr


def test_start_cloaking_plays_cloak_sfx(monkeypatch):
    mgr = _install_fake_sound_manager(monkeypatch)
    cloak = CloakingSubsystem("Cloak")
    cloak.StartCloaking()
    assert "Cloak" in mgr.requested
    assert len(mgr.sounds["Cloak"].plays) == 1


def test_stop_cloaking_plays_uncloak_sfx(monkeypatch):
    mgr = _install_fake_sound_manager(monkeypatch)
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()                     # jump to cloaked (silent)
    cloak.StopCloaking()                     # the transition that should sound
    assert "Uncloak" in mgr.requested
    assert len(mgr.sounds["Uncloak"].plays) == 1


def test_instant_transitions_are_silent(monkeypatch):
    mgr = _install_fake_sound_manager(monkeypatch)
    cloak = CloakingSubsystem("Cloak")
    cloak.InstantCloak()
    cloak.InstantDecloak()
    # No transition sweep played for the instant (no-transition) jumps.
    assert mgr.requested == []
