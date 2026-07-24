from collections import OrderedDict
import engine.appc.hardpoint_override_writer as w


def test_render_then_parse_round_trips():
    m = OrderedDict([("Port Impulse", "Left Impulse"),
                     ("Star Impulse", "Right Impulse")])
    block = w.render_managed_block(m)
    # Delimited and indented as a function body.
    assert block.startswith(w.BLOCK_START)
    assert block.rstrip().endswith(w.BLOCK_END)
    assert '    p = find("Port Impulse")' in block
    assert '        p.SetName("Left Impulse")' in block
    # Wrapped in unrelated indented lines, parse recovers exactly the mapping.
    wrapped = '    # glow above\n' + block + '\n    # more below\n'
    assert w.parse_managed_block(wrapped) == m


def test_names_with_quotes_are_escaped_and_recovered():
    m = OrderedDict([('A "special" name', 'B\\C')])
    block = w.render_managed_block(m)
    assert w.parse_managed_block(block) == m


import ast
import pytest

_BASE = '''\
def apply(leaf):
    pass


def _galaxy(find):
    p = find("Sensor Array")
    if p is not None:
        p.SetGlowRegionRadius(0, 0.28)


OVERRIDES = {
    "galaxy": _galaxy,
}
'''


def _get_overrides(module_text):
    ns = {}
    exec(compile(module_text, "<test>", "exec"), ns)  # noqa: S102
    return ns


def test_rename_extends_existing_function_and_preserves_hand_code():
    out = w.apply_renames(_BASE, "galaxy", [("Port Impulse", "Left Impulse")])
    # Hand-authored glow line untouched.
    assert 'p.SetGlowRegionRadius(0, 0.28)' in out
    # Managed block present with the rename.
    assert w.parse_managed_block(out) == {"Port Impulse": "Left Impulse"}
    # Still valid Python.
    ast.parse(out)


def test_re_rename_updates_same_entry_keyed_by_original():
    once = w.apply_renames(_BASE, "galaxy", [("Port Impulse", "Left Impulse")])
    # The loaded name is now "Left Impulse"; renaming again must update, not add.
    twice = w.apply_renames(once, "galaxy", [("Left Impulse", "Backup Impulse")])
    assert w.parse_managed_block(twice) == {"Port Impulse": "Backup Impulse"}


def test_second_subsystem_adds_a_group():
    once = w.apply_renames(_BASE, "galaxy", [("Port Impulse", "Left Impulse")])
    twice = w.apply_renames(once, "galaxy", [("Star Impulse", "Right Impulse")])
    assert w.parse_managed_block(twice) == {
        "Port Impulse": "Left Impulse",
        "Star Impulse": "Right Impulse",
    }


def test_rename_back_to_original_removes_entry():
    once = w.apply_renames(_BASE, "galaxy", [("Port Impulse", "Left Impulse")])
    back = w.apply_renames(once, "galaxy", [("Left Impulse", "Port Impulse")])
    assert w.parse_managed_block(back) == {}


def test_creates_function_and_overrides_entry_when_absent():
    out = w.apply_renames(_BASE, "akira", [("Bridge", "Command Deck")])
    ns = _get_overrides(out)
    assert "akira" in ns["OVERRIDES"]
    assert w.parse_managed_block(out) == {"Bridge": "Command Deck"}
    ast.parse(out)


def test_malformed_result_raises_without_returning_text():
    with pytest.raises(ValueError):
        w.apply_renames("this is ( not python", "galaxy",
                        [("A", "B")])
