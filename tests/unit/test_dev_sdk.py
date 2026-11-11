"""tools.dev_sdk: the developer-only SDK chain (env, settings, project)."""
import pytest

from tools import dev_sdk
from tools.dev_sdk import DevSdkMissing


class FakeStore:
    def __init__(self, sdk=None):
        self._sdk = sdk

    def has(self, section, key):
        return (section, key) == ("paths", "sdk") and self._sdk is not None

    def get(self, section, key, default=None):
        return self._sdk if self.has(section, key) else default


def _make_sdk(root):
    (root / "Build" / "scripts").mkdir(parents=True)
    (root / "Build" / "scripts" / "App.py").write_text("")
    (root / "Build" / "Data").mkdir(parents=True)
    (root / "Build" / "Data" / "TGL").write_text("")
    return root


@pytest.fixture
def empty_project(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    monkeypatch.setattr(dev_sdk, "PROJECT_ROOT", proj)
    return proj


def test_env_wins_over_settings_and_project(tmp_path, empty_project):
    env_root = _make_sdk(tmp_path / "env_sdk")
    other = _make_sdk(tmp_path / "other")
    _make_sdk(empty_project / "sdk")
    got = dev_sdk.sdk_root(env={"DAUNTLESS_SDK_DIR": str(env_root)},
                           store=FakeStore(str(other)))
    assert got == env_root


def test_settings_used_when_env_unset(tmp_path, empty_project):
    root = _make_sdk(tmp_path / "s")
    assert dev_sdk.sdk_root(env={}, store=FakeStore(str(root))) == root


def test_project_folder_is_last(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    sdk = _make_sdk(proj / "sdk")  # paths-guard: test fixture building a fake tree
    monkeypatch.setattr(dev_sdk, "PROJECT_ROOT", proj)
    assert dev_sdk.sdk_root(env={}, store=FakeStore()) == sdk


def test_missing_sdk_raises_with_the_chain_named(empty_project):
    with pytest.raises(DevSdkMissing) as ei:
        dev_sdk.sdk_root(env={}, store=FakeStore())
    msg = str(ei.value)
    assert "DAUNTLESS_SDK_DIR" in msg
    assert "settings.json [paths].sdk" in msg
    assert "required for development" in msg


def test_set_but_invalid_raises_not_falls_through(tmp_path, empty_project):
    bad = tmp_path / "empty"
    bad.mkdir()
    good = _make_sdk(tmp_path / "good")
    with pytest.raises(DevSdkMissing) as ei:
        dev_sdk.sdk_root(env={"DAUNTLESS_SDK_DIR": str(bad)},
                         store=FakeStore(str(good)))
    msg = str(ei.value)
    assert str(bad) in msg
    assert "Build/scripts/App.py" in msg


def test_empty_env_value_counts_as_unset(tmp_path, empty_project):
    good = _make_sdk(tmp_path / "good")
    assert dev_sdk.sdk_root(env={"DAUNTLESS_SDK_DIR": ""},
                            store=FakeStore(str(good))) == good


def test_scripts_and_data_derive_from_root(tmp_path, empty_project):
    root = _make_sdk(tmp_path / "s")
    env = {"DAUNTLESS_SDK_DIR": str(root)}
    assert dev_sdk.sdk_scripts(env=env, store=FakeStore()) == root / "Build" / "scripts"
    assert dev_sdk.sdk_data(env=env, store=FakeStore()) == root / "Build" / "Data"
