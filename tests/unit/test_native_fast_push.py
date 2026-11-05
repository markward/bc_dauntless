"""One-call scalar mirror push (native weapon state, Task 2; spec
docs/superpowers/specs/2026-11-02-native-weapon-state-design.md §4.2).

A scalar NativeField (float, int, bool, IS_TRUE, OPT_INT) pushes through
one binding, combat_push_scalar, which encodes in C++. NativeField._encode /
_push stay the reference: every input must land the same mirror value
(floats bit for bit), or drop the row where _encode raises TypeError /
ValueError / OverflowError, or propagate any other exception unchanged.
"""
import decimal
import fractions
import struct

import pytest

try:
    import _dauntless_host as _h
except ImportError:
    _h = None

pytestmark = pytest.mark.skipif(
    _h is None or not hasattr(_h, "combat_register"),
    reason="native combat bindings not built")

from engine.appc import native_combat as nc  # noqa: E402
from engine.appc import passive_state  # noqa: E402

ON = {"DAUNTLESS_NATIVE_COMBAT": "1"}
_INT64 = (-(1 << 63), (1 << 63) - 1)


@pytest.fixture(autouse=True)
def _switch():
    nc.reset()
    passive_state.reset()
    yield
    for h in _ROWS:
        try:
            _h.combat_unregister(h)
        except ValueError:
            pass
    _ROWS.clear()
    nc.reset()
    passive_state.reset()


_ROWS: list = []


class Probe:
    """One scalar NativeField per push code, keyed onto real Subsystem
    mirror fields of the right storage type."""

    _f = nc.NativeField(float, key="_condition")
    _i = nc.NativeField(int, key="_cloak_state")
    _b = nc.NativeField(bool, key="_destroyed")
    _t = nc.NativeField(nc.IS_TRUE, key="_radiation_out")
    _o = nc.NativeField(nc.OPT_INT, key="_selected_slot")

    def __init__(self):
        h = _h.combat_register(nc._kind("Subsystem"))
        _ROWS.append(h)
        self.__dict__["_nslot"] = h
        # A sentinel in every field, so a push that did not happen shows.
        _h.combat_set_f(h, nc._fid("_condition"), 0.125)
        for key in ("_cloak_state", "_destroyed", "_radiation_out",
                    "_selected_slot"):
            _h.combat_set_i(h, nc._fid(key), 12345)


class Waker:
    """The wrapped descriptors (NativeWrapped._after_set)."""

    _c = nc.NativeWakeField(float, key="_charge_level")
    _n = nc.NativeWakeField(int, key="_power_setting")
    _p = nc.NativeWakeField(float, key="_condition")

    def __init__(self):
        h = _h.combat_register(nc._kind("Subsystem"))
        _ROWS.append(h)
        self.__dict__["_nslot"] = h
        self.events = []

    def _passive_on_wake(self):
        self.events.append("wake")



# ── Inputs ───────────────────────────────────────────────────────────────────

class _F(float):
    pass


class _FloatOverride(float):
    def __float__(self):
        return 2.5


class _HasFloat:
    def __float__(self):
        return 3.25


class _HasIndex:
    def __index__(self):
        return 7


class _HasInt:
    def __int__(self):
        return 9


class _IntSub(int):
    pass


class _BadBool:
    def __bool__(self):
        raise TypeError("no truth")


class _BoomBool:
    def __bool__(self):
        raise RuntimeError("boom bool")


class _BoomFloat:
    def __float__(self):
        raise RuntimeError("boom float")

    def __int__(self):
        raise RuntimeError("boom int")


class _FloatReturnsInt:
    def __float__(self):
        return 1


class _Falsy:
    def __len__(self):
        return 0


_VALUES = [
    0.0, -0.0, 1.5, -2.75, float("nan"), -float("nan"), float("inf"),
    -float("inf"), 5e-324, 1.7976931348623157e308, 0.1,
    0, 1, -1, 2, (1 << 53) + 1, _INT64[1], _INT64[0], 1 << 63,
    -(1 << 63) - 1, 10 ** 400,
    True, False, None,
    _F(-0.0), _F(7.5), _FloatOverride(1.0), _HasFloat(), _HasIndex(),
    _HasInt(), _IntSub(-4),
    "abc", "1.5", "12", " 7 ", "", "nan", "inf", b"12", b"x",
    [], [0], (), {}, object(), 1j, complex(2, 0),
    fractions.Fraction(1, 3), decimal.Decimal("2.5"), decimal.Decimal("nan"),
    _BadBool(), _BoomBool(), _BoomFloat(), _FloatReturnsInt(), _Falsy(),
]

