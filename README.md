# open_stbc

Open reimplementation of the Bridge Commander engine.

## Legal notice

This project is an independent engine reimplementation. It does not include any game assets, scripts, or content from Star Trek: Bridge Commander. A legitimate retail copy of Star Trek: Bridge Commander is required to use this software.

This project is not made by, affiliated with, or supported by Activision or Paramount.

## Setup

Drop your BC installation into `game/` and your BC SDK into `sdk/`.

```bash
uv sync
uv run pytest
```

See `docs/gap_analysis.md` for the engine gap analysis and implementation phases.

## References & acknowledgements

The Phase 2 NIF parser draws on two open-source projects:

- **[OpenMW](https://openmw.org/)** — its NIF parser
  (`components/nif/`) is mirrored into `native/third_party/openmw_nif/` and
  used as a test-only diff oracle. Many thanks to the OpenMW team for
  building and maintaining a robust, GPL-licensed NIF implementation we can
  hold our own work to.
- **[NifSkope](https://github.com/niftools/nifskope)** — its `nif.xml`
  schema is the authoritative documentation for NIF block layouts and
  explicitly includes Bridge Commander in its compatibility list. Thanks
  to the NifTools / NifSkope team for keeping the format documented.

See `THIRD_PARTY_NOTICES.md` for the formal attribution.
