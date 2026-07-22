from engine.appc.character_status_map import StatusMap


def test_keys_0_to_5_store_and_read():
    sm = StatusMap(owner=None)
    sm.set_status("Waiting")            # default key 0
    sm.set_status("Red Alert", 1)
    assert sm.get_status(0) == "Waiting"
    assert sm.get_status(1) == "Red Alert"


def test_key_above_5_is_rejected():
    sm = StatusMap(owner=None)
    sm.set_status("nope", 6)
    assert sm.get_status(6) == 0          # BC: key>5 returns, nothing stored


def test_miss_returns_zero_sentinel():
    sm = StatusMap(owner=None)
    assert sm.get_status(3) == 0          # BC GetStatus miss -> 0


def test_clear_removes_one_row():
    sm = StatusMap(owner=None)
    sm.set_status("Destination : X", 3)
    sm.clear_status(3)
    assert sm.get_status(3) == 0


def test_rows_ascending_key_order():
    sm = StatusMap(owner=None)
    sm.set_status("loc", 2)
    sm.set_status("speed", 1)
    sm.set_status("general", 0)
    assert sm.rows() == [(0, "general"), (1, "speed"), (2, "loc")]


def test_dirty_flag_lifecycle():
    sm = StatusMap(owner=None)
    sm.clear_dirty()
    assert sm.is_dirty() is False
    sm.set_status("x", 0)
    assert sm.is_dirty() is True
