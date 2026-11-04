"""The macOS .app layout scripts/package.py stages.

Staging itself needs a Release build and macOS's own tools (otool,
install_name_tool, codesign), so these pin the pure parts: the bundle's
shape, its Info.plists, and the two facts read out of the built binary.
"""
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_package():
    spec = importlib.util.spec_from_file_location(
        "dauntless_package_script_macos", PROJECT_ROOT / "scripts" / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = _load_package()

OTOOL_L = """build/dauntless:
\t/Users/x/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none/lib/libpython3.11.dylib (compatibility version 3.11.0, current version 3.11.0)
\t/System/Library/Frameworks/AppKit.framework/Versions/C/AppKit (compatibility version 45.0.0, current version 2685.60.104)
\t/usr/lib/libc++.1.dylib (compatibility version 1.0.0, current version 2100.43.0)
"""

OTOOL_LOAD_COMMANDS = """Load command 10
      cmd LC_BUILD_VERSION
  cmdsize 32
 platform 1
    minos 12.0
      sdk 26.5
"""


def test_platform_tag_names_the_os_and_arch():
    assert package.platform_tag("win32") == "windows-x64"
    assert package.platform_tag("darwin") == "macos-arm64"


def test_zip_name_carries_version_and_platform():
    assert (package.zip_name("0.2.0", "macos-arm64")
            == "BC-Dauntless-0.2.0-macos-arm64.zip")


def test_linked_libpython_is_read_from_otool():
    assert package.linked_libpython(OTOOL_L) == Path(
        "/Users/x/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none"
        "/lib/libpython3.11.dylib")


def test_linked_libpython_refuses_a_binary_without_one():
    import pytest
    with pytest.raises(SystemExit, match="libpython"):
        package.linked_libpython("build/dauntless:\n\t/usr/lib/libc++.1.dylib (x)\n")


def test_min_macos_is_the_binarys_deployment_target():
    assert package.macos_min_version(OTOOL_LOAD_COMMANDS) == "12.0"


def test_declared_min_macos_is_never_below_the_floor():
    assert package.declared_min_macos("12.0") == package.MACOS_FLOOR == "26.0"
    assert package.declared_min_macos("26.1") == "26.1"
    assert package.declared_min_macos("100.0") == "100.0"


def test_app_binary_per_platform():
    app = Path("/d/BC Dauntless.app")
    assert package.app_binary(app, "darwin") == app / "Contents" / "MacOS" / "BC Dauntless"
    win = Path("/d/BC Dauntless")
    assert package.app_binary(win, "win32") == win / "BC Dauntless.exe"


def test_helper_apps_are_the_ones_chromium_derives():
    # Chromium appends these suffixes to the plain helper's name once it knows
    # it is bundled; a missing variant is a helper that never starts.
    assert package.macos_helper_names() == [
        "BC Dauntless Helper",
        "BC Dauntless Helper (Alerts)",
        "BC Dauntless Helper (GPU)",
        "BC Dauntless Helper (Plugin)",
        "BC Dauntless Helper (Renderer)",
    ]


def test_main_info_plist():
    plist = package.info_plist("BC Dauntless", "0.2.0", "12.0", icon="dauntless")
    assert plist["CFBundleExecutable"] == "BC Dauntless"
    assert plist["CFBundleIdentifier"] == "com.markward.bcdauntless"
    assert plist["CFBundleShortVersionString"] == "0.2.0"
    assert plist["CFBundleVersion"] == "0.2.0"
    assert plist["CFBundlePackageType"] == "APPL"
    assert plist["LSMinimumSystemVersion"] == "12.0"
    assert plist["LSArchitecturePriority"] == ["arm64"]
    assert plist["NSHighResolutionCapable"] is True
    assert plist["CFBundleIconFile"] == "dauntless"
    assert "LSUIElement" not in plist


def test_helper_info_plist_stays_out_of_the_dock():
    plist = package.info_plist("BC Dauntless Helper (GPU)", "0.2.0", "12.0")
    assert plist["CFBundleExecutable"] == "BC Dauntless Helper (GPU)"
    assert plist["CFBundleIdentifier"] == "com.markward.bcdauntless.helper.gpu"
    assert plist["LSUIElement"] is True
    assert "CFBundleIconFile" not in plist


def test_helper_bundle_ids_are_distinct():
    ids = {package.info_plist(n, "0.2.0", "12.0")["CFBundleIdentifier"]
           for n in package.macos_helper_names()}
    assert len(ids) == len(package.macos_helper_names())
