"""Join the q13 static-ABI dumps into a single Ghidra-ready export.

Off-box (dev machine). Reads the committed q13 result files and emits, under
tools/probes/results/ghidra_export/:

    stbc_symbols.csv    one row per UNIQUE C symbol (the mass-rename input)
    stbc_methods.csv    full per-(python_class, method) join, incl. Ptr twins
    stbc_classes.csv    class -> direct bases + transitive ancestors (q13h)
    stbc_constants.csv  every constant with value/hex/type/scope (q13 menu dump)
    stbc_abi.json       all of the above in one bundle + metadata
    README.md           schema notes for the Ghidra session

Usage:  uv run python tools/probes/build_ghidra_export.py
"""
import csv
import json
import re
import pathlib

RESULTS = pathlib.Path(__file__).parent / "results"
OUT = RESULTS / "ghidra_export"

Q13C = RESULTS / "q13c_symbol_map.txt"       # App.Cls.M -> C_Symbol
Q13H = RESULTS / "q13h_inheritance.txt"      # App.Cls : Base1, Base2
Q13CONST = RESULTS / "q13_constants_menu.txt"  # App.Name = <dec> (0x..) type


# --------------------------------------------------------------------------- #
def load_classes() -> dict:
    """{class_name: {"bases":[...], "is_ptr":bool}} from q13h."""
    classes: dict = {}
    for raw in Q13H.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("App.") or " : " not in raw:
            continue
        left, right = raw[4:].split(" : ", 1)
        cls = left.strip()
        if right.strip() == "(root)":
            bases = []
        else:
            bases = [b.strip() for b in right.split(",") if b.strip()]
        classes[cls] = {"bases": bases, "is_ptr": cls.endswith("Ptr")}
    return classes


def ancestors_of(cls: str, classes: dict, _seen=None) -> list:
    """Transitive base closure (depth-first, dedup, order-preserving)."""
    if _seen is None:
        _seen = []
    for b in classes.get(cls, {}).get("bases", []):
        if b not in _seen:
            _seen.append(b)
            ancestors_of(b, classes, _seen)
    return _seen


def load_method_map(known_classes) -> list:
    """[(python_class, method, c_symbol)] from q13c."""
    rows = []
    for raw in Q13C.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("App.") or " -> " not in raw:
            continue
        left, sym = raw[4:].split(" -> ", 1)
        sym = sym.strip()
        if "." not in left:
            continue
        pycls, method = left.split(".", 1)
        rows.append((pycls, method, sym))
    return rows


def owning_class_of(sym: str, known_classes: set):
    """Longest known-class prefix `<Class>_...`; else infer/mark bare."""
    # longest match handles leading-underscore class names (_STStylizedWindow_Move)
    best = None
    for c in known_classes:
        if sym.startswith(c + "_") and (best is None or len(c) > len(best)):
            best = c
    if best is not None:
        return best, "direct"
    if "_" in sym and not sym.startswith("_"):
        return sym.split("_", 1)[0], "direct_unmatched"
    return "", "python_wrapper"   # bare name = hand-written App.py wrapper


def parse_const_value(right: str):
    """'8388710 (0x800066) int' -> (typename, dec_or_None, hex_or_None, repr)."""
    parts = right.rsplit(" ", 1)
    if len(parts) != 2:
        return ("?", None, None, right)
    head, typ = parts[0].strip(), parts[1].strip()
    if typ in ("int", "long"):
        m = re.match(r"(-?\d+)(?:\s*\(0x([0-9a-fA-F]+)\))?", head)
        if m:
            return (typ, m.group(1), (m.group(2) and "0x" + m.group(2)), head)
        return (typ, None, None, head)
    return (typ, None, None, head)   # float/str: value kept as repr in 'head'


def load_constants() -> list:
    rows = []
    for raw in Q13CONST.read_text(encoding="utf-8").splitlines():
        if not raw.startswith("App.") or " = " not in raw:
            continue
        qual, right = raw[4:].split(" = ", 1)
        if "." in qual:                       # class-scoped: Owner.NAME
            owner, name = qual.rsplit(".", 1)
            scope = "class"
        else:
            owner, name, scope = "", qual, "module"
        typ, dec, hexv, valrepr = parse_const_value(right.strip())
        rows.append({
            "qualified_name": "App." + qual, "scope": scope, "owner_class": owner,
            "name": name, "type": typ, "dec": dec, "hex": hexv, "value_repr": valrepr,
        })
    return rows


