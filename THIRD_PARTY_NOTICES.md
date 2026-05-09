# Third-Party Notices

This project incorporates source code from the following third-party projects.

## OpenMW

`native/third_party/openmw_nif/` contains a verbatim mirror of the NIF parser
from [OpenMW](https://openmw.org/), specifically the `components/nif/`
directory. OpenMW is licensed under the GNU General Public License version 3
(GPLv3), the same license as open_stbc. Original file headers are preserved
in the mirrored source. The full OpenMW LICENSE is reproduced at
`native/third_party/openmw_nif/LICENSE`. Upstream commit SHA is recorded in
`native/third_party/openmw_nif/UPSTREAM_VERSION`.

## NifSkope

[NifSkope](https://github.com/niftools/nifskope) is used as a reference for
the NIF binary format. Its `nif.xml` schema documents block layouts. NifSkope
itself is **not** incorporated into open_stbc — it is reference documentation
only. NifSkope is licensed under a BSD-style license; see
https://github.com/niftools/nifskope/blob/develop/LICENSE.md.

## niftools/nifxml

[niftools/nifxml](https://github.com/niftools/nifxml) provides the
authoritative `nif.xml` schema. We read it as documentation; it is not
incorporated into open_stbc binaries. Permissively licensed
(GPLv3-compatible).

## niftools/niflib

[niflib](https://github.com/niftools/niflib) is the reference C++ NIF
reader/writer. We read its `src/obj/*.cpp` files as the authoritative
source for v3.1-specific reading order — the schema describes the format,
but niflib's auto-gen `Read` methods capture quirks the schema doesn't
(e.g. `bool` as "uint32 != 0" semantics for `version <= 4.1.0.1`, and
`NiMultiTextureProperty`'s actual field layout). niflib is BSD-licensed
(GPLv3-compatible); none of niflib's code is linked into open_stbc, only
read as documentation.

## stb_image (native/third_party/stb)

Single-header image loader by Sean Barrett. Used by the `assets` library
for TGA (and optionally PNG/JPEG/BMP) decoding.

- Upstream: https://github.com/nothings/stb
- Pinned commit: see `native/third_party/stb/UPSTREAM_VERSION`
- License: dual public-domain / MIT (see `LICENSE` in vendor dir)
