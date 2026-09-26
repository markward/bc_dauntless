"""Rewrite a MOD's own ships/Hardpoints/<leaf>.py with Ship Property Viewer
edits (spec docs/superpowers/specs/2026-09-26-spv-save-to-mod-hardpoint-design.md).

Pure text in, text out -- file I/O lives in override_routing.ModHardpointFileTarget.
SetPosition/SetRadius are rewritten in place on the author's own call; every
other edit lives in ONE machine-owned block at the end of the file, between
START_MARKER and END_MARKER, guarded on App.DAUNTLESS_ENV so stock stbc.exe
skips it. Emitted code must stay Python 1.5 safe.
"""
from __future__ import annotations

import ast

from engine.appc import hardpoint_override_writer as _w

START_MARKER = "# >>> dauntless SPV edits -- machine-owned, regenerated on save; do not edit >>>"
END_MARKER = "# <<< dauntless SPV edits <<<"
BLOCK_FN = "_dauntless_spv"
_PARTS_KEY = "__parts__"


class ManagedBlockError(ValueError):
    """The file's managed-block markers are malformed; never guess."""


def _marker_lines(text):
    """[(line_start, line_end_incl_newline, stripped_line)] for marker lines."""
    out, pos = [], 0
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if s in (START_MARKER, END_MARKER):
            out.append((pos, pos + len(line), s))
        pos += len(line)
    return out


def split_block(text):
    marks = _marker_lines(text)
    if not marks:
        return text, None
    kinds = [m[2] for m in marks]
    if kinds != [START_MARKER, END_MARKER]:
        raise ManagedBlockError("malformed dauntless SPV markers: %r" % kinds)
    (s0, _s1, _), (_e0, e1, _) = marks
    return text[:s0] + text[e1:], text[s0:e1]


def read_block(block_text):
    """The block's model. Only the `def _dauntless_spv` is executed -- never
    the block's `import App` + guarded call, which under the real shim would
    register parts on the live g_kModelPropertyManager as a side effect."""
    if not block_text:
        return {}
    tree = ast.parse(block_text)
    fn = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == BLOCK_FN]
    if len(fn) != 1:
        raise ManagedBlockError("managed block has no %s()" % BLOCK_FN)
    module = ast.Module(body=fn, type_ignores=[])
    ast.fix_missing_locations(module)
    ns = {}
    exec(compile(module, "<dauntless SPV block>", "exec"), ns)  # noqa: S102
    return _w.record_fn(ns[BLOCK_FN])


def _non_empty(per_sub):
    subs = any(c for s, c in per_sub.items() if s != _PARTS_KEY)
    parts = any(c for c in per_sub.get(_PARTS_KEY, {}).values())
    return subs or parts


def emit_block(per_sub, newline="\n"):
    if not _non_empty(per_sub):
        return ""
    lines = [START_MARKER,
             _w._emit_function("spv", per_sub, fn_name=BLOCK_FN),
             "",
             "import App",
             _w.env_guard(),
             "    %s(lambda n: App.g_kModelPropertyManager.FindByName("
             "n, App.TGModelPropertyManager.LOCAL_TEMPLATES))" % BLOCK_FN,
             END_MARKER]
    return newline.join("\n".join(lines).split("\n")) + newline


def append_block(author_text, block, newline):
    if not block:
        return author_text
    if author_text and not author_text.endswith(("\n", "\r")):
        author_text += newline
    return author_text + block
