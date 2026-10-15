"""Assemble Python 1.5 ``.pyc`` bytes for tests.

A test-only marshal WRITER, the inverse of engine/py15/marshal15.py. Every
fixture it builds is our own bytecode written by hand, so tests of the
lifter run on a machine with no Bridge Commander install and commit no BC or
mod content.

    pyc_bytes = pyc(module([("LOAD_CONST", 0), ("RETURN_VALUE",)],
                           consts=(None,)))
"""
from __future__ import annotations

import struct

from engine.py15 import opcodes15
from engine.py15.marshal15 import MAGIC, Code15

OPCODES = {name: num for num, name in opcodes15.NAMES.items()}

# CO_OPTIMIZED | CO_NEWLOCALS: what the 1.5 compiler sets on every def.
FUNCTION_FLAGS = 0x0003


def asm(instructions) -> bytes:
    """Bytecode for [("NAME",) or ("NAME", arg), ...]."""
    out = bytearray()
    for ins in instructions:
        num = OPCODES[ins[0]]
        out.append(num)
        if num >= opcodes15.HAVE_ARGUMENT:
            out += struct.pack("<H", ins[1])
    return bytes(out)


def function(name, instructions, *, consts=(None,), names=(), varnames=(),
             argcount=0, flags=FUNCTION_FLAGS, firstlineno=1) -> Code15:
    """A def's code object. consts[0] is the docstring slot (None or str),
    exactly as the 1.5 compiler lays it out."""
    return Code15(argcount, len(varnames), 10, flags, asm(instructions),
                  tuple(consts), tuple(names), tuple(varnames), "test.py",
                  name, firstlineno, b"")


def module(instructions, *, consts=(None,), names=()) -> Code15:
    return Code15(0, 0, 10, 0, asm(instructions), tuple(consts), tuple(names),
                  (), "test.py", "?", 1, b"")


def dumps(value) -> bytes:
    if value is None:
        return b"N"
    if value is Ellipsis:
        return b"."
    if isinstance(value, bool):
        raise TypeError("Python 1.5 has no bool")
    if isinstance(value, int):
        if -2**31 <= value < 2**31:
            return b"i" + struct.pack("<i", value)
        digits, n = [], abs(value)
        while n:
            digits.append(n & 0x7FFF)
            n >>= 15
        count = len(digits) if value > 0 else -len(digits)
        return (b"l" + struct.pack("<i", count)
                + b"".join(struct.pack("<H", d) for d in digits))
    if isinstance(value, float):
        text = repr(value).encode("ascii")
        return b"f" + bytes([len(text)]) + text
    if isinstance(value, complex):
        real, imag = (repr(v).encode("ascii") for v in (value.real, value.imag))
        return b"x" + bytes([len(real)]) + real + bytes([len(imag)]) + imag
    if isinstance(value, str):
        value = value.encode("utf-8")
    if isinstance(value, (bytes, bytearray)):
        return b"s" + struct.pack("<i", len(value)) + bytes(value)
    if isinstance(value, (tuple, list)):
        tag = b"(" if isinstance(value, tuple) else b"["
        return tag + struct.pack("<i", len(value)) + b"".join(map(dumps, value))
    if isinstance(value, dict):
        return (b"{" + b"".join(dumps(k) + dumps(v) for k, v in value.items())
                + b"0")
    if isinstance(value, Code15):
        return (b"c" + struct.pack("<4h", value.argcount, value.nlocals,
                                   value.stacksize, value.flags)
                + dumps(value.code) + dumps(value.consts) + dumps(value.names)
                + dumps(value.varnames) + dumps(value.filename)
                + dumps(value.name) + struct.pack("<h", value.firstlineno)
                + dumps(value.lnotab))
    raise TypeError("cannot marshal %r" % type(value))


def pyc(code: Code15, mtime: int = 0) -> bytes:
    return MAGIC + struct.pack("<I", mtime) + dumps(code)


def projectile_module(damage=500.0):
    """The stock projectile shape in miniature, as straight-line 1.5 bytecode:

        import App
        def Create(pTorp):
            pTorp.SetDamage(GetDamage())
            import Multiplayer.SpeciesToTorp
            pTorp.SetNetType(Multiplayer.SpeciesToTorp.PHOTON)
            return 0
        def GetDamage():
            return <damage>
    """
    create = function(
        "Create",
        [("SET_LINENO", 3), ("LOAD_FAST", 0), ("LOAD_ATTR", 0),
         ("LOAD_GLOBAL", 1), ("CALL_FUNCTION", 0), ("CALL_FUNCTION", 1),
         ("POP_TOP",),
         ("SET_LINENO", 4), ("IMPORT_NAME", 2), ("STORE_FAST", 1),
         ("SET_LINENO", 5), ("LOAD_FAST", 0), ("LOAD_ATTR", 3),
         ("LOAD_FAST", 1), ("LOAD_ATTR", 4), ("LOAD_ATTR", 5),
         ("CALL_FUNCTION", 1), ("POP_TOP",),
         ("SET_LINENO", 6), ("LOAD_CONST", 1), ("RETURN_VALUE",),
         ("LOAD_CONST", 0), ("RETURN_VALUE",)],
        consts=(None, 0),
        names=("SetDamage", "GetDamage", "Multiplayer.SpeciesToTorp",
               "SetNetType", "SpeciesToTorp", "PHOTON"),
        varnames=("pTorp", "Multiplayer"), argcount=1, firstlineno=2)
    get_damage = function(
        "GetDamage",
        [("SET_LINENO", 8), ("LOAD_CONST", 1), ("RETURN_VALUE",),
         ("LOAD_CONST", 0), ("RETURN_VALUE",)],
        consts=(None, damage), firstlineno=7)
    return module(
        [("SET_LINENO", 1), ("IMPORT_NAME", 0), ("STORE_NAME", 0),
         ("SET_LINENO", 2), ("LOAD_CONST", 0), ("MAKE_FUNCTION", 0),
         ("STORE_NAME", 1),
         ("SET_LINENO", 7), ("LOAD_CONST", 1), ("MAKE_FUNCTION", 0),
         ("STORE_NAME", 2),
         ("LOAD_CONST", 2), ("RETURN_VALUE",)],
        consts=(create, get_damage, None),
        names=("App", "Create", "GetDamage"))
