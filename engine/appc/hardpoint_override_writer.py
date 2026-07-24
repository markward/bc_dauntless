"""Pure text tooling to maintain a delimited 'managed-overrides' block inside
each _<leaf>(find) function in engine/appc/hardpoint_overrides.py.

The block is regenerated wholesale from an original-stock-name -> current-name
mapping, so edits are idempotent and re-nameable. Only names are supported
today; the block's shape (find(original) then guarded setter calls) is chosen so
future glow/light setters can join each subsystem's group.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict

BLOCK_START = "    # >>> dauntless-overrides (managed) >>>"
BLOCK_END = "    # <<< dauntless-overrides <<<"


def render_managed_block(mapping: "OrderedDict[str, str]") -> str:
    lines = [BLOCK_START]
    for original, current in mapping.items():
        lines.append("    p = find(%s)" % json.dumps(original))
        lines.append("    if p is not None:")
        lines.append("        p.SetName(%s)" % json.dumps(current))
    lines.append(BLOCK_END)
    return "\n".join(lines)


_FIND_RE = re.compile(r'p = find\((".*")\)\s*$')
_SETNAME_RE = re.compile(r'p\.SetName\((".*")\)\s*$')


def parse_managed_block(text: str) -> "OrderedDict[str, str]":
    mapping: "OrderedDict[str, str]" = OrderedDict()
    in_block = False
    pending = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == BLOCK_START.strip():
            in_block = True
            continue
        if stripped == BLOCK_END.strip():
            in_block = False
            continue
        if not in_block:
            continue
        mf = _FIND_RE.match(stripped)
        if mf:
            pending = json.loads(mf.group(1))
            continue
        ms = _SETNAME_RE.match(stripped)
        if ms and pending is not None:
            mapping[pending] = json.loads(ms.group(1))
            pending = None
    return mapping


import ast as _ast


def _function_span(text: str, leaf: str):
    """Return (start_idx, end_idx) of the `def _<leaf>(find):` block in text,
    or None. end_idx is the index just past the function body (at the next
    top-level `def ` / `OVERRIDES` / EOF)."""
    header = "def _%s(find):" % leaf
    start = text.find("\n" + header)
    if start < 0:
        if text.startswith(header):
            start = 0
        else:
            return None
    else:
        start += 1  # skip the leading newline
    # Body ends at the next top-level statement (column-0 def/OVERRIDES) or EOF.
    rest = text[start + len(header):]
    m = re.search(r'\n(?=def |OVERRIDES\b)', rest)
    end = len(text) if m is None else start + len(header) + m.start() + 1
    return (start, end)


def _resolve_original(existing: "OrderedDict[str, str]", loaded_name: str) -> str:
    """The row shows the loaded name (a current override target or a stock
    name). Map it back to the original stock key."""
    for original, current in existing.items():
        if current == loaded_name:
            return original
    return loaded_name


def apply_renames(module_text: str, leaf: str,
                  renames: "list[tuple[str, str]]") -> str:
    span = _function_span(module_text, leaf)
    if span is None:
        module_text = _create_function(module_text, leaf)
        span = _function_span(module_text, leaf)
    start, end = span
    body = module_text[start:end]

    mapping = parse_managed_block(body)
    for loaded_name, new_name in renames:
        original = _resolve_original(mapping, loaded_name)
        if new_name == original:
            mapping.pop(original, None)
        else:
            mapping[original] = new_name

    # Strip any existing managed block from the body, then append the fresh one
    # at the end of the function (after hand-authored glow lookups).
    body_wo = _strip_managed_block(body)
    body_wo = body_wo.rstrip("\n")
    if mapping:
        new_body = body_wo + "\n" + render_managed_block(mapping) + "\n"
    else:
        new_body = body_wo + "\n"

    out = module_text[:start] + new_body + module_text[end:]
    try:
        _ast.parse(out)
    except SyntaxError as e:
        raise ValueError("hardpoint_overrides rewrite would not parse: %s" % e)
    return out


def _strip_managed_block(body: str) -> str:
    lines = body.splitlines(keepends=True)
    out, skipping = [], False
    for line in lines:
        s = line.strip()
        if s == BLOCK_START.strip():
            skipping = True
            continue
        if s == BLOCK_END.strip():
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "".join(out)


def _create_function(text: str, leaf: str) -> str:
    """Insert an empty `def _<leaf>(find):` before `OVERRIDES = {` and register
    it in the dict."""
    fn = "\ndef _%s(find):\n    pass\n\n" % leaf
    anchor = text.find("\nOVERRIDES = {")
    if anchor < 0:
        # No dict yet: append both.
        return text.rstrip("\n") + "\n" + fn + 'OVERRIDES = {\n    "%s": _%s,\n}\n' % (leaf, leaf)
    text = text[:anchor] + "\n" + fn + text[anchor + 1:]
    # Register in the dict literal (insert before its closing brace).
    entry = '    "%s": _%s,\n' % (leaf, leaf)
    close = text.find("\n}", text.find("OVERRIDES = {"))
    return text[:close + 1] + entry + text[close + 1:]