_ATTRS = ("_f", "_i", "_b", "_t", "_o")


def _field(cls, attr):
    return cls.__dict__[attr]


def _bits(x):
    return struct.pack("<d", x)


def _row_value(obj, field):
    h = obj.__dict__.get("_nslot")
    if h is None:
        return ("dropped",)
    v = _h.combat_dump(h)[field._dump_key]
    return ("row", _bits(v) if isinstance(v, float) else v)


def _expected(field, value):
    """What the reference encoding says the write must do."""
    try:
        enc = field._encode(value)
    except (TypeError, ValueError, OverflowError):
        return ("dropped",)
    except BaseException as e:      # noqa: BLE001 -- propagated unchanged
        return ("raised", type(e))
    if isinstance(enc, float):
        return ("row", _bits(enc))
    if not _INT64[0] <= enc <= _INT64[1]:
        # Not representable in the int64 row: dropped (the old path let
        # pybind's TypeError escape the setter and left a stale row).
        return ("dropped",)
    return ("row", enc)


def _beyond_int64(field, value):
    """An int encoding the int64 row cannot hold: the one input where the
    fast path deliberately differs from the old one (test below)."""
    try:
        enc = field._encode(value)
    except BaseException:           # noqa: BLE001
        return False
    return isinstance(enc, int) and not _INT64[0] <= enc <= _INT64[1]


def _write(obj, attr, value):
    try:
        setattr(obj, attr, value)
    except BaseException as e:      # noqa: BLE001
        return ("raised", type(e))
    return _row_value(obj, _field(type(obj), attr))


def _reference_write(obj, attr, value):
    """The pre-fast-path route: the dict write, then NativeField._push."""
    field = _field(type(obj), attr)
    obj.__dict__[attr] = value
    try:
        field._push(obj, obj.__dict__["_nslot"], value)
    except BaseException as e:      # noqa: BLE001
        return ("raised", type(e))
    return _row_value(obj, field)


def _fast_pushes():
    return nc.counts()["fast_pushes"]


# ── Tests ────────────────────────────────────────────────────────────────────

def test_push_codes_are_the_bindings():
    codes = _h.combat_push_codes()
    assert set(codes) == {"PUSH_FLOAT", "PUSH_INT", "PUSH_BOOL",
                          "PUSH_IS_TRUE", "PUSH_OPT_INT"}
    assert sorted(codes.values()) == list(range(5))


@pytest.mark.parametrize("attr", _ATTRS)
def test_fast_push_encodes_like_encode(attr):
    nc.configure(ON)
    field = _field(Probe, attr)
    for value in _VALUES:
        want = _expected(field, value)
        fast = Probe()
        before = _fast_pushes()
        got = _write(fast, attr, value)
        assert got == want, (attr, value)
        assert _fast_pushes() - before == (1 if want[0] == "row" else 0), \
            (attr, value)
        assert fast.__dict__[attr] is value     # the dict write comes first
        if not _beyond_int64(field, value):
            ref = Probe()
            assert _reference_write(ref, attr, value) == got, (attr, value)


def test_int_beyond_int64_drops_the_row():
    nc.configure(ON)
    for attr in ("_i", "_o"):
        for value in (1 << 63, -(1 << 63) - 1, 10 ** 400):
            p = Probe()
            h = p.__dict__["_nslot"]
            setattr(p, attr, value)
            assert "_nslot" not in p.__dict__
            with pytest.raises(ValueError):
                _h.combat_dump(h)


def test_unencodable_drops_row():
    nc.configure(ON)
    p = Probe()
    h = p.__dict__["_nslot"]
    p._f = "not a float"
    assert "_nslot" not in p.__dict__
    with pytest.raises(ValueError):
        _h.combat_dump(h)
    p._f = 0.5                                  # no slot: nothing to push
    assert p.__dict__["_f"] == 0.5
    # A stale handle (the row freed behind the object's back) drops too.
    q = Probe()
    _h.combat_unregister(q.__dict__["_nslot"])
    q._i = 3
    assert "_nslot" not in q.__dict__
    # An exception _encode does not swallow propagates and keeps the row.
    r = Probe()
    with pytest.raises(RuntimeError):
        r._b = _BoomBool()
    assert "_nslot" in r.__dict__
    assert _h.combat_dump(r.__dict__["_nslot"])["_destroyed"] == 12345
    # Encoding comes before the handle check, as in _push: a stale row
    # with a value whose encoding raises propagates, it does not drop.
    s = Probe()
    _h.combat_unregister(s.__dict__["_nslot"])
    with pytest.raises(RuntimeError):
        s._f = _BoomFloat()
    assert "_nslot" in s.__dict__


