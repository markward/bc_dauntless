"""Developer-only access to the BC SDK tree.

The game never reads the SDK at runtime; only developers, tools and tests do
(spec docs/superpowers/specs/2026-11-11-no-sdk-runtime-design.md, decisions
4-5). This module is never imported by the game. A guard test (plan Task 8)
keeps it that way.

Chain, highest first: DAUNTLESS_SDK_DIR, settings.json [paths].sdk, then the
in-project SDK folder. A SET source that is invalid raises; it never falls
through to a lower one (same rule as engine.paths._candidate). An empty env
value counts as unset.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from engine import paths

PROJECT_ROOT = paths.PROJECT_ROOT
SDK_MARKERS: tuple[str, ...] = ("Build/scripts/App.py", "Build/Data/TGL")
ENV_VAR = "DAUNTLESS_SDK_DIR"

_CHAIN = (f"{ENV_VAR}, settings.json [paths].sdk, "
          "or the in-project SDK folder")


class DevSdkMissing(RuntimeError):
    """The SDK is a development requirement and none could be used."""


def _check(path, source: str) -> Path:
    if not str(path).strip():
        raise DevSdkMissing(
            f"The SDK path from {source} is empty. The SDK is required for "
            f"development; set {_CHAIN}.")
    root = paths.normalise(path)
    missing = [m for m in SDK_MARKERS if not (root / m).exists()]
    if missing:
        raise DevSdkMissing(
            f"The SDK path from {source} ({root}) is not a BC SDK tree: "
            f"missing {', '.join(missing)}. The SDK is required for "
            f"development; fix that source or unset it.")
    return root


def sdk_root(env: Optional[Mapping[str, str]] = None, store=None) -> Path:
    """The BC SDK root. Resolved at use, never captured."""
    if env is None:
        env = os.environ
    from_env = env.get(ENV_VAR)
    if from_env:
        return _check(from_env, ENV_VAR)

    if store is None:
        from engine.settings_store import SettingsStore
        store = SettingsStore()
        store.load()
    if store.has("paths", "sdk"):  # paths-guard: settings key, not a path
        return _check(store.get("paths", "sdk"),  # paths-guard: settings key
                      "settings.json [paths].sdk")

    project = PROJECT_ROOT / "sdk"  # paths-guard: dev SDK chain, decision 4
    if project.is_dir():
        return _check(project, "the in-project SDK folder")

    raise DevSdkMissing(
        f"No BC SDK found. The SDK is required for development; set "
        f"{ENV_VAR}, settings.json [paths].sdk, or put it in the project's "
        f"SDK folder.")


def sdk_scripts(env=None, store=None) -> Path:
    return sdk_root(env, store) / "Build" / "scripts"


def sdk_data(env=None, store=None) -> Path:
    return sdk_root(env, store) / "Build" / "Data"
