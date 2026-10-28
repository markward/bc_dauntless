# Third-Party Notices

BC Dauntless is licensed under the GNU General Public License version 3
(GPLv3). It includes the third-party software listed below, each under its
own license.

**In the BC Dauntless download**, the full text of every license named here
is in the `licenses` folder, under the file name given for each entry.
**In the source code**, it is at the path given in brackets.

## Included in BC Dauntless

### Python (CPython)

The game's scripting runtime: the Python interpreter and its standard
library are bundled so that no separate Python install is needed.

- Upstream: https://www.python.org/
- License: Python Software Foundation License. On Windows this file also
  covers the libraries bundled with Python itself.
- License text: `licenses/Python-LICENSE.txt` (taken from the Python
  installation the build was packaged with)

### Chromium Embedded Framework (CEF)

Off-screen browser that draws the game's interface over the 3D scene.

- Pinned version: `cef_binary_144.0.25+g27ce504+chromium-144.0.7559.250`
- Distribution: Minimal binary from https://cef-builds.spotifycdn.com/
- Upstream: https://bitbucket.org/chromiumembedded/cef
- License: BSD 3-Clause (CEF), plus the licenses of the Chromium components
  it bundles.
- License text: `licenses/CEF-LICENSE.txt` and, for Chromium's components,
  `licenses/Chromium-CREDITS.html` (`LICENSE.txt` and `CREDITS.html` in the
  CEF distribution, unpacked to `build/_deps/cef-src/` by CMake)

### OpenAL Soft

3D audio library, statically linked into the game.

- Upstream: https://github.com/kcat/openal-soft
- Pinned release: 1.23.1
- License: GNU Library General Public License version 2. The complete
  source code of BC Dauntless is available under the GPLv3, so it can be
  rebuilt against a modified OpenAL Soft.
- License text: `licenses/OpenAL-Soft-COPYING.txt` (`COPYING`, unpacked to
  `build/_deps/openal_soft-src/` by CMake)

### pybind11

Connects the C++ engine to the game's Python code.

- Upstream: https://github.com/pybind/pybind11
- Pinned release: v2.13.6
- License: BSD 3-Clause
- License text: `licenses/pybind11-LICENSE.txt` (`LICENSE`, unpacked to
  `build/_deps/pybind11-src/` by CMake)

### JSON for Modern C++ (nlohmann/json)

JSON reading and writing in the C++ engine.

- Upstream: https://github.com/nlohmann/json
- Pinned release: v3.11.3
- License: MIT
- License text: `licenses/nlohmann-json-LICENSE.txt` (`LICENSE.MIT`, unpacked
  to `build/_deps/nlohmann_json-src/` by CMake)

### GLFW

Creates the game window and its OpenGL context, and reads keyboard and
mouse input.

- Upstream: https://github.com/glfw/glfw
- Pinned release: 3.4
- License: zlib/libpng
- License text: `licenses/GLFW-LICENSE.txt`
  (`native/third_party/glfw/LICENSE.md`)

### GLAD

Generated OpenGL function loader, by David Herberth.

- Upstream: https://github.com/Dav1dde/glad / https://glad.dav1d.de/
- Generation parameters: see `native/third_party/glad/UPSTREAM_VERSION`
- License: MIT
- License text: `licenses/GLAD-LICENSE.txt` (`native/third_party/glad/LICENSE`)

### glm

Header-only math library for OpenGL, used for matrix and quaternion math.

- Upstream: https://github.com/g-truc/glm
- Pinned release: see `native/third_party/glm/UPSTREAM_VERSION`
- License: MIT (glm offers the Happy Bunny License or MIT; we use it under
  MIT)
- License text: `licenses/glm-LICENSE.txt` (`native/third_party/glm/LICENSE`)

### stb_image and stb_image_write

Single-header image loader and writer by Sean Barrett, used to read and
write textures.

- Upstream: https://github.com/nothings/stb
- Pinned versions: see `native/third_party/stb/UPSTREAM_VERSION`
- License: public domain or MIT, at your choice
- License text: `licenses/stb-LICENSE.txt` (`native/third_party/stb/LICENSE`)

### cgltf

Single-header glTF loader by Johannes Kuhlmann, used to load the generated
asteroid models.

- Upstream: https://github.com/jkuhlmann/cgltf
- Pinned release: see `native/third_party/cgltf/UPSTREAM_VERSION`
- License: MIT
- License text: `licenses/cgltf-LICENSE.txt`
  (`native/third_party/cgltf/LICENSE`)

### dr_mp3 (dr_libs)

Single-header MP3 decoder by David Reid, used for music and sound.

- Upstream: https://github.com/mackron/dr_libs
- Pinned commit: see `native/third_party/dr_libs/UPSTREAM_VERSION`
- License: public domain (Unlicense) or MIT No Attribution, at your choice
- License text: `licenses/dr_libs-LICENSE.txt`
  (`native/third_party/dr_libs/LICENSE`)

### ThorVG

Vector graphics library, used to play the animated Lottie panels on the bridge
(software rasteriser and Lottie loader only).

- Upstream: https://github.com/thorvg/thorvg
- Pinned release: see `native/third_party/thorvg/UPSTREAM_VERSION`
- License: MIT
- License text: `licenses/ThorVG-LICENSE.txt`
  (`native/third_party/thorvg/LICENSE`)

### Antonio font

Sans-serif typeface by Vernon Adams (Open Window), used for the interface
text.

- Upstream: https://github.com/google/fonts/tree/main/ofl/antonio
- License: SIL Open Font License 1.1 (OFL)
- License text: `licenses/Antonio-OFL.txt`
  (`native/assets/ui-cef/THIRD_PARTY/Antonio-OFL.txt`)

## Used as reference only

The projects below shaped how BC Dauntless reads Bridge Commander's NIF
model files. None of their code is part of the game itself.

### OpenMW

`native/third_party/openmw_nif/` in the source code contains a verbatim
mirror of the NIF parser from [OpenMW](https://openmw.org/), specifically
the `components/nif/` directory. It is kept as a reference and is not built
into the game. OpenMW is licensed under the GNU General Public License
version 3 (GPLv3), the same license as BC Dauntless. Original file headers
are preserved in the mirrored source. The full OpenMW LICENSE is reproduced
at `native/third_party/openmw_nif/LICENSE`. Upstream commit SHA is recorded
in `native/third_party/openmw_nif/UPSTREAM_VERSION`.

### NifSkope

[NifSkope](https://github.com/niftools/nifskope) is used as a reference for
the NIF binary format. Its `nif.xml` schema documents block layouts. NifSkope
itself is **not** incorporated into BC Dauntless — it is reference
documentation only. NifSkope is licensed under a BSD-style license; see
https://github.com/niftools/nifskope/blob/develop/LICENSE.md.

### niftools/nifxml

[niftools/nifxml](https://github.com/niftools/nifxml) provides the
authoritative `nif.xml` schema. We read it as documentation; it is not
incorporated into BC Dauntless binaries. Permissively licensed
(GPLv3-compatible).

### niftools/niflib

[niflib](https://github.com/niftools/niflib) is the reference C++ NIF
reader/writer. We read its `src/obj/*.cpp` files as the authoritative
source for v3.1-specific reading order — the schema describes the format,
but niflib's auto-gen `Read` methods capture quirks the schema doesn't
(e.g. `bool` as "uint32 != 0" semantics for `version <= 4.1.0.1`, and
`NiMultiTextureProperty`'s actual field layout). niflib is BSD-licensed
(GPLv3-compatible); none of niflib's code is linked into BC Dauntless, only
read as documentation.
