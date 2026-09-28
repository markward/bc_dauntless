"""Dispatch engine-owned ship-data overrides after SDK module execution.

Both SDK loaders (`_SDKLoader.exec_module` in tools/mission_harness.py and its
twin in tests/conftest.py) call `on_sdk_module_exec` after executing any module
whose qualified name starts with "ships." or "Systems.". This is the second
pass of the "pre-load then override" scheme: the SDK file runs untouched, then
we extend or tweak what it produced. sdk/Build/scripts/ stays byte-identical.

Systems.<System>.<Region> -> region_hooks.on_region_module_exec (applies the
system map after the region's Initialize()).

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

    ships.Hardpoints.<leaf>  -> hardpoint_overrides.apply(<leaf>), STOCK
                                ships only; then the articulated-part
                                snapshot for every leaf
    ships.<Leaf>             -> ship_overrides.apply(module)
    Systems.<System>.<Region> -> region_hooks.on_region_module_exec(module, qualname)
        (applies the system map after the region's Initialize())
    Anything else (including the "ships" and "ships.Hardpoints" packages, the
    "Systems" and "Systems.<System>" packages, "Systems.Utils", and any
    "Systems.<System>.<Region>_S" static module) is a no-op.

    A mod-supplied ships/Hardpoints/<leaf>.py owns its ship: the Ship Property
    Viewer saves that ship's edits into the mod file itself, so the engine's
    stock override pass is skipped for it -- running apply() after the mod's
    module body would clobber those saved edits on every rebuild (spec
    2026-09-26, docs/superpowers/specs/2026-09-26-spv-save-to-mod-hardpoint-design.md).
    """
    parts = qualname.split(".")
    if parts[0] == "Systems":
        if len(parts) == 3 and not parts[2].endswith("_S"):
            from engine.systems import region_hooks
            _dispatch(region_hooks.on_region_module_exec, module, qualname)
        return
    if parts[0] != "ships" or len(parts) < 2:
        return
    if parts[1] == "Hardpoints":
        if len(parts) == 3:
            leaf = parts[2]
            from engine import mods
            if mods.sdk_override("ships/Hardpoints/%s.py" % leaf) is None:
                # Overrides are for stock ships only; a mod file owns its own.
                from engine.appc import hardpoint_overrides
                _dispatch(hardpoint_overrides.apply, leaf)
            # Snapshot after the (possible) apply(): a stock ship's parts were
            # just registered BY apply(); a modded ship's parts were just
            # registered by its own hardpoint file's module body, which has
            # just finished executing. One snapshot point covers both homes.
            from engine.appc import articulated_part
            _dispatch(articulated_part.snapshot_for_leaf, leaf)
    elif len(parts) == 2:
        from engine.appc import ship_overrides
        _dispatch(ship_overrides.apply, module)
