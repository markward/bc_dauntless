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


# ── In-place rewrite of the author's own SetPosition/SetRadius calls ───────

INPLACE_SETTERS = ("SetPosition", "SetRadius")


def _is_create_of(node, subsystem):
    return (isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name) and node.func.value.id == "App"
            and node.func.attr.endswith("Property_Create")            # spec §4.1
            and len(node.args) >= 1
            and isinstance(node.args[0], ast.Constant) and node.args[0].value == subsystem)


def _is_setter_call_on(stmt, var, setter):
    """`stmt` is exactly the top-level statement `V.<setter>(...)`."""
    return (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)
            and isinstance(stmt.value.func, ast.Attribute)
            and stmt.value.func.attr == setter
            and isinstance(stmt.value.func.value, ast.Name)
            and stmt.value.func.value.id == var)


def _contains_setter_call(node, var, setter):
    """Whether `V.<setter>(...)` appears anywhere inside `node`, at any
    nesting depth (an `if`/loop/function body, or as a sub-expression)."""
    for n in ast.walk(node):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == setter and isinstance(n.func.value, ast.Name)
                and n.func.value.id == var):
            return True
    return False


def find_setter_call(tree, subsystem, setter):
    """The LAST module-level, top-level-statement `V.<setter>(...)` issued
    while V is bound to `App.<X>Property_Create("<subsystem>")`. None when
    absent (loop-built, computed name, inside a function, or no such call) --
    and ALSO None when any later statement contains a `V.<setter>(...)` call
    at any OTHER nesting depth (inside an `if`, a loop, a function body, or as
    a sub-expression): such a call runs after ours at runtime and would
    silently override an in-place rewrite of the top-level call, so the whole
    candidacy is treated as unsafe rather than producing a save that looks
    right in the file but does nothing in the game."""
    var, hit = None, None
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            names = [t.id for t in stmt.targets if isinstance(t, ast.Name)]
            if len(stmt.targets) == 1 and names and _is_create_of(stmt.value, subsystem):
                var, hit = names[0], None
                continue
            if var in names:
                var = None                          # rebound: later calls are not ours
                continue
        if var is None:
            continue
        if _is_setter_call_on(stmt, var, setter):
            hit = stmt.value
            continue
        if _contains_setter_call(stmt, var, setter):
            return None                              # could override us at runtime
    return hit


def format_setter_call(var, setter, args):
    return "%s.%s(%s)" % (var, setter, ", ".join("%f" % float(a) for a in args))


def _char_span(text, node):
    """(start, end) character offsets of `node` in `text`. ast columns are
    UTF-8 byte offsets within a line, so convert per line."""
    lines = text.split("\n")                 # CRLF keeps its \r on the line: fine for offsets
    def off(lineno, col_bytes):
        before = sum(len(l) + 1 for l in lines[:lineno - 1])
        return before + len(lines[lineno - 1].encode("utf-8")[:col_bytes].decode("utf-8"))
    return off(node.lineno, node.col_offset), off(node.end_lineno, node.end_col_offset)


def _newline_of(text):
    return "\r\n" if "\r\n" in text else "\n"


def _dedupe_last_wins(edits):
    """Two edits for the same (subsystem, setter) 3-tuple key would each
    independently locate and splice the SAME source span via
    find_setter_call, producing overlapping replacements. Keep only the
    last-issued edit per key, in its original position."""
    last_index = {}
    for i, edit in enumerate(edits):
        if len(edit) == 3:
            last_index[(edit[0], edit[1])] = i
    keep = set(last_index.values())
    return [edit for i, edit in enumerate(edits) if len(edit) != 3 or i in keep]


def _check_span_is_the_call(author, start, end, var, setter):
    """A REAL verify against the source -- not a tautology. Undoing a splice
    with the same span it was cut from always reproduces the input, so that
    check catches nothing; this instead re-parses the exact slice of the
    ORIGINAL text the span claims to cover and confirms it really is
    `var.setter(...)`."""
    seg = author[start:end]
    try:
        node = ast.parse(seg, mode="eval").body
    except SyntaxError:
        node = None
    ok = (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
          and node.func.attr == setter and isinstance(node.func.value, ast.Name)
          and node.func.value.id == var)
    if not ok:
        raise ManagedBlockError(
            "in-place rewrite span %r is not %s.%s(...)" % (seg, var, setter))


def _check_no_overlapping_spans(replacements):
    ordered = sorted(replacements)
    for (_s1, e1, _n1), (s2, _e2, _n2) in zip(ordered, ordered[1:]):
        if s2 < e1:
            raise ManagedBlockError("in-place rewrite spans overlap")


def rewrite(text, leaf, edits):
    newline = _newline_of(text)
    author, block = split_block(text)
    models = {leaf: read_block(block)}
    edits = _dedupe_last_wins(edits)
    try:
        tree = ast.parse(author) if ("\r" not in author.replace("\r\n", "")) else None
    except SyntaxError:
        tree = None

    replacements = []                         # (start, end, new_text)
    for edit in edits:
        if tree is not None and len(edit) == 3 and edit[1] in INPLACE_SETTERS:
            subsystem, setter, args = edit
            call = find_setter_call(tree, subsystem, setter)
            if call is not None:
                var = call.func.value.id
                start, end = _char_span(author, call)
                _check_span_is_the_call(author, start, end, var, setter)
                replacements.append((start, end, format_setter_call(var, setter, args)))
                calls = models[leaf].get(subsystem)
                if calls:
                    models[leaf][subsystem] = [(s, a) for (s, a) in calls if s != setter]
                continue
        _w.apply_edit(models, leaf, edit)

    _check_no_overlapping_spans(replacements)

    new_author = author
    for start, end, new in sorted(replacements, reverse=True):
        new_author = new_author[:start] + new + new_author[end:]

    block_text = emit_block(models[leaf], newline)
    if block_text:
        ast.parse(block_text)                 # spec §5.6: block parses on its own,
                                                # whenever non-empty, even if the
                                                # author's own text does not (py1.5/py2)

    out = append_block(new_author, block_text, newline)
    if tree is not None:
        ast.parse(out)                        # raises SyntaxError on a bad result
    return out
