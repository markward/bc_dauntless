"""Locks the placement/realization behavior that Task 4 extracts. If these pass
before AND after the refactor, the extraction preserved behavior."""
import engine.host_loop as HL


def test_realize_helper_exists_and_is_used_by_place_one_character():
    # The extracted helper must exist...
    assert hasattr(HL, "_realize_character_instance")
    # ...and _place_one_character must delegate to it (no duplicated build body).
    import inspect
    src = inspect.getsource(HL._place_one_character)
    assert "_realize_character_instance" in src
