"""engine.py15.marshal15 reads Python 1.5 .pyc files.

The synthetic round-trips run on any machine: every fixture is our own
bytecode, built by tests/helpers/py15_assembler.py. The stock-corpus read
needs a BC install (configured through engine.paths) and skips without one.
"""
import pytest

from engine.py15.marshal15 import Code15, Py15FormatError, is_py15_pyc, load_pyc
from tests.helpers import py15_assembler as A

RET = [("LOAD_CONST", 0), ("RETURN_VALUE",)]


@pytest.mark.parametrize("value", [
    None, 1, -7, 2**40, -2**40, 1.5, -0.25, 1 + 2j, b"ab", (1, (2,)), [1],
    {b"k": 2}, Ellipsis,
])
def test_a_constant_round_trips(value):
    code = A.module(RET, consts=(value,))
    assert load_pyc(A.pyc(code)).consts == (value,)


def test_a_code_object_round_trips_whole():
    code = A.projectile_module()
    assert load_pyc(A.pyc(code)) == code


def test_identifiers_are_text_and_bytecode_is_bytes():
    code = load_pyc(A.pyc(A.projectile_module()))
    assert code.names == ("App", "Create", "GetDamage")
    assert isinstance(code.code, bytes)
    assert isinstance(code.consts[0], Code15)


def test_only_the_python_15_magic_is_accepted():
    data = A.pyc(A.module(RET))
    assert is_py15_pyc(data)
    with pytest.raises(Py15FormatError, match="not Python 1.5"):
        load_pyc(b"\xa7\r\r\n" + data[4:])      # CPython 3.11's magic


def test_every_truncation_is_a_format_error():
    data = A.pyc(A.projectile_module())
    for n in range(len(data)):
        with pytest.raises(Py15FormatError):
            load_pyc(data[:n])


def test_a_negative_length_is_a_format_error_not_a_short_read():
    data = A.pyc(A.module(RET, consts=(b"abcd",)))
    at = data.index(b"s\x04\x00\x00\x00abcd")
    bad = data[:at + 1] + b"\xfc\xff\xff\xff" + data[at + 5:]
    with pytest.raises(Py15FormatError):
        load_pyc(bad)


def test_every_stock_pyc_reads():
    """BC ships every game script as 1.5 .pyc; the reader must take them
    all. (1201 files on the GOG install this was measured against.)"""
    from tests.helpers.bc_assets import require_game_dir

    scripts = require_game_dir("scripts")
    files = sorted(scripts.rglob("*.pyc"))
    assert len(files) > 1000, "expected the full retail script set"
    for path in files:
        code = load_pyc(path.read_bytes())
        assert code.name == "?", path      # 1.5 names every module code "?"
