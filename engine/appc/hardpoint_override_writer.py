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
