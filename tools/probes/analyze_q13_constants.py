"""Off-box (dev-machine) diff of the q13 constant dump vs our App.py shim.

NOT run in-game. Run after collect_q13.py has produced a result file:

    uv run python tools/probes/analyze_q13_constants.py            # auto-pick file
    uv run python tools/probes/analyze_q13_constants.py battle     # force a phase

What it does:
  1. Imports the repo App.py shim and introspects it exactly as the probe
     introspects the real engine (dir(App) + per-class walk), capturing the
     shim's REAL runtime constant values (math.pi resolved, ET_* allocator
     resolved, ...) -- more accurate than AST-parsing the source.
  2. Parses the probe's ground-truth dump (tools/probes/results/q13_constants_*.txt).
  3. Cross-references docs/stub_heatmap.md's unimplemented-attribute roadmap.
  4. Emits three buckets:
       WRONG     -- shim defines a value that disagrees with the engine.
       MISSING   -- engine exposes it, shim does not (so it hits the _Stub path).
       LIVE-HIT  -- the subset of WRONG+MISSING that the heatmap has actually
                    observed being hit at runtime, ranked by hit count. This is
                    the "pays for itself" list: provably-live latent bugs the
                    dump now resolves.
  Plus an informational EXTRA count (shim has it, engine dump does not).
"""
import ast
import math
import pathlib
import re
import sys

PROBES = pathlib.Path(__file__).parent
RESULTS = PROBES / "results"
ROOT = PROBES.parent.parent
HEATMAP = ROOT / "docs" / "stub_heatmap.md"

_SCALAR_TYPES = (int, float, str, bool)


# --------------------------------------------------------------------------- #
# 1. shim introspection
# --------------------------------------------------------------------------- #
def _install_native_stub_if_absent() -> None:
    """The shim transitively imports the C++ `_dauntless_host` extension. Prefer
    the real build (build/python/), but fall back to a permissive stub so the
    analyzer runs on a machine that has not built the native module."""
    build_python = ROOT / "build" / "python"
    if build_python.is_dir() and str(build_python) not in sys.path:
        sys.path.insert(0, str(build_python))
    import importlib.util
    if importlib.util.find_spec("_dauntless_host") is not None:
        return
    import types

    class _Stub:
        def __getattr__(self, name):
            return _Stub()
        def __call__(self, *a, **k):
            return _Stub()
        def __int__(self):
            return 0
        def __float__(self):
            return 0.0
        def __bool__(self):
            return True

    class _StubModule(types.ModuleType):
        def __getattr__(self, name):
            return _Stub()

    sys.modules["_dauntless_host"] = _StubModule("_dauntless_host")


