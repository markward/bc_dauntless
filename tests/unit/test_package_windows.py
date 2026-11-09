"""The Microsoft C++ runtime scripts/package.py ships beside the Windows exe.

The engine is built against the shared C++ runtime (/MD, native/CMakeLists.txt),
so BC Dauntless.exe and _dauntless_host.pyd load msvcp140.dll and
vcruntime140*.dll at start-up. 0.2.1 shipped only the two vcruntime files it
found in the Python install -- Python has no msvcp140.dll -- so on a PC
without the Visual C++ Redistributable the exe refused to start with
"MSVCP140.dll was not found". The packager now copies the whole runtime
folder from Visual Studio's redist tree, and refuses to stage without it.

Staging itself needs a Windows build, so these pin the pure parts: finding
the runtime folder and copying it.
"""
import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_package():
    spec = importlib.util.spec_from_file_location(
        "dauntless_package_script_windows", PROJECT_ROOT / "scripts" / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = _load_package()

# What Visual Studio 2022's x64 runtime folder holds.
CRT_DLLS = (
    "concrt140.dll", "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
    "vccorlib140.dll", "vcruntime140.dll", "vcruntime140_1.dll",
)


def _redist_version(msvc: Path, version: str, crt: str = "Microsoft.VC143.CRT",
                    dlls=CRT_DLLS) -> Path:
    """Fake <VS>/VC/Redist/MSVC/<version>/x64/<crt>/ holding `dlls`."""
    folder = msvc / version / "x64" / crt
    folder.mkdir(parents=True)
    for name in dlls:
        (folder / name).write_bytes(b"MZ" + name.encode())
    return folder


def test_crt_dir_from_the_developer_prompt_variable(tmp_path):
    crt = _redist_version(tmp_path / "MSVC", "14.38.33135")
    env = {"VCToolsRedistDir": str(tmp_path / "MSVC" / "14.38.33135") + "\\"}
    assert package.find_msvc_crt(env, vs_install=lambda: None) == crt


def test_crt_dir_from_the_visual_studio_install(tmp_path):
    msvc = tmp_path / "VS" / "VC" / "Redist" / "MSVC"
    crt = _redist_version(msvc, "14.38.33135")
    assert package.find_msvc_crt({}, vs_install=lambda: tmp_path / "VS") == crt


def test_newest_redist_version_wins_by_number_not_by_text(tmp_path):
    msvc = tmp_path / "VS" / "VC" / "Redist" / "MSVC"
    _redist_version(msvc, "14.9.1")
    newest = _redist_version(msvc, "14.38.33135")
    # VS keeps merge modules in a non-version folder beside the versions.
    (msvc / "v143" / "MergeModules").mkdir(parents=True)
    assert package.find_msvc_crt({}, vs_install=lambda: tmp_path / "VS") == newest


def test_newest_crt_folder_wins_within_a_version(tmp_path):
    msvc = tmp_path / "MSVC"
    _redist_version(msvc, "14.44.1", crt="Microsoft.VC142.CRT")
    newest = msvc / "14.44.1" / "x64" / "Microsoft.VC143.CRT"
    newest.mkdir(parents=True)
    for name in CRT_DLLS:
        (newest / name).write_bytes(b"MZ")
    # Neither the debug runtime nor another library's folder is the CRT.
    (msvc / "14.44.1" / "x64" / "Microsoft.VC143.OpenMP").mkdir()
    env = {"VCToolsRedistDir": str(msvc / "14.44.1")}
    assert package.find_msvc_crt(env, vs_install=lambda: None) == newest


def test_a_stale_prompt_variable_falls_back_to_the_install(tmp_path):
    msvc = tmp_path / "VS" / "VC" / "Redist" / "MSVC"
    crt = _redist_version(msvc, "14.38.33135")
    env = {"VCToolsRedistDir": str(tmp_path / "gone")}
    assert package.find_msvc_crt(env, vs_install=lambda: tmp_path / "VS") == crt


def test_no_runtime_found_refuses_to_stage(tmp_path):
    with pytest.raises(SystemExit, match="Visual C\\+\\+ runtime"):
        package.find_msvc_crt({}, vs_install=lambda: None)
    with pytest.raises(SystemExit, match="Visual C\\+\\+ runtime"):
        package.find_msvc_crt({}, vs_install=lambda: tmp_path / "empty VS")


def test_stage_msvc_runtime_copies_every_dll_beside_the_exe(tmp_path):
    crt = _redist_version(tmp_path / "MSVC", "14.38.33135")
    (crt / "readme.txt").write_text("not a library")
    bin_dir = tmp_path / "BC Dauntless"
    bin_dir.mkdir()
    copied = package.stage_msvc_runtime(bin_dir, crt)
    assert copied == sorted(CRT_DLLS)
    for name in CRT_DLLS:
        assert (bin_dir / name).read_bytes() == (crt / name).read_bytes()
    assert not (bin_dir / "readme.txt").exists()


def test_stage_msvc_runtime_replaces_an_older_copy(tmp_path):
    # Python's install carries its own vcruntime140.dll, which may be older
    # than the toolset that built the exe; the redist copy must win.
    crt = _redist_version(tmp_path / "MSVC", "14.38.33135")
    bin_dir = tmp_path / "BC Dauntless"
    bin_dir.mkdir()
    (bin_dir / "vcruntime140.dll").write_bytes(b"old")
    package.stage_msvc_runtime(bin_dir, crt)
    assert (bin_dir / "vcruntime140.dll").read_bytes() == (
        crt / "vcruntime140.dll").read_bytes()


def test_stage_msvc_runtime_refuses_a_folder_without_msvcp140(tmp_path):
    crt = _redist_version(tmp_path / "MSVC", "14.38.33135",
                          dlls=("vcruntime140.dll", "vcruntime140_1.dll"))
    bin_dir = tmp_path / "BC Dauntless"
    bin_dir.mkdir()
    with pytest.raises(SystemExit, match="msvcp140.dll"):
        package.stage_msvc_runtime(bin_dir, crt)


def test_python_staging_no_longer_supplies_the_c_runtime(tmp_path, monkeypatch):
    # The runtime comes from one place only: Visual Studio's redist folder.
    home = tmp_path / "py"
    (home / "Lib").mkdir(parents=True)
    ver = "python%d%d" % package.sys.version_info[:2]
    for name in (f"{ver}.dll", "python3.dll", "vcruntime140.dll",
                 "vcruntime140_1.dll"):
        (home / name).write_bytes(b"MZ")
    monkeypatch.setattr(package, "python_home", lambda: home)
    bin_dir = tmp_path / "BC Dauntless"
    bin_dir.mkdir()
    package.stage_python(bin_dir)
    assert (bin_dir / f"{ver}.dll").is_file()
    assert (bin_dir / "python3.dll").is_file()
    assert not (bin_dir / "vcruntime140.dll").exists()
    assert not (bin_dir / "vcruntime140_1.dll").exists()
