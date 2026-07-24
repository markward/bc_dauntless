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