def test_switch_off_never_calls_binding(monkeypatch):
    calls = []
    monkeypatch.setattr(_h, "combat_push_scalar",
                        lambda *a: calls.append(a))
    assert not nc.enabled()
    p, w = Probe(), Waker()
    for attr in _ATTRS:
        setattr(p, attr, 1)
    w._c, w._n, w._p = 0.5, 2, 0.25
    assert calls == []
    assert p.__dict__["_f"] == 1 and w.__dict__["_c"] == 0.5
    assert _h.combat_dump(p.__dict__["_nslot"])["_condition"] == 0.125


def test_wake_field_push_uses_fast_path(monkeypatch):
    nc.configure(ON)
    w = Waker()
    h = w.__dict__["_nslot"]

    def _old(*a):
        raise AssertionError("old push binding called: %r" % (a,))
    monkeypatch.setattr(_h, "combat_set_f", _old)
    monkeypatch.setattr(_h, "combat_set_i", _old)
    w.__dict__["_passive_asleep"] = True
    before = _fast_pushes()
    w._c = -0.0
    w._n = True
    w._p = 0.75
    assert _fast_pushes() - before == 3
    row = _h.combat_dump(h)
    assert _bits(row["_charge_level"]) == _bits(-0.0)
    assert row["_power_setting"] == 1
    assert row["_condition"] == 0.75
    assert w.events == ["wake"]         # woken once, by the first write
    # Unencodable through a wrapped field: the wake ran, then the drop.
    w._c = "x"
    assert "_nslot" not in w.__dict__
    assert w.__dict__["_c"] == "x"


def test_raw_entry_rejects_caller_bugs_with_system_error():
    """A wrong argument count, an unknown push code or a field id out of
    range is a bug in the CALLER, not an unencodable value: SystemError, so
    _push_scalar (which drops the row on TypeError / ValueError /
    OverflowError) lets it propagate instead of silently dropping a row."""
    p = Probe()
    h = p.__dict__["_nslot"]
    fid = nc._fid("_condition")
    code = _h.combat_push_codes()["PUSH_FLOAT"]
    for args in ((), (h,), (h, fid, code), (h, fid, code, 1.0, 2.0)):
        with pytest.raises(SystemError):
            _h.combat_push_scalar(*args)
    for bad_code in (-1, 5, 99):
        with pytest.raises(SystemError):
            _h.combat_push_scalar(h, fid, bad_code, 1.0)
    for bad_fid in (-1, len(_h.combat_field_names()), 1 << 20):
        with pytest.raises(SystemError):
            _h.combat_push_scalar(h, bad_fid, code, 1.0)
    # None of them stored anything.
    assert _h.combat_dump(h)["_condition"] == 0.125
    # Through the descriptor: propagated, the row kept.
    nc.configure(ON)
    field = _field(Probe, "_f")
    field._fast = (fid, 99)
    try:
        with pytest.raises(SystemError):
            p._f = 0.5
        assert p.__dict__.get("_nslot") == h
    finally:
        field._fast = None


@pytest.mark.parametrize("name", ["combat_push_scalar",
                                  "combat_apply_reset_counts",
                                  "combat_set_floats"])
def test_stale_so_without_a_binding_is_unavailable(monkeypatch, name):
    """A .so older than a binding the module calls unconditionally (reset()
    calls combat_apply_reset_counts; every scalar push combat_push_scalar;
    every slot-list push combat_set_floats) is stale: native is
    unavailable, never an AttributeError later -- and configure() says so,
    naming the binding (fire control native only, M10)."""
    assert nc.available()
    monkeypatch.delattr(_h, name)
    assert not nc.available()
    with pytest.raises(RuntimeError, match=name):
        nc.configure(ON)
    assert not nc.enabled() and not nc._enabled
    with pytest.raises(RuntimeError, match=name):
        nc.fire_control_native()
    nc.reset()                                  # no AttributeError
