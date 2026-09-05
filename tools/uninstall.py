"""Remove the instrumentation shim and restore a working App.pyc.

Note: the original App.pyc shipped with the game is gone if setup.py
was run more than once. App.pyc.bak now holds our compiled instrumented
bytecode (instrumentation is a no-op since file I/O fails silently).
To fully restore the original game, reinstall it.
"""
import shutil
import sys

from engine import paths

GAME_SCRIPTS = paths.game_asset("scripts")
DEST_APP = GAME_SCRIPTS / "App.py"
DEST_PYC = GAME_SCRIPTS / "App.pyc"
DEST_PYC_BAK = GAME_SCRIPTS / "App.pyc.bak"


def main() -> None:
    if DEST_APP.exists():
        DEST_APP.unlink()
        print(f"Removed: App.py")

    if DEST_PYC.exists():
        DEST_PYC.unlink()
        print(f"Removed: App.pyc")

    if DEST_PYC_BAK.exists():
        # Copy (not rename) so .bak is preserved for future setup.py runs.
        shutil.copy2(str(DEST_PYC_BAK), str(DEST_PYC))
        print("Restored: App.pyc from App.pyc.bak")
    else:
        print("Warning: App.pyc.bak not found - game cannot start without App.pyc.")
        print("Reinstall the game to get a clean App.pyc.")
        sys.exit(1)

    print("Done.")


if __name__ == "__main__":
    main()
