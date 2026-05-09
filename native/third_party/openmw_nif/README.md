# Mirrored OpenMW NIF parser

This directory is a verbatim mirror of `components/nif/` from
[OpenMW](https://openmw.org/), used **only** by the test-side diff oracle in
`nif_tests`. It is never linked into the public `nif` library.

**Do not edit files here directly.** To update the mirror, modify upstream
OpenMW (or, for local divergence, drop a `.patch` file into `patches/`) then
run `tools/sync_openmw_nif.sh` from the project root. The script re-syncs
files, records the upstream commit SHA in `UPSTREAM_VERSION`, and re-applies
patches.

License: GPLv3 (see `LICENSE`). Original file headers are preserved.
