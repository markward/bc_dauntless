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

from engine.appc.subsystems import CloakingSubsystem


class _CapturedEvents:
    """Registers global broadcast handlers for the cloak completion events and
    records which ones fired (with their source), so a test can assert that a
    completion event was emitted exactly once via App.g_kEventManager."""

    def __init__(self):
        self.cloak = []
        self.decloak = []
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_CLOAK_COMPLETED, self, __name__ + "._on_cloak"
        )
        App.g_kEventManager.AddBroadcastPythonFuncHandler(
            App.ET_DECLOAK_COMPLETED, self, __name__ + "._on_decloak"
        )


def _on_cloak(handler, event):
    handler.cloak.append(event.GetSource())


def _on_decloak(handler, event):
    handler.decloak.append(event.GetSource())


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