def load_shim_constants() -> dict:
    """Import the App.py shim and return {qualified_name: (value, typename)}."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    _install_native_stub_if_absent()
    try:
        import App  # the repo-root shim (shadows the SDK)
    except Exception as e:  # noqa: BLE001 - report and bail, don't crash
        print(f"FATAL: could not import the App.py shim: {type(e).__name__}: {e}")
        print("(run from the repo root; if the native module is unbuilt this can")
        print(" still fail on engine-module import — build with `cmake --build build`)")
        sys.exit(2)

    out: dict = {}

    def attr_names(cls) -> set:
        names = set()
        try:
            names.update(dir(cls))
        except Exception:
            pass
        for base in getattr(cls, "__bases__", ()):
            names |= attr_names(base)
        return names

    for name in dir(App):
        if name.startswith("__"):
            continue
        try:
            v = getattr(App, name)
        except Exception:
            continue
        if isinstance(v, _SCALAR_TYPES):
            out[f"App.{name}"] = (v, type(v).__name__)
        elif isinstance(v, type) or _is_old_style_class(v):
            cls = v
            for attr in attr_names(cls):
                if attr.startswith("__"):
                    continue
                try:
                    av = getattr(cls, attr)
                except Exception:
                    continue
                if isinstance(av, _SCALAR_TYPES):
                    out[f"App.{name}.{attr}"] = (av, type(av).__name__)
    return out


def _is_old_style_class(v) -> bool:
    # the shim defines plain `class Foo:` (new-style in py3); isinstance(v, type)
    # already covers them. Kept as a hook in case a metaclass slips through.
    return False


# --------------------------------------------------------------------------- #
# 2. dump parsing
# --------------------------------------------------------------------------- #
def parse_dump_line(line: str):
    """'App.X = 1 (0x1) int' -> ('App.X', 1, 'int'); returns None if not a const."""
    if not line.startswith("App.") or " = " not in line:
        return None
    name, right = line.split(" = ", 1)
    right = right.strip()
    if " " not in right:
        return None
    head, typename = right.rsplit(" ", 1)
    head = head.strip()
    try:
        if typename in ("int", "long"):
            tok = head.split()[0]
            return (name, int(tok.rstrip("Ll")), typename)
        if typename == "float":
            return (name, float(head), typename)
        if typename == "str":
            return (name, ast.literal_eval(head), typename)
    except Exception:
        return (name, head, typename)
    return (name, head, typename)


def load_dump(path: pathlib.Path) -> dict:
    out: dict = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        parsed = parse_dump_line(raw.strip())
        if parsed:
            out[parsed[0]] = (parsed[1], parsed[2])
    return out


# --------------------------------------------------------------------------- #
# 3. heatmap roadmap
# --------------------------------------------------------------------------- #
def load_heatmap_hits() -> dict:
    """{ 'App.<owner>.<attr>': total_hits } from the roadmap table."""
    hits: dict = {}
    if not HEATMAP.exists():
        return hits
    row = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(\d+)\s*\|")
    for line in HEATMAP.read_text(encoding="utf-8").splitlines():
        m = row.match(line)
        if m:
            owner, attr, n = m.group(1), m.group(2), int(m.group(3))
            hits[f"App.{owner}.{attr}"] = n
    return hits


# --------------------------------------------------------------------------- #
# comparison
# --------------------------------------------------------------------------- #
def values_equal(shim_v, dump_v, dump_typ: str) -> bool:
    if isinstance(shim_v, bool):
        shim_v = int(shim_v)
    try:
        if dump_typ == "float" or isinstance(shim_v, float):
            return math.isclose(float(shim_v), float(dump_v), rel_tol=1e-9, abs_tol=1e-12)
        if dump_typ in ("int", "long"):
            return int(shim_v) == int(dump_v)
        if dump_typ == "str":
            return str(shim_v) == str(dump_v)
    except Exception:
        return False
    return shim_v == dump_v


def pick_result_file(arg: str | None) -> pathlib.Path:
    if arg:
        p = RESULTS / f"q13_constants_{arg}.txt"
        if not p.exists():
            print(f"no result file {p}")
            sys.exit(1)
        return p
    battle = RESULTS / "q13_constants_battle.txt"
    menu = RESULTS / "q13_constants_menu.txt"
    if battle.exists():
        return battle
    if menu.exists():
        return menu
    print("no q13 result file found -- run the probe and collect_q13.py first")
    sys.exit(1)


# --------------------------------------------------------------------------- #
def main() -> None:
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    result_file = pick_result_file(arg)
    print(f"# q13 constant analysis")
    print(f"# dump   : {result_file.relative_to(ROOT)}")

    dump = load_dump(result_file)
    shim = load_shim_constants()
    hits = load_heatmap_hits()
    print(f"# engine : {len(dump)} constants")
    print(f"# shim   : {len(shim)} constants")
    print(f"# heatmap: {len(hits)} roadmap rows")
    print()

    wrong, missing, extra = [], [], []
    for name, (dval, dtyp) in sorted(dump.items()):
        if name in shim:
            sval = shim[name][0]
            if not values_equal(sval, dval, dtyp):
                wrong.append((name, sval, dval, dtyp))
        else:
            missing.append((name, dval, dtyp))
    for name in sorted(shim):
        if name not in dump:
            extra.append(name)

    def hit(name):
        return hits.get(name, 0)

    print(f"## BUCKET 1 - WRONG (shim value disagrees with engine): {len(wrong)}")
    for name, sval, dval, dtyp in sorted(wrong, key=lambda r: -hit(r[0])):
        tag = f"   [live hits: {hit(name)}]" if hit(name) else ""
        print(f"  {name}: shim={sval!r} engine={dval!r} ({dtyp}){tag}")
    print()

    print(f"## BUCKET 2 - MISSING (engine has it, shim stubs it): {len(missing)}")
    for name, dval, dtyp in sorted(missing, key=lambda r: -hit(r[0])):
        tag = f"   [live hits: {hit(name)}]" if hit(name) else ""
        print(f"  {name} = {dval!r} ({dtyp}){tag}")
    print()

    live = [(n, h) for n, h in ((r[0], hit(r[0])) for r in
             ([(w[0],) for w in wrong] + [(m[0],) for m in missing])) if h]
    live.sort(key=lambda r: -r[1])
    print(f"## BUCKET 3 - LIVE-HIT & RESOLVABLE (in heatmap roadmap): {len(live)}")
    for name, h in live:
        kind = "WRONG" if name in {w[0] for w in wrong} else "MISSING"
        print(f"  {name}  hits={h}  [{kind}]")
    print()

    print(f"## (info) EXTRA - shim defines, engine dump lacks: {len(extra)}")
    print("  (engine-internal constants or dump not run in the state that exposes them)")

    RESULTS.mkdir(exist_ok=True)
    # a machine-checkable summary line for CI / quick eyeballing
    print()
    print(f"SUMMARY wrong={len(wrong)} missing={len(missing)} live={len(live)} extra={len(extra)}")


if __name__ == "__main__":
    main()
