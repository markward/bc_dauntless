"""TGConfigMapping — INI-style game options storage.

SDK call sites (sdk/.../MissionLib.py, Multiplayer/MultiplayerMenus.py):

    if App.g_kConfigMapping.HasValue("Sound", "StreamVoices"):
        if App.g_kConfigMapping.GetIntValue("Sound", "StreamVoices"):
            ...
    pName = App.g_kConfigMapping.GetTGStringValue("Multiplayer Options", "Player Name")
    App.g_kConfigMapping.SetTGStringValue("Multiplayer Options", "Player Name", pNew)
    App.g_kConfigMapping.SaveConfigFile("Options.cfg")

Storage model: in-memory section -> key -> value dict.  LoadConfigFile and
SaveConfigFile read/write INI-format files (mirrors the on-disk layout the
real Appc engine uses for Options.cfg, KeyboardConfig.cfg, BCTickLog.cfg).

This class is also already used by tools/appc_logger.py for the
instrumentation snippet's BCTickLog output, so the in-memory store has to
be real (not a stub) for the existing instrumentation flow.
"""

import os
from pathlib import Path


class TGConfigMapping:
    def __init__(self):
        # section_name -> {key: value}.  Values are stored as their original
        # type (int/float/str) — typed getters coerce on read.
        self._sections: dict = {}

    # ── Existence check ─────────────────────────────────────────────────────
    def HasValue(self, section: str, key: str) -> int:
        return 1 if key in self._sections.get(section, {}) else 0

    # ── Typed getters / setters ─────────────────────────────────────────────
    def GetIntValue(self, section: str, key: str) -> int:
        try:
            return int(self._sections.get(section, {}).get(key, 0))
        except (TypeError, ValueError):
            return 0

    def SetIntValue(self, section: str, key: str, value) -> None:
        self._sections.setdefault(section, {})[key] = int(value)

    def GetFloatValue(self, section: str, key: str) -> float:
        try:
            return float(self._sections.get(section, {}).get(key, 0.0))
        except (TypeError, ValueError):
            return 0.0

    def SetFloatValue(self, section: str, key: str, value) -> None:
        self._sections.setdefault(section, {})[key] = float(value)

    def GetStringValue(self, section: str, key: str) -> str:
        return str(self._sections.get(section, {}).get(key, ""))

    def SetStringValue(self, section: str, key: str, value) -> None:
        self._sections.setdefault(section, {})[key] = str(value)

    def GetTGStringValue(self, section: str, key: str):
        """Return value as _TGString so SDK chains like .GetCString() work."""
        from engine.appc.localization import _TGString
        return _TGString(self.GetStringValue(section, key))

    def SetTGStringValue(self, section: str, key: str, value) -> None:
        # Accepts _TGString (str subclass) or plain str.
        self.SetStringValue(section, key, str(value))

    # ── Section-level introspection ─────────────────────────────────────────
    def HasSection(self, section: str) -> int:
        return 1 if section in self._sections else 0

    def GetSectionNames(self) -> tuple:
        return tuple(self._sections.keys())

    def GetKeysInSection(self, section: str) -> tuple:
        return tuple(self._sections.get(section, {}).keys())

    # ── File I/O ────────────────────────────────────────────────────────────
    def LoadConfigFile(self, filename: str) -> int:
        """Parse an INI-format file into the section/key map.

        Returns 1 on success, 0 on failure.  Existing in-memory values
        survive the load — LoadConfigFile MERGES rather than replacing,
        matching Appc behaviour where multiple .cfg files (Options.cfg
        + KeyboardConfig.cfg) are layered onto one mapping.
        """
        try:
            path = self._resolve_path(filename)
            if not path.exists():
                return 0
            current_section = ""
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith(";"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current_section = line[1:-1].strip()
                    self._sections.setdefault(current_section, {})
                    continue
                if "=" in line:
                    key, _, value = line.partition("=")
                    self._sections.setdefault(current_section, {})[key.strip()] = value.strip()
            return 1
        except Exception:
            return 0

    def SaveConfigFile(self, filename: str) -> int:
        """Serialise the section/key map to an INI-format file.

        Returns 1 on success, 0 on failure.  The output matches the on-disk
        layout the real game's Options.cfg uses, so files written here can
        be read back by the original engine if it ever runs the same path.
        """
        try:
            path = self._resolve_path(filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            lines = []
            for section, kv in self._sections.items():
                lines.append(f"[{section}]")
                for key, value in kv.items():
                    lines.append(f"{key}={value}")
                lines.append("")
            path.write_text("\n".join(lines))
            return 1
        except Exception:
            return 0

    def _resolve_path(self, filename: str) -> Path:
        """Anchor relative filenames to the project working directory.

        SDK callers pass bare filenames ("Options.cfg", "BCTickLog.cfg") —
        the original engine writes those next to the running .exe; the
        headless harness writes them next to the project root so the
        instrumentation tooling and tests can find them.
        """
        p = Path(filename.replace("\\", "/"))
        if p.is_absolute():
            return p
        return Path.cwd() / p
