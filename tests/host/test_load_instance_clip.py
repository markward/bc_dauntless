"""Task 4: load_instance_clip — attach gesture/reaction clips to an officer at runtime."""
import os
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GAME = PROJECT_ROOT / "game"
BODY_NIF = GAME / "data/Models/Characters/Bodies/BodyMaleM/BodyMaleM.NIF"
HEAD_NIF = GAME / "data/Models/Characters/Heads/HeadPicard/Picard_head.NIF"
PLACEMENT_NIF = GAME / "data/animations/DB_stand_H_M.NIF"
GESTURE_NIF = GAME / "data/animations/react_console_left.NIF"
SHIP_NIF = GAME / "data/Models/Ships/Galaxy/Galaxy.nif"
SHIP_TEX = GAME / "data/Models/SharedTextures/FedShips/High"

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in [BODY_NIF, HEAD_NIF, PLACEMENT_NIF, GESTURE_NIF]),
    reason="needs game/ assets",
)


def test_load_instance_clip_returns_new_index():
    """load_instance_clip appends gesture clips to the officer's per-instance model
    and returns the first new clip index (>= 1, because index 0 is the placement clip
    baked at assemble_officer time)."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, "test-load-instance-clip")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    try:
        h = _dauntless_host.assemble_officer(
            str(BODY_NIF), str(HEAD_NIF), None, None, str(PLACEMENT_NIF), False
        )
        assert h > 0
        iid = _dauntless_host.create_bridge_instance(h)

        idx = _dauntless_host.load_instance_clip(iid, str(GESTURE_NIF))
        assert idx >= 1, f"expected idx >= 1 (placement clip is 0), got {idx}"
    finally:
        _dauntless_host.shutdown()


def test_load_instance_clip_idempotent():
    """Calling load_instance_clip twice with the same path returns the same index
    and does NOT append the clips a second time (no unbounded growth)."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, "test-load-instance-clip-idem")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    try:
        h = _dauntless_host.assemble_officer(
            str(BODY_NIF), str(HEAD_NIF), None, None, str(PLACEMENT_NIF), False
        )
        iid = _dauntless_host.create_bridge_instance(h)

        idx = _dauntless_host.load_instance_clip(iid, str(GESTURE_NIF))
        idx2 = _dauntless_host.load_instance_clip(iid, str(GESTURE_NIF))
        assert idx2 == idx, (
            f"idempotency broken: first call returned {idx}, second returned {idx2}"
        )
    finally:
        _dauntless_host.shutdown()


@pytest.mark.skipif(
    not (SHIP_NIF.exists() and SHIP_TEX.exists() and GESTURE_NIF.exists()),
    reason="needs game/ ship assets",
)
def test_load_instance_clip_returns_minus1_for_non_officer():
    """load_instance_clip must return -1 for non-officer (cache-loaded) models.
    Cache models are genuinely const; const_cast on them is UB, so the is_officer
    guard must fire before any mutation is attempted."""
    os.environ["OPEN_STBC_HOST_HEADLESS"] = "1"
    import _dauntless_host
    try:
        _dauntless_host.init(640, 480, "test-load-instance-clip-nonofficer")
    except RuntimeError as e:
        pytest.skip(f"no GL context available: {e}")
    try:
        h = _dauntless_host.load_model(str(SHIP_NIF), str(SHIP_TEX))
        assert h > 0
        iid = _dauntless_host.create_instance(h)
        result = _dauntless_host.load_instance_clip(iid, str(GESTURE_NIF))
        assert result == -1, (
            f"expected -1 for non-officer model, got {result} "
            "(const_cast on a cache model is undefined behaviour)"
        )
    finally:
        _dauntless_host.shutdown()
