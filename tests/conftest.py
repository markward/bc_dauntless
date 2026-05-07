import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
SDK_SCRIPTS = PROJECT_ROOT / "sdk" / "Build" / "scripts"


def pytest_configure(config):
    # Our App.py must shadow sdk/Build/scripts/App.py
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    if str(SDK_SCRIPTS) not in sys.path:
        sys.path.append(str(SDK_SCRIPTS))

    # Stub out SDK modules that MissionLib imports but we don't implement yet
    _stub_modules = [
        "loadspacehelper",
        "Bridge",
        "Bridge.TacticalCharacterHandlers",
        "Bridge.HelmCharacterHandlers",
        "Bridge.XOCharacterHandlers",
        "Bridge.ScienceCharacterHandlers",
        "Bridge.EngineerCharacterHandlers",
        "BridgeHandlers",
        "Actions",
        "Actions.MissionScriptActions",
    ]
    for name in _stub_modules:
        if name not in sys.modules:
            sys.modules[name] = types.ModuleType(name)
