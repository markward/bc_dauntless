"""host_io.set_instance_node_transform: the node-matrix binding (spec §5)."""
from engine import host_io


def test_the_binding_is_in_the_facade_table():
    """A binding missing from the table is how features have shipped inert."""
    assert "set_instance_node_transform" in host_io._REQUIRED_BINDINGS


def test_headless_or_fake_iid_is_false_not_an_error(monkeypatch):
    monkeypatch.setattr(host_io, "_h", None)
    assert host_io.set_instance_node_transform(3, "left wing",
                                               (1.0,) + (0.0,) * 15) is False


def test_the_matrix_is_passed_as_sixteen_floats(monkeypatch):
    seen = []

    class _H:
        def set_instance_node_transform(self, iid, node, m16):
            seen.append((iid, node, tuple(m16)))
            return True

    monkeypatch.setattr(host_io, "_h", _H())
    m = tuple(float(i) for i in range(16))
    assert host_io.set_instance_node_transform(7, "left wing", m) is True
    assert seen == [(7, "left wing", m)]
