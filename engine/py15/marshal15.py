"""Read a Python 1.5 ``.pyc`` file: header, then one marshalled code object.

BC's ``stbc.exe`` embeds Python 1.5 (magic ``0x4E99``), and mod authors ship
modules as the ``.pyc`` it wrote. CPython 3 cannot read that format, and its
``marshal`` module never could: 1.5 code objects carry 16-bit fields and
floats as decimal text.

Pure data: nothing here executes the bytecode. Strings stay ``bytes`` except
identifiers (names, varnames, filename, code name), which are ASCII in every
file BC itself shipped and are decoded as latin-1 so no byte is ever lost.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

# b"\x99\x4e\x0d\x0a": 20121 (0x4E99) little-endian, then "\r\n".
MAGIC = b"\x99N\r\n"


class Py15FormatError(ValueError):
    """The file is not a well-formed Python 1.5 .pyc."""


@dataclass(frozen=True)
class Code15:
    argcount: int
    nlocals: int
    stacksize: int
    flags: int
    code: bytes
    consts: tuple
    names: tuple
    varnames: tuple
    filename: str
    name: str
    firstlineno: int
    lnotab: bytes


class _Reader:
    def __init__(self, data: bytes, pos: int):
        self.data = data
        self.pos = pos

    def _take(self, n: int) -> bytes:
        end = self.pos + n
        if n < 0 or end > len(self.data):
            raise Py15FormatError("truncated at offset %d" % self.pos)
        chunk = self.data[self.pos:end]
        self.pos = end
        return chunk

    def byte(self) -> int:
        return self._take(1)[0]

    def short(self) -> int:
        return struct.unpack("<h", self._take(2))[0]

    def long(self) -> int:
        return struct.unpack("<i", self._take(4))[0]

    def _float_text(self) -> float:
        return float(self._take(self.byte()).decode("ascii"))

    def _ident(self) -> str:
        value = self.object()
        if not isinstance(value, bytes):
            raise Py15FormatError("expected a string, got %r" % type(value))
        return value.decode("latin-1")

    def object(self):
        kind = chr(self.byte())
        if kind == "N":
            return None
        if kind == ".":
            return Ellipsis
        if kind == "i":
            return self.long()
        if kind == "I":
            return struct.unpack("<q", self._take(8))[0]
        if kind == "f":
            return self._float_text()
        if kind == "x":
            real = self._float_text()
            return complex(real, self._float_text())
        if kind == "l":
            n = self.long()
            value = 0
            for i in range(abs(n)):
                value |= struct.unpack("<H", self._take(2))[0] << (15 * i)
            return -value if n < 0 else value
        if kind == "s":
            return self._take(self.long())
        if kind in "([":
            items = tuple(self.object() for _ in range(self.long()))
            return items if kind == "(" else list(items)
        if kind == "{":
            out = {}
            while True:
                if self.data[self.pos:self.pos + 1] == b"0":
                    self.pos += 1
                    return out
                key = self.object()
                out[key] = self.object()
        if kind == "c":
            argcount, nlocals, stacksize, flags = (self.short() for _ in range(4))
            code = self.object()
            consts = self.object()
            names = tuple(n.decode("latin-1") for n in self.object())
            varnames = tuple(n.decode("latin-1") for n in self.object())
            filename = self._ident()
            name = self._ident()
            firstlineno = self.short()
            lnotab = self.object()
            return Code15(argcount, nlocals, stacksize, flags, code, consts,
                          names, varnames, filename, name, firstlineno, lnotab)
        raise Py15FormatError("unknown marshal type %r at offset %d"
                              % (kind, self.pos - 1))


def is_py15_pyc(data: bytes) -> bool:
    """True when `data` starts with the Python 1.5 .pyc magic."""
    return data[:4] == MAGIC


def load_pyc(data: bytes) -> Code15:
    """The module code object of a Python 1.5 .pyc file's bytes."""
    if not is_py15_pyc(data):
        raise Py15FormatError("not Python 1.5 bytecode (magic %s)" % data[:4].hex())
    reader = _Reader(data, 8)          # magic + 4-byte mtime
    try:
        code = reader.object()
    except Py15FormatError:
        raise
    except (ValueError, TypeError, AttributeError, IndexError,
            struct.error, RecursionError) as exc:
        # Corrupt input must surface as a format error, never as whatever
        # a half-read value happened to raise.
        raise Py15FormatError("malformed: %s: %s" % (type(exc).__name__, exc)) from exc
    if not isinstance(code, Code15):
        raise Py15FormatError("top-level object is not a code object")
    return code
