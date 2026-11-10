"""Missing torpedo-type constants on `Multiplayer.SpeciesToTorp` read as UNKNOWN.

Every torpedo script ends its `Create()` with
`pTorp.SetNetType(Multiplayer.SpeciesToTorp.<NAME>)`. Community packs ship an
extended copy of that SDK file with extra types, and a mod built against one
names them (the Majestic Class: `PHOTON6`, `QUANTUM2`). Without that pack
the AttributeError aborted `Create()` after the torpedo was fully built, so
the tube fired nothing and the fire key raised a traceback.

The net type only identifies a torpedo to the other machines in a BC
multiplayer game; our `Torpedo.SetNetType` ignores it. So a missing CONSTANT
(an upper-case name) reads as the module's own `UNKNOWN`, with one `[weapons]`
line naming it. Anything the module defines is untouched, a mod that ships
its own extended copy still wins, and any other missing name (lower case,
dunder, function) raises as before, so `hasattr` probes are unchanged.

Installed from `engine.appc.sdk_overrides.on_sdk_module_exec` after the SDK
(or mod) file runs; the SDK file on disk is untouched.
"""

import re

QUALNAME = "Multiplayer.SpeciesToTorp"

_CONSTANT = re.compile(r"[A-Z][A-Z0-9_]*\Z")

# Names already announced, so a tube firing every few seconds logs once.
_announced: set = set()


def install(module) -> None:
    """Give `module` a PEP 562 `__getattr__` for missing torpedo constants.

    Re-installing (importlib.reload re-runs the loader's override pass) just
    replaces the hook."""

    def __getattr__(name):
        if not _CONSTANT.match(name) or name.startswith("__"):
            raise AttributeError(
                "module %r has no attribute %r" % (module.__name__, name))
        fallback = module.__dict__.get("UNKNOWN", 0)
        if name not in _announced:
            _announced.add(name)
            print("[weapons] %s has no torpedo type %s (a mod expects an "
                  "extended copy of that file) -- using UNKNOWN; it only "
                  "matters in multiplayer" % (module.__name__, name),
                  flush=True)
        return fallback

    module.__getattr__ = __getattr__
