"""AT_* ammo-type constants on the App shim."""
import App


def test_at_one_is_int():
    assert isinstance(App.AT_ONE, int)


def test_at_constants_are_distinct():
    constants = [App.AT_ONE, App.AT_TWO, App.AT_THREE, App.AT_FOUR, App.AT_FIVE]
    assert len(set(constants)) == 5, f"AT_* constants must be distinct: {constants}"


def test_at_one_equals_at_one():
    # Sanity: same constant referenced twice compares equal.
    assert App.AT_ONE == App.AT_ONE
    # And differs from AT_TWO.
    assert App.AT_ONE != App.AT_TWO