# --------------------------------------------------------------------------- #
def main() -> None:
    for f in (Q13C, Q13H, Q13CONST):
        if not f.exists():
            raise SystemExit(f"missing input: {f} — run the q13 probes + collect first")

    classes = load_classes()
    known = set(classes)
    method_rows = load_method_map(known)
    # union in any python_class seen only in q13c (safety)
    for pycls, _m, _s in method_rows:
        known.add(pycls)

    # --- per-method join ---
    methods = []
    for pycls, method, sym in method_rows:
        owner, kind = owning_class_of(sym, known)
        methods.append({
            "c_symbol": sym, "python_class": pycls, "method": method,
            "owning_class": owner, "binding_kind": kind,
        })

    # --- unique-symbol view (the mass-rename input) ---
    by_sym: dict = {}
    for m in methods:
        s = by_sym.setdefault(m["c_symbol"], {
            "c_symbol": m["c_symbol"], "owning_class": m["owning_class"],
            "method": m["method"], "binding_kind": m["binding_kind"], "python_aliases": set(),
        })
        s["python_aliases"].add(m["python_class"] + "." + m["method"])
    symbols = []
    for s in by_sym.values():
        symbols.append({
            "c_symbol": s["c_symbol"], "owning_class": s["owning_class"],
            "method": s["method"], "binding_kind": s["binding_kind"],
            "n_python_aliases": len(s["python_aliases"]),
        })
    symbols.sort(key=lambda r: r["c_symbol"])

    # --- classes with ancestors ---
    class_rows = []
    for cls in sorted(classes):
        info = classes[cls]
        class_rows.append({
            "class": cls, "is_ptr": int(info["is_ptr"]),
            "direct_bases": "|".join(info["bases"]),
            "ancestors": "|".join(ancestors_of(cls, classes)),
        })

    constants = load_constants()

    OUT.mkdir(parents=True, exist_ok=True)

    def write_csv(name, rows, cols):
        with (OUT / name).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            for r in rows:
                w.writerow(r)

    write_csv("stbc_symbols.csv", symbols,
              ["c_symbol", "owning_class", "method", "binding_kind", "n_python_aliases"])
    write_csv("stbc_methods.csv", methods,
              ["c_symbol", "python_class", "method", "owning_class", "binding_kind"])
    write_csv("stbc_classes.csv", class_rows,
              ["class", "is_ptr", "direct_bases", "ancestors"])
    write_csv("stbc_constants.csv", constants,
              ["qualified_name", "scope", "owner_class", "name", "type", "dec", "hex", "value_repr"])

    bundle = {
        "meta": {
            "source_binary": "game/stbc.exe",
            "python": "1.5.2 (magic 0x4E99), statically linked; SWIG ~1.1",
            "note": "docstrings stripped (no signatures); types via wrapper "
                    "PyArg_ParseTuple/Py_BuildValue only",
            "counts": {
                "unique_c_symbols": len(symbols), "methods": len(methods),
                "classes": len(class_rows), "constants": len(constants),
            },
        },
        # full per-method join lives in stbc_methods.csv; the bundle keeps the
        # lean, Ghidra-relevant views (unique symbols + classes + constants).
        "symbols": symbols, "classes": class_rows, "constants": constants,
    }
    (OUT / "stbc_abi.json").write_text(json.dumps(bundle, indent=1), encoding="utf-8")

    (OUT / "README.md").write_text(_README, encoding="utf-8")

    print("wrote to", OUT)
    for k, v in bundle["meta"]["counts"].items():
        print("  %-18s %d" % (k, v))


_README = """# STBC engine ABI export (for Ghidra)

Generated by tools/probes/build_ghidra_export.py from the q13 console-probe
dumps of game/stbc.exe (Python 1.5.2 + SWIG ~1.1, statically linked).

## Files
- stbc_symbols.csv   ONE row per unique C symbol — the mass-rename input.
    c_symbol         SWIG wrapper name string as it appears in the binary's
                     module PyMethodDef table (e.g. ShipClass_GetHull).
    owning_class     true implementing C++ class (symbol prefix).
    method           method name.
    binding_kind     direct | direct_unmatched | python_wrapper
                     (python_wrapper = hand-written App.py shim, no C symbol
                      of the Class_Method form; may not exist as its own fn).
    n_python_aliases how many Python (class.method) names resolve to this symbol
                     (Ptr twins etc.).
- stbc_methods.csv   full per-(python_class, method) join incl. Ptr twins.
- stbc_classes.csv   class, is_ptr, direct_bases (|-sep), ancestors (|-sep).
- stbc_constants.csv qualified_name, scope (module|class), owner_class, name,
                     type, dec, hex, value_repr — 3831 constants with values.
- stbc_abi.json      all of the above + metadata, one bundle.

## Intended Ghidra flow
1. Find the SWIG module method table (SwigMethods[], array of {char* name,
   PyCFunction fn, int flags}). Anchor on a distinctive name string from
   stbc_symbols.csv (e.g. "ShipClass_GetHull").
2. Walk the array; for each {name, fn} set the function's name from c_symbol.
   Filter to binding_kind == "direct"/"direct_unmatched" (python_wrapper rows
   have no dedicated binary function).
3. Each _wrap_<symbol> is a thin shim -> follow its main call to the real C++
   method and propagate the name (owning_class::method).
4. Constant-install table: cross-ref stbc_constants.csv (name=value) to label it
   and tag matching immediates in code.
5. stbc_classes.csv -> reconstruct inheritance / shared vtables.

Note: docstrings were stripped (PyMethodDef ml_doc is null), so argument/return
types must be recovered from each wrapper's PyArg_ParseTuple format string and
Py_BuildValue call, not from the export.
"""


if __name__ == "__main__":
    main()
