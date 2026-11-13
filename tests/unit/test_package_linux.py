"""The Linux layout scripts/package.py stages.

Staging itself needs a Linux build and binutils (ldd, strip), so these pin
the pure parts: the artefact's name, where the binary goes, and the two
facts read off the build tree.
"""
import importlib.util
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_package():
    spec = importlib.util.spec_from_file_location(
        "dauntless_package_script_linux", PROJECT_ROOT / "scripts" / "package.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


package = _load_package()

LDD = """\tlinux-vdso.so.1 (0x00007ffd5e9f2000)
\tlibpython3.14.so.1.0 => /lib64/libpython3.14.so.1.0 (0x00007fcb60661000)
\tlibcef.so => /home/x/bc_dauntless/build/libcef.so (0x00007fcb51a00000)
\tlibc.so.6 => /lib64/libc.so.6 (0x00007fcb51400000)
"""


def test_platform_tag_names_linux():
    assert package.platform_tag("linux") == "linux-x64"
    assert package.zip_name("0.3.2", "linux-x64") == "BC-Dauntless-0.3.2-linux-x64.zip"


def test_app_binary_sits_at_the_install_root_without_an_extension():
    app = Path("/d/BC Dauntless")
    assert package.app_binary(app, "linux") == app / "BC Dauntless"


def test_ldd_libpython_is_the_resolved_path():
    assert package.ldd_libpython(LDD) == Path("/lib64/libpython3.14.so.1.0")


def test_ldd_libpython_refuses_a_missing_library():
    with pytest.raises(SystemExit, match="not found"):
        package.ldd_libpython("\tlibpython3.14.so.1.0 => not found\n")


def test_ldd_libpython_refuses_a_binary_without_one():
    with pytest.raises(SystemExit, match="libpython"):
        package.ldd_libpython("\tlibc.so.6 => /lib64/libc.so.6 (0x0)\n")


@pytest.mark.parametrize("name", [
    "libcef.so", "libvulkan.so.1", "resources.pak", "icudtl.dat",
    "v8_context_snapshot.bin", "vk_swiftshader_icd.json"])
def test_cef_runtime_files_are_shipped(name):
    assert package.is_linux_runtime_file(name)


@pytest.mark.parametrize("name", [
    "dauntless", "build.ninja", "CMakeCache.txt", "run2.log", "first-run.log"])
def test_build_tree_clutter_is_not(name):
    assert not package.is_linux_runtime_file(name)


def test_stdlib_keeps_sourceless_bytecode():
    # Fedora ships encodings/cp1252.pyc with no cp1252.py.
    names = ["cp1252.pyc", "utf_8.py", "utf_8.pyc", "__pycache__", "x.pyo"]
    assert package.linux_stdlib_ignore("encodings", names) == {
        "utf_8.pyc", "__pycache__", "x.pyo"}


def test_stdlib_skip_lists_still_apply():
    names = ["test", "tkinter", "site-packages", "os.py"]
    assert package.linux_stdlib_ignore("lib", names) == {
        "test", "tkinter", "site-packages"}
