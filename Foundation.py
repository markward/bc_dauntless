"""Foundation — project-root shim shadowing any mod-supplied Foundation.py.

A thin re-export; the implementation is engine/foundation/. This file exists
at the root for one reason: _SDKFinder checks PROJECT_ROOT before the mod
index, so being here is what makes ours win over a bundled copy.

Joins App.py, LoadBridge.py and LoadDamageHitSounds.py. See the
"Project-root SDK shims" section of CLAUDE.md -- this is the fourth, and
that note asks us to consider grouping them into shims/ at the third.

Spec: docs/superpowers/specs/2026-09-09-foundation-compatibility-design.md

NOTE: `load_plugins` is deliberately not imported here yet -- it is Task 4's
deliverable and does not exist on engine.foundation as of this file's
authorship (Task 5 runs before Task 4; see the plan's ruling R1). Once Task
4 lands it, `Foundation.load_plugins` still resolves correctly through the
`__getattr__` forward below without any change here.
"""
from engine.foundation import *          # noqa: F401,F403
from engine.foundation import (          # noqa: F401
    ShipDef, shipList, reset, synthesised_races,
)


def __getattr__(attr):
    # Forward <Race>ShipDef synthesis (and anything else not explicitly
    # re-exported above, e.g. load_plugins once Task 4 adds it) to the
    # engine module.
    from engine import foundation
    return getattr(foundation, attr)
