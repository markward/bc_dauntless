"""Case-insensitive file lookup for BC content.

BC shipped for Windows, whose filesystem ignores case, and its content leans
on that everywhere: `Bridge/GalaxyBridge.py` does `import DBridgeProperties`
while the file on disk is `dbridgeproperties.py`, then loads
"data/Models/Sets/DBridge/DBridge.nif" from a folder that holds
`Dbridge.NIF`. macOS defaults to a case-insensitive filesystem too, so only
Linux sees the mismatch.

Every path into BC content resolves through `resolve()`: both `_SDKFinder`s
(tools/mission_harness.py and tests/conftest.py, which must not drift apart
on this rule), `engine.paths.game_asset`/`game_asset_dirs`, and host_loop's
animation-clip resolver. The C++ side has its own twin in
native/src/renderer/asset_path.cc. An exact-case match is always tried first
and always preferred, so on a case-insensitive filesystem, or for a correctly
spelled path, behaviour is unchanged.
"""

import os
from pathlib import Path


def resolve(base: Path, rel: str):
    """`base / rel` if it exists, else the one existing path whose components
    match `rel` case-insensitively; None if there is neither.

    Where a directory holds several entries that fold to the same name, the
    first in sorted order wins, so the result is deterministic.
    """
    exact = base / rel
    if exact.exists():
        return exact
    cur = base
    for part in Path(rel).parts:
        if (cur / part).exists():
            cur = cur / part
            continue
        try:
            entries = sorted(os.listdir(cur))
        except OSError:
            return None
        folded = part.casefold()
        match = next((e for e in entries if e.casefold() == folded), None)
        if match is None:
            return None
        cur = cur / match
    return cur


def rglob_py(root: Path, name: str) -> list:
    """Every `<name>.py` under `root`, matched case-insensitively, sorted.

    Python 3.12+ matches case-insensitively during its own single walk; 3.11
    falls back to filtering a walk of every .py file.
    """
    pattern = f"{name}.py"
    try:
        found = root.rglob(pattern, case_sensitive=False)
    except TypeError:  # Python 3.11: no case_sensitive parameter
        target = pattern.casefold()
        found = (p for p in root.rglob("*.py") if p.name.casefold() == target)
    return sorted(found)
