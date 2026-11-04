"""host_loop.run()'s source as it reads with the frame's sim section inline.

The frame's sim section lives in `host_loop._run_frame_sim` (native motion
phase 4, Task 1), so `inspect.getsource(host_loop.run)` no longer holds it.
The source guards that read run() for an order or a call read this instead:
run()'s source with the `# --- frame sim: call ---` .. `call end` block
replaced by the section between `_run_frame_sim`'s `begin` / `end` markers,
re-indented to the call marker's indentation.
"""
import ast
import inspect
import textwrap

from engine import host_loop

BEGIN = "# --- frame sim: begin ---"
END = "# --- frame sim: end ---"
CALL = "# --- frame sim: call ---"
CALL_END = "# --- frame sim: call end ---"


def _marker_line(lines, marker, where):
    hits = [i for i, line in enumerate(lines) if line.strip() == marker]
    if len(hits) != 1:
        raise AssertionError(
            "%s: marker %r appears %d times, expected once"
            % (where, marker, len(hits)))
    return hits[0]


def _section() -> str:
    lines = inspect.getsource(host_loop._run_frame_sim).splitlines(keepends=True)
    b = _marker_line(lines, BEGIN, "_run_frame_sim")
    e = _marker_line(lines, END, "_run_frame_sim")
    return textwrap.dedent("".join(lines[b + 1:e]))


def run_source() -> str:
    """run()'s source, the frame sim section in place of its call."""
    lines = inspect.getsource(host_loop.run).splitlines(keepends=True)
    c = _marker_line(lines, CALL, "run")
    ce = _marker_line(lines, CALL_END, "run")
    indent = lines[c][:len(lines[c]) - len(lines[c].lstrip())]
    section = textwrap.indent(_section(), indent)
    return "".join(lines[:c]) + section + "".join(lines[ce + 1:])


def run_tree() -> ast.FunctionDef:
    """run_source() parsed: the `run` FunctionDef."""
    return ast.parse(run_source()).body[0]
