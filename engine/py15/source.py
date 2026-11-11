"""Turn Python 1.5 source text into Python 3 source for the same program.

Both SDK loaders (tools/mission_harness.py and tests/conftest.py) read every
SDK and mod ``.py`` through ``fix_source`` before ``ast.parse``; the lifter
(engine/py15/lift.py) promises the AST this produces for the same module.

Every rewrite works on a scan of the text that knows what is code, what is a
string literal and what is a comment, so a rewrite never reaches into a
string or a comment. The rules, each one Python 1.5's own:

* **Indentation**: a tab in leading whitespace advances to the next multiple
  of 8 columns (1.5's tokenizer). Tabs elsewhere, in strings above all, stay.
* **Text**: a file is UTF-8 if it is valid UTF-8, else cp1252 (``decode_text``).
* **Numbers**: the long suffix ``L`` is dropped; ``0755`` is octal; a plain
  hex or octal literal from 2**31 to 2**32 is negative (a 32-bit C long).
* **String escapes** (non-raw only): ``\\N``, ``\\u`` and ``\\U`` are not
  escapes in 1.5 and stay as written; ``\\x`` takes every following hex digit
  and an octal escape any value, both keeping the low byte, which means the
  character ``decode_text`` gives that byte; ``\\x`` with no hex digit stays
  as written.
* **Operators**: ``<>`` is ``!=``, backticks are ``repr()``, ``.has_key(`` is
  ``.__contains__(``.
* **Statements**, each found at statement level -- after a ``;`` or a
  compound statement's colon as well as at a line start, and ending before a
  ``;`` or a comment: ``print``, ``print >>f``, ``raise X, v``,
  ``exec c in g, l`` and ``except X, e:``.

``print a,`` (trailing comma) becomes ``print(a,)``, as before: the newline
1.5 suppressed is printed. ``print (x)`` is left as a call.
"""
from __future__ import annotations

import re

__all__ = ["decode_text", "fix_source", "fix_syntax", "read_source"]

_CODE, _STRING, _COMMENT, _NEWLINE = "code", "string", "comment", "newline"

_COMPOUND = frozenset({"if", "elif", "else", "while", "for", "try", "except",
                       "finally", "def", "class"})
_OPEN, _CLOSE = "([{", ")]}"

# An integer literal: hex, octal (a leading 0) or decimal, with 1.5's optional
# long suffix. Not after a float exponent's sign (`7.7e-05`: that `05` is the
# exponent), and not the integer part of a float or imaginary literal.
_INT = re.compile(r"(?<![\w.])(?<![0-9.][eE][+-])"
                  r"(0[xX][0-9a-fA-F]+|0[0-7]+|\d+)([lL]?)\b(?![.eEjJ])")
_HAS_KEY = re.compile(r"\.has_key\s*\(")
_HEX = "0123456789abcdefABCDEF"


class _Tok:
    __slots__ = ("kind", "text", "raw", "depth")

    def __init__(self, kind, text, raw=False, depth=0):
        self.kind = kind
        self.text = text
        self.raw = raw
        self.depth = depth      # bracket depth where the token STARTS


