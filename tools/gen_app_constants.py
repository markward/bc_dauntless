"""Regenerate engine/appc/constants_generated.py from the q13 measured dump.

Run:  uv run python tools/gen_app_constants.py
"""
import csv
import pathlib

from tools.constant_surface_audit import CSV_PATH, SKIP, parse

OUT = (pathlib.Path(__file__).resolve().parents[1]
       / "engine/appc/constants_generated.py")

HEADER = '''"""App constant values measured from the ORIGINAL GAME.  GENERATED -- do not edit.

Regenerate with:  uv run python tools/gen_app_constants.py
Source:           tools/probes/results/ghidra_export/stbc_constants.csv
Provenance:       docs/instrumented_experiments/2026-07-13-constant-dump-probe.md

Every value here was read out of a running stbc.exe by probe q13.  None is
inferred from the SDK and none is invented.  `App.py` applies this table via
engine.appc.constants_apply.apply_constants; names we deliberately keep
different from BC are listed in that module's DEVIATIONS table.
"""

'''


def _lit(value):
    """Render a value as source.  Ints as hex when they are flag-like."""
    if isinstance(value, int) and value >= 0x1000:
        return hex(value)
    return repr(value)


def render():
    """The full source text of the generated module."""
    rows = [r for r in csv.DictReader(open(CSV_PATH)) if r["name"] not in SKIP]
    module = {r["name"]: parse(r) for r in rows if r["scope"] == "module"}
    classes = {}
    for r in rows:
        if r["scope"] != "module":
            classes.setdefault(r["owner_class"], {})[r["name"]] = parse(r)

    out = [HEADER, "MODULE_CONSTANTS: dict[str, int | float | str] = {\n"]
    for name in sorted(module):
        out.append("    %r: %s,\n" % (name, _lit(module[name])))
    out.append("}\n\nCLASS_CONSTANTS: dict[str, dict[str, int | float | str]] = {\n")
    for cls in sorted(classes):
        out.append("    %r: {\n" % cls)
        for name in sorted(classes[cls]):
            out.append("        %r: %s,\n" % (name, _lit(classes[cls][name])))
        out.append("    },\n")
    out.append("}\n")
    return "".join(out)


if __name__ == "__main__":
    OUT.write_text(render())
    print("wrote %s" % OUT)
