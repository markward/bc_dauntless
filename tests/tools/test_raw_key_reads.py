"""The keyboard-capture guarantee is structural: every key the engine reads
goes through Window::key_state, which filters through the KeyGate. A raw
glfwGetKey anywhere else in native/src would let keys leak into the game
while a CEF text field has focus.

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S2.2, S7.3
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "native" / "src"
WINDOW_CC = NATIVE / "renderer" / "window.cc"
ALLOWED = {"Window::key_state", "Window::set_key_capture"}

# glfwGetKeyName( does NOT match: the name continues past "Key".
_CALL = re.compile(r"\bglfwGetKey\s*\(")


def _blank(text):
    return re.sub(r"[^\n]", " ", text)


def _strip(src):
    """Blank out comments and string/char literals, keeping offsets and
    newlines. Only applied to window.cc, which has no raw string literals."""
    out = []
    i, n = 0, len(src)
    while i < n:
        if src.startswith("//", i):
            j = src.find("\n", i)
            j = n if j < 0 else j
            out.append(_blank(src[i:j])); i = j
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append(_blank(src[i:j])); i = j
        elif src[i] in "\"'":
            q, j = src[i], i + 1
            while j < n and src[j] != q:
                j += 2 if src[j] == "\\" else 1
            j = min(j + 1, n)
            out.append(q + _blank(src[i + 1:j - 1]) + (q if j - i >= 2 else ""))
            i = j
        else:
            out.append(src[i]); i += 1
    return "".join(out)


def enclosing_functions(src):
    """For each glfwGetKey( call in `src`, the qualified name of the
    outermost function body containing it (namespace / extern "C" blocks are
    transparent), or None when the call is not inside a function."""
    s = _strip(src)
    stack = []          # ("ns" | "fn" | "block", name)
    boundary = 0
    hits = []
    for m in re.finditer(r"[{};]|\bglfwGetKey\s*\(", s):
        tok = m.group(0)
        if tok == "{":
            header = s[boundary:m.start()]
            in_fn = any(k == "fn" for k, _ in stack)
            if in_fn:
                stack.append(("block", None))
            elif re.search(r'\bnamespace\b|\bextern\s*"', header):
                stack.append(("ns", None))
            else:
                nm = re.search(r"([A-Za-z_]\w*(?:::~?[A-Za-z_]\w*)+)\s*\(", header)
                stack.append(("fn", nm.group(1) if nm else None))
            boundary = m.end()
        elif tok == "}":
            if stack:
                stack.pop()
            boundary = m.end()
        elif tok == ";":
            boundary = m.end()
        else:
            hits.append(next((nm for k, nm in stack if k == "fn"), None))
    return hits


def test_the_guard_sees_a_planted_offender():
    planted = (
        "namespace renderer {\n"
        "bool Window::key_state(int k) noexcept { return glfwGetKey(h, k); }\n"
        "void Window::poll() { auto f = [&]{ glfwGetKey(h, 1); }; }\n"
        "}\n"
    )
    assert enclosing_functions(planted) == ["Window::key_state", "Window::poll"]


def test_the_guard_ignores_comments_strings_and_key_name():
    src = ('// glfwGetKey(h, 1)\n/* glfwGetKey( */\n'
           'void Window::x() { const char* s = "glfwGetKey("; glfwGetKeyName(1, 2); }\n')
    assert enclosing_functions(src) == []


def test_window_cc_reads_raw_keys_only_inside_the_gate():
    found = enclosing_functions(WINDOW_CC.read_text())
    assert found, "window.cc has no glfwGetKey at all -- the guard is vacuous"
    assert set(found) == ALLOWED, found


def test_no_other_native_file_reads_raw_keys():
    offenders = []
    for path in sorted(NATIVE.rglob("*")):
        if path.suffix not in (".cc", ".cpp", ".h", ".mm") or path == WINDOW_CC:
            continue
        src = path.read_text(errors="replace")
        if "glfwGetKey" not in src:
            continue
        if _CALL.search(re.sub(r"//[^\n]*", "", src)):
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, (
        "raw glfwGetKey outside Window::key_state -- read keys through "
        "g_window->key_state so the KeyGate filters them: %s" % offenders)
