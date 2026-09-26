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
        # Codebase precedent for a fake `_h` whose isinstance guard must
        # accept a plain int (tests/unit/test_event_manager_method_handler.py
        # ~line 148 does the same for `sys.modules["_dauntless_host"]`):
        # the real module's InstanceId is a distinct wrapped type, but a
        # fake standing in for it can alias `int` so a plain-int test iid
        # still exercises the success path through the isinstance guard
        # that `set_instance_transform_slot` also has.
        InstanceId = int

        def set_instance_node_transform(self, iid, node, m16):
            seen.append((iid, node, tuple(m16)))
            return True

    monkeypatch.setattr(host_io, "_h", _H())
    m = tuple(float(i) for i in range(16))
    assert host_io.set_instance_node_transform(7, "left wing", m) is True
    assert seen == [(7, "left wing", m)]


def test_a_non_instance_id_iid_is_false_not_a_typeerror(monkeypatch):
    """A real-module-shaped fake: InstanceId is a DISTINCT type from int, as
    it is in the actual _dauntless_host module. A plain-int iid (e.g. a test
    double's placeholder) must degrade to False here, not raise -- mirroring
    set_instance_transform_slot's isinstance guard exactly. This is the guard
    a stale wrapper without it would skip, raising TypeError from the native
    binding instead."""
    class _RealInstanceId:
        pass

    class _H:
        InstanceId = _RealInstanceId

        def set_instance_node_transform(self, iid, node, m16):
            raise AssertionError("must not reach the native call")

    monkeypatch.setattr(host_io, "_h", _H())
    assert host_io.set_instance_node_transform(
        7, "left wing", (1.0,) + (0.0,) * 15) is False
