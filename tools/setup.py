"""Install the Appc logging shim into game/scripts/.

Normal mode (no flags):
  If App.pyc.bak exists, uses a timestamp trick so Python 1.5 loads the
  cached .pyc without recompiling (Python 1.5 crashes parsing the 666KB
  source). Otherwise falls through to first-install mode.

Flags:
  --recompile  Force Python 1.5 to compile App.py on next game launch.
               Removes App.pyc; preserves App.pyc.bak as fallback.
               If the game crashes, run setup.py (no flags) to restore.

  --capture    After a successful --recompile game run, call this to save
               the freshly compiled App.pyc as App.pyc.bak and re-apply
               the timestamp trick for future launches.

  --power      Install the power-drain snippet (tools/appc_power_logger.py)
               instead of the default tick/event snippet (tools/appc_logger.py).
               Combine with --recompile / --capture as usual, e.g.
                 uv run python tools/setup.py --power --recompile
"""
import os
import pathlib
import shutil
import struct
import sys

PROJECT_ROOT = pathlib.Path(__file__).parent.parent
GAME_SCRIPTS = PROJECT_ROOT / "game" / "scripts"
SDK_APP = PROJECT_ROOT / "sdk" / "Build" / "scripts" / "App.py"
SHIM_SNIPPET = PROJECT_ROOT / "tools" / "appc_logger.py"
POWER_SNIPPET = PROJECT_ROOT / "tools" / "appc_power_logger.py"
_snippet_path = SHIM_SNIPPET  # overridden by --power in main()
DEST_APP = GAME_SCRIPTS / "App.py"
DEST_PYC = GAME_SCRIPTS / "App.pyc"
DEST_PYC_BAK = GAME_SCRIPTS / "App.pyc.bak"


def build_combined() -> bytes:
    log_path = str(GAME_SCRIPTS / "tick_log.txt").replace("\\", "\\\\")
    err_path = str(GAME_SCRIPTS / "appc_error.txt").replace("\\", "\\\\")
    snippet = _snippet_path.read_text(encoding="utf-8")
    snippet = snippet.replace('"LOG_PATH"', '"%s"' % log_path)
    snippet = snippet.replace('"ERR_PATH"', '"%s"' % err_path)
    app_source = SDK_APP.read_bytes()
    return app_source + b"\n\n# === instrumentation ===\n" + snippet.encode("ascii")


def apply_timestamp_trick(combined: bytes) -> None:
    """Write App.py with mtime matching App.pyc.bak, then copy .bak as App.pyc.

    Python 1.5 checks stored_mtime == stat(App.py).st_mtime and skips
    recompilation when they match — avoiding a crash on the large source.
    """
    pyc_data = DEST_PYC_BAK.read_bytes()
    stored_mtime = struct.unpack_from("<I", pyc_data, 4)[0]
    if DEST_APP.exists():
        DEST_APP.chmod(0o666)  # game marks App.py read-only after compiling it
    DEST_APP.write_bytes(combined)
    os.utime(str(DEST_APP), (stored_mtime, stored_mtime))
    if DEST_PYC.exists():
        DEST_PYC.unlink()
    shutil.copy2(str(DEST_PYC_BAK), str(DEST_PYC))
    print("Installed: App.pyc from cached .bak (Python will skip recompilation)")
    print(f"Written:   App.py (mtime matched to .pyc)")


def main() -> None:
    global _snippet_path
    recompile = "--recompile" in sys.argv
    capture = "--capture" in sys.argv
    power = "--power" in sys.argv
    if power:
        _snippet_path = POWER_SNIPPET
        print(f"Snippet:   {POWER_SNIPPET.name} (power-drain instrumentation)")
    else:
        print(f"Snippet:   {SHIM_SNIPPET.name} (tick/event instrumentation)")

    if not GAME_SCRIPTS.exists():
        print("game/scripts/ not found - is the game installed in game/?")
        sys.exit(1)
    if not SDK_APP.exists():
        print("sdk/Build/scripts/App.py not found - is the SDK installed in sdk/?")
        sys.exit(1)

    # Remove stale files from earlier approaches.
    for stale in ("Local.py", "Local.pyc"):
        p = GAME_SCRIPTS / stale
        if p.exists():
            p.unlink()
            print(f"Removed stale: {stale}")

    combined = build_combined()

    if capture:
        # Save the freshly compiled App.pyc as .bak, then apply timestamp trick.
        if not DEST_PYC.exists():
            print("No App.pyc to capture. Run the game first (after --recompile).")
            sys.exit(1)
        shutil.copy2(str(DEST_PYC), str(DEST_PYC_BAK))
        print("Captured: App.pyc -> App.pyc.bak")
        apply_timestamp_trick(combined)

    elif recompile:
        # Force Python 1.5 to compile App.py from source on next launch.
        # Preserves App.pyc.bak so normal setup.py can restore if game crashes.
        if DEST_PYC.exists():
            DEST_PYC.unlink()
        if DEST_APP.exists():
            DEST_APP.chmod(0o666)
        DEST_APP.write_bytes(combined)
        print(f"Installed: {DEST_APP}")
        print("Removed:   App.pyc (Python will recompile on next launch)")
        print()
        print("If the game crashes: run setup.py (no flags) to restore cached .pyc.")
        print("If the game runs OK: run setup.py --capture to lock in the new .pyc.")

    elif DEST_PYC_BAK.exists():
        apply_timestamp_trick(combined)

    else:
        # First install: save original App.pyc and install source.
        if not DEST_PYC.exists():
            print("game/scripts/App.pyc missing - game installation looks incomplete.")
            sys.exit(1)
        DEST_PYC.rename(DEST_PYC_BAK)
        DEST_APP.write_bytes(combined)
        print("Saved original App.pyc as App.pyc.bak")
        print(f"Installed: {DEST_APP}")
        print()
        print("NOTE: Python 1.5 may crash parsing App.py on first launch.")
        print("If it does, try again. On success, run: setup.py --capture")

    # Clear stale log/error files.
    for name in ("tick_log.txt", "appc_error.txt"):
        p = GAME_SCRIPTS / name
        if p.exists():
            p.unlink()
            print(f"Cleared old: {name}")

    print()
    print("Next steps:")
    print("  1. Launch game/stbc.exe")
    print("  2. Start Quick Battle - play for 30+ seconds")
    print("  3. Quit the game")
    print("  4. Run: uv run python tools/analyze_session.py")
    print()
    print("To revert: uv run python tools/uninstall.py")


if __name__ == "__main__":
    main()
