"""Dispatch engine-owned ship-data overrides after SDK module execution.

Both SDK loaders (`_SDKLoader.exec_module` in tools/mission_harness.py and its
twin in tests/conftest.py) call `on_sdk_module_exec` after executing any module
whose qualified name starts with "ships.". This is the second pass of the
"pre-load then override" scheme: the SDK file runs untouched, then we extend or
tweak what it produced. sdk/Build/scripts/ stays byte-identical.

Timing matters for hardpoints: loadspacehelper.CreateShip does
ClearLocalTemplates() -> reload(mod) -> mod.LoadPropertySet(...), and
importlib.reload re-enters exec_module, so the hardpoint override pass re-fires
after every template re-registration and before LoadPropertySet consumes them.

Every dispatch is fail-soft: a missing or broken override section prints one
diagnostic line and never breaks the SDK import itself.
"""


def _dispatch(fn, *args):
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 - never break an SDK import
        print(f"[sdk-overrides] override skipped: {type(exc).__name__}: {exc}",
              flush=True)


def on_sdk_module_exec(module, qualname: str) -> None:
    """Route a just-executed SDK module to its override pass, if any.

    ships.Hardpoints.<leaf>  -> hardpoint_overrides.apply(<leaf>)
    ships.<Leaf>             -> ship_overrides.apply(module)
    Anything else (including the "ships" and "ships.Hardpoints" packages) is a
    no-op.
    """
    parts = qualname.split(".")
    if parts[0] != "ships" or len(parts) < 2:
        return
    if parts[1] == "Hardpoints":
        if len(parts) == 3:
            from engine.appc import hardpoint_overrides
            _dispatch(hardpoint_overrides.apply, parts[2])
    elif len(parts) == 2:
        from engine.appc import ship_overrides
        _dispatch(ship_overrides.apply, module)
