"""Compare the q13 measured constant surface against our App shim.

Data source: tools/probes/results/ghidra_export/stbc_constants.csv — the
machine-readable twin of the q13_constants_*.txt dumps.  Read, never guessed.
"""
import csv
import pathlib

CSV_PATH = (pathlib.Path(__file__).resolve().parent
            / "probes/results/ghidra_export/stbc_constants.csv")

# In the dump but never definable: they are Python module internals.
SKIP = {"__name__", "__file__"}


def parse(row):
    """The measured value for a dump row, correctly typed."""
    if row["type"] == "int":
        return int(row["dec"])
    if row["type"] == "float":
        return float(row["value_repr"])
    return row["value_repr"].strip("'")


def real_attr(obj, name):
    """(is_really_defined, value).

    Walks __dict__/__mro__ rather than using getattr, because App and TGObject
    both vend truthy stubs from __getattr__ for undefined names -- getattr can
    never distinguish 'defined' from 'stubbed'.
    """
    if isinstance(obj, type):
        for klass in obj.__mro__:
            if name in vars(klass):
                return True, vars(klass)[name]
        return False, None
    d = vars(obj)
    return (name in d, d.get(name))


def load():
    """Partition every usable dump row against the live App shim."""
    import App

    rows = [r for r in csv.DictReader(open(CSV_PATH)) if r["name"] not in SKIP]

    # Force memoization of WC_/KY_ constants before classification.
    # App.__getattr__ memoizes them into vars(App) on first access via getattr().
    # Without this, real_attr() would report them as 'missing' until something
    # accessed them, making the audit order-dependent and non-deterministic.
    for row in rows:
        if row["scope"] == "module" and row["name"][:3] in ("WC_", "KY_"):
            getattr(App, row["name"], None)

    ok, wrong, missing, noclass = [], [], [], []
    for row in rows:
        want = parse(row)
        if row["scope"] == "module":
            have, val = real_attr(App, row["name"])
        else:
            has_cls, cls = real_attr(App, row["owner_class"])
            if not has_cls or not isinstance(cls, type):
                noclass.append((row, want, None))
                continue
            have, val = real_attr(cls, row["name"])
        bucket = ok if (have and val == want) else wrong if have else missing
        bucket.append((row, want, val))
    return rows, ok, wrong, missing, noclass