def _scan(text):
    """Split ``text`` into code, string, comment and newline tokens.

    A code token is a maximal run of code on one physical line; a newline
    token is a physical line end, with ``depth`` > 0 (or a backslash before
    it) marking a continuation rather than a statement end."""
    toks = []
    i, n, depth = 0, len(text), 0
    start = 0

    def flush(end):
        if end > start:
            toks.append(_Tok(_CODE, text[start:end], depth=depth))

    while i < n:
        ch = text[i]
        if ch == "#":
            flush(i)
            j = text.find("\n", i)
            j = n if j < 0 else j
            toks.append(_Tok(_COMMENT, text[i:j], depth=depth))
            i = start = j
        elif ch == "\n":
            flush(i)
            cont = depth > 0 or (i > 0 and text[i - 1] == "\\")
            toks.append(_Tok(_NEWLINE, "\n", depth=1 if cont else 0))
            i += 1
            start = i
        elif ch in "'\"":
            # A string prefix (r/R) is the identifier character before it.
            raw = (i > start and text[i - 1] in "rR"
                   and (i - 1 == 0 or not (text[i - 2].isalnum()
                                           or text[i - 2] == "_")))
            pre_end = i - 1 if raw else i
            flush(pre_end)
            quote = text[i:i + 3] if text[i:i + 3] in ('"""', "'''") else ch
            j = i + len(quote)
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text.startswith(quote, j):
                    j += len(quote)
                    break
                if len(quote) == 1 and text[j] == "\n":
                    break       # unterminated: let ast.parse report it
                j += 1
            toks.append(_Tok(_STRING, text[pre_end:j], raw=raw, depth=depth))
            i = start = min(j, n)
        else:
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE and depth:
                depth -= 1
            i += 1
    flush(n)
    return toks


# -- token-level rewrites ------------------------------------------------------

def _int_literal(m):
    digits, is_long = m.group(1), bool(m.group(2))
    if digits[:2] in ("0x", "0X"):
        value, text = int(digits, 16), digits
    elif len(digits) > 1 and digits[0] == "0":
        value, text = int(digits, 8), "0o" + digits[1:]
    else:
        return digits
    # A plain (not long) hex or octal literal is a 32-bit C long in 1.5:
    # 0xFFFFFFFF is -1. Parenthesised so it stays one operand anywhere.
    if not is_long and 2 ** 31 <= value < 2 ** 32:
        return "(-%d)" % (2 ** 32 - value)
    return text if value else "0"


def _fix_code(text):
    text = text.replace("<>", "!=")
    text = _HAS_KEY.sub(".__contains__(", text)
    return _INT.sub(_int_literal, text)


def _bc_char(byte):
    """The character a 1.5 string byte means: cp1252 (BC is a Windows game),
    latin-1 for the five bytes cp1252 leaves undefined."""
    try:
        return bytes([byte]).decode("cp1252")
    except UnicodeDecodeError:
        return chr(byte)


def decode_text(raw: bytes) -> str:
    """Python 1.5 source or string bytes as text: UTF-8 when the bytes are
    valid UTF-8 (files written by modern editors), else cp1252 byte by byte.
    The SDK loaders read files with it and the lifter decodes string
    constants with it, so a byte means the same character on every path."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return "".join(_bc_char(b) for b in raw)


def _escape_char(value):
    """A string escape's byte value as a Python 3 escape for the same
    character decode_text gives that byte."""
    ch = _bc_char(value) if value >= 0x80 else chr(value)
    return "\\x%02x" % value if ord(ch) < 0x100 else "\\u%04x" % ord(ch)


def _fix_escapes(literal):
    """A non-raw string literal with 1.5's escape meanings made explicit."""
    out, i, n = [], 0, len(literal)
    while i < n:
        ch = literal[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        nxt = literal[i + 1]
        if nxt in "NuU":
            out.append("\\\\" + nxt)
            i += 2
        elif nxt == "x":
            j = i + 2
            while j < n and literal[j] in _HEX:
                j += 1
            if j == i + 2:
                out.append("\\\\x")
            else:
                out.append(_escape_char(int(literal[i + 2:j], 16) & 0xFF))
            i = j
        elif nxt in "01234567":
            j = i + 1
            while j < n and j < i + 4 and literal[j] in "01234567":
                j += 1
            out.append(_escape_char(int(literal[i + 1:j], 8) & 0xFF))
            i = j
        else:
            out.append(literal[i:i + 2])
            i += 2
    return "".join(out)


def _rewrite_tokens(toks):
    backtick_open = False
    for t in toks:
        if t.kind == _CODE:
            text = _fix_code(t.text)
            if "`" in text:
                parts = text.split("`")
                rebuilt = [parts[0]]
                for part in parts[1:]:
                    rebuilt.append(")" if backtick_open else "repr(")
                    backtick_open = not backtick_open
                    rebuilt.append(part)
                text = "".join(rebuilt)
            t.text = text
        elif t.kind == _STRING and not t.raw:
            t.text = _fix_escapes(t.text)
        elif t.kind == _NEWLINE and t.depth == 0:
            backtick_open = False


# -- statement-level rewrites -----------------------------------------------

def _first_word(text):
    m = re.match(r"\s*([A-Za-z_]\w*)", text)
    return m.group(1) if m else ""


def _split_separators(toks):
    """A new token list with every statement-level ``;`` and compound-header
    colon cut out of the code tokens as a ``sep`` token (the colon stays in
    the header's text). Statement level = bracket depth 0, not in a string."""
    out = []
    at_start, header = True, False
    for t in toks:
        if t.kind == _NEWLINE:
            out.append(t)
            if t.depth == 0:
                at_start, header = True, False
            continue
        if t.kind != _CODE:
            out.append(t)
            if t.kind == _STRING:
                at_start = False
            continue
        text, depth, last = t.text, t.depth, 0
        for i, ch in enumerate(text):
            if at_start and not ch.isspace():
                header = _first_word(text[i:]) in _COMPOUND
                at_start = False
            if ch in _OPEN:
                depth += 1
            elif ch in _CLOSE and depth:
                depth -= 1
            elif depth == 0 and (ch == ";" or (ch == ":" and header)):
                end = i + 1 if ch == ":" else i
                out.append(_Tok(_CODE, text[last:end], depth=t.depth))
                out.append(_Tok("sep", "" if ch == ":" else ";"))
                last = i + 1
                at_start, header = True, False
        out.append(_Tok(_CODE, text[last:], depth=t.depth))
    return out


def _statements(toks):
    """(start, end) token ranges, one per simple statement or compound
    header. Comments, separators and newlines belong to no range; a
    continuation newline (inside brackets, or after a backslash) does."""
    stmt = []
    for k, t in enumerate(toks):
        boundary = (t.kind == "sep"
                    or (t.kind in (_COMMENT, _NEWLINE) and t.depth == 0))
        if boundary:
            if stmt and any(toks[j].text.strip() for j in stmt):
                yield stmt[0], stmt[-1] + 1
            stmt = []
            continue
        stmt.append(k)
    if stmt and any(toks[j].text.strip() for j in stmt):
        yield stmt[0], stmt[-1] + 1


def _string_end(text, i):
    """Index just past the string literal whose opening quote is at i."""
    quote = text[i:i + 3] if text[i:i + 3] in ('"""', "'''") else text[i]
    j = i + len(quote)
    while j < len(text):
        if text[j] == "\\":
            j += 2
        elif text.startswith(quote, j):
            return j + len(quote)
        else:
            j += 1
    return len(text)


def _top_level_split(text, sep):
    """Split code text at depth-0 occurrences of ``sep`` (a char or a
    keyword surrounded by whitespace)."""
    parts, depth, last, i = [], 0, 0, 0
    while i < len(text):
        ch = text[i]
        if ch in "'\"":
            i = _string_end(text, i)
            continue
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE and depth:
            depth -= 1
        elif depth == 0 and text.startswith(sep, i):
            if len(sep) == 1 or (
                    (i == 0 or not (text[i - 1].isalnum() or text[i - 1] == "_"))
                    and (i + len(sep) >= len(text)
                         or not (text[i + len(sep)].isalnum()
                                 or text[i + len(sep)] == "_"))):
                parts.append(text[last:i])
                last = i + len(sep)
                i = last
                continue
        i += 1
    parts.append(text[last:])
    return parts


def _rewrite_statement(text):
    """One statement's text (strings already joined in) -> Python 3."""
    lead = text[:len(text) - len(text.lstrip())]
    body = text.strip()
    if not body:
        return text
    word = re.match(r"[A-Za-z_]\w*", body)
    word = word.group(0) if word else ""
    rest = body[len(word):]
    trail = text[len(text.rstrip()):]
    if word == "print" and not rest.lstrip().startswith("("):
        rest = rest.strip()
        if rest.startswith(">>"):
            target, _, items = rest[2:].partition(",")
            items = items.strip()
            args = (items + ", " if items else "") + "file=" + target.strip()
            return "%sprint(%s)%s" % (lead, args, trail)
        return "%sprint(%s)%s" % (lead, rest, trail)
    if word == "raise" and rest[:1].isspace():
        parts = _top_level_split(rest.strip(), ",")
        if len(parts) == 2 and re.fullmatch(r"\w[\w.]*", parts[0].strip()):
            return "%sraise %s(%s)%s" % (lead, parts[0].strip(),
                                         parts[1].strip(), trail)
    if word == "exec" and rest[:1].isspace():
        code_and_ns = _top_level_split(rest.strip(), "in")
        args = [code_and_ns[0].strip()]
        if len(code_and_ns) == 2:
            args += [p.strip() for p in _top_level_split(code_and_ns[1], ",")]
        return "%sexec(%s)%s" % (lead, ", ".join(args), trail)
    if word == "except" and body.endswith(":"):
        parts = _top_level_split(body[len(word):-1].strip(), ",")
        if len(parts) == 2 and re.fullmatch(r"[A-Za-z_]\w*", parts[1].strip()):
            return "%sexcept %s as %s:%s" % (lead, parts[0].strip(),
                                             parts[1].strip(), trail)
    return text


def _joined(toks, a, b):
    return "".join(t.text for t in toks[a:b])


def _rewrite_statements(toks):
    toks[:] = _split_separators(toks)
    ranges = list(_statements(toks))
    # Rewrite back to front so earlier ranges keep their indices.
    for a, b in reversed(ranges):
        text = _joined(toks, a, b)
        new = _rewrite_statement(text)
        if new != text:
            toks[a:b] = [_Tok(_CODE, new)]


def _expand_indent_tabs(text):
    lines = text.split("\n")
    out = []
    in_string = False
    for line in lines:
        if not in_string:
            stripped = line.lstrip(" \t")
            indent = line[:len(line) - len(stripped)]
            line = indent.expandtabs(8) + stripped
        out.append(line)
        # Track only triple-quoted strings spanning lines; a cheap rescan of
        # this line is enough since single-quoted strings cannot span.
        in_string = _ends_in_triple_string(line, in_string)
    return "\n".join(out)


def _ends_in_triple_string(line, in_string):
    quote = None if not in_string else in_string
    i = 0
    while i < len(line):
        if quote:
            if line[i] == "\\":
                i += 2
                continue
            if line.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
            i += 1
            continue
        ch = line[i]
        if ch == "#":
            break
        if line.startswith('"""', i) or line.startswith("'''", i):
            quote = line[i:i + 3]
            i += 3
            continue
        if ch in "'\"":
            j = i + 1
            while j < len(line) and line[j] != ch:
                j += 2 if line[j] == "\\" else 1
            i = j + 1
            continue
        i += 1
    return quote if quote and len(quote) == 3 else False


def fix_syntax(text: str) -> str:
    """Python 1.5 syntax made Python 3, indentation untouched."""
    toks = _scan(text)
    _rewrite_tokens(toks)
    _rewrite_statements(toks)
    return "".join(t.text for t in toks)


def fix_source(text: str) -> str:
    """What the SDK loaders parse: 1.5 indentation, then ``fix_syntax``."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return fix_syntax(_expand_indent_tabs(text))


def read_source(path) -> str:
    """A 1.5 source file's text (``decode_text``), ready for ``fix_source``."""
    with open(path, "rb") as f:
        return decode_text(f.read())
