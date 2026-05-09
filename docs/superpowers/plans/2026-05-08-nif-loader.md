# NIF Loader Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## v3.1 amendment (post-Task-4)

Task 4 discovered that **BC uses NIF v3.1** (older than OpenMW supports). The
diff-oracle approach as originally planned is not viable. The user-approved
mitigation is **snapshot tests + a structural block-walker oracle**. Apply
these changes when reading the rest of the plan:

- **Drop the OpenMW oracle relationship in CMake.** The `openmw_nif_oracle`
  and `openmw_nif_dump_canonical` targets are not built. The mirror in
  `native/third_party/openmw_nif/` stays committed as algorithmic reference
  but is not compiled. Remove its `add_subdirectory(third_party/openmw_nif)`
  from `native/CMakeLists.txt` if/when it would be added.
- **Task 6 is dropped entirely.** A "structural walker" oracle was
  considered but isn't viable: v3.1 files store no block-size info anywhere,
  so block boundaries are only knowable by parsing each block to its end. A
  walker would have to be the parser itself. **Skip Task 6 — proceed
  directly from Task 5 to Task 7.**
- **Replace Task 20 (diff harness)** with a snapshot-test harness. For each
  sample file: our parser produces a canonical-text dump that is compared
  against a committed `<sample>.golden.txt`. There is also one sanity
  assertion per file: parsing reaches the `"End Of File"` sentinel block
  (which closes every BC NIF) and consumes all bytes. A misread block-body
  length anywhere desyncs parsing and fails this check, so it catches whole
  categories of structural bugs cheaply. Golden files are validated once by
  hand using a hex viewer + nifxml schema.
- **Header parsing (Task 16) targets v3.1's format:** several lines of
  vendor text each ending in `\n` (line 1 is `"NetImmerse File Format,
  Version 3.1"`, then studio/copyright lines), 4-byte version, no
  block-type table, no block-size table, no string table. Blocks are
  walked linearly, each prefixed with `uint32_t name_length` + that many
  ASCII bytes naming the block type, then the block body. Loop terminates
  on the `"End Of File"` block.
- **Block dispatch (Task 18)** keys on the inline type-name string read at
  each block boundary, not on a header table.
- **Resolver (Task 17)** still applies — block-index references between
  blocks exist in v3.1 too, just as 32-bit signed offsets.
- **Task 13's BC version constants** are `kBcVersionValue = 0x03010000`
  (subject to confirmation when the inventory tool first reads it). The
  user-version concept doesn't apply to v3.x; that field is absent.

**Goal:** Build a fresh C++20 NIF parser library that reads four BC sample files (Galaxy ship, CardStarbase, BodyKlingon, EBridge interior) end-to-end, validated by a structural block-walker (offsets/types/sizes) and snapshot tests on canonical-text dumps.

**Architecture:** New `native/src/nif/` static library with a `std::variant`-based block representation, hand-written block parsers using `nifxml/nif.xml` as schema and OpenMW's `components/nif/` (mirrored at `native/third_party/openmw_nif/`, retained as documentation only — not built) as algorithmic reference. NIF format target is v3.1 specifically. Correctness via two layers: a structural block-walker confirms every block boundary, and snapshot tests on canonical-text dumps catch field-level regressions.

**Tech Stack:** C++20, CMake 3.20+, GoogleTest, Python 3.11+ for the one-off block-type inventory tool. NIF schema lives at sibling clone `/Users/mward/Documents/Projects/nifxml/nif.xml`. macOS + Linux supported; Windows is bonus.

**Spec reference:** [docs/superpowers/specs/2026-05-08-nif-loader-design.md](../specs/2026-05-08-nif-loader-design.md) — see v3.1 amendment section at the top of that file.

---

## File Map

**Created (new):**

- `THIRD_PARTY_NOTICES.md` — project-root attribution for mirrored OpenMW NIF parser.
- `native/CMakeLists.txt` — top-level native build, declares subdirectories.
- `native/src/nif/CMakeLists.txt` — builds the `nif` static library.
- `native/src/nif/include/nif/types.h` — `Vec3`, `Vec4`, `Quat`, `Mat3x3`, `Color3`, `Color4`, `BlockId`, `StringRef`.
- `native/src/nif/include/nif/version.h` — `Version` struct, `is_bc(Version)` declaration.
- `native/src/nif/include/nif/block.h` — `Block` `std::variant`, `BlockHandle` struct.
- `native/src/nif/include/nif/file.h` — `File` struct, `load(path)` declaration.
- `native/src/nif/include/nif/error.h` — `ParseError`, `UnknownBlockType`, `TruncatedBlock`, `VersionMismatch`.
- `native/src/nif/src/reader.h` / `reader.cc` — `Reader` class: bounds-checked little-endian byte reader.
- `native/src/nif/src/file.cc` — `nif::load` entry point, dispatch table.
- `native/src/nif/src/resolver.cc` — converts cross-block indices to `BlockHandle`s.
- `native/src/nif/src/blocks/ni_node.cc` — NiNode (and any BC variants).
- `native/src/nif/src/blocks/ni_tri_shape.cc` — NiTriShape, NiTriShapeData.
- `native/src/nif/src/blocks/property.cc` — NiTexturingProperty, NiSourceTexture, NiMaterialProperty, NiAlphaProperty, NiVertexColorProperty, NiZBufferProperty, NiSpecularProperty.
- `native/src/nif/src/blocks/skinning.cc` — NiSkinInstance, NiSkinData, NiSkinPartition.
- `native/src/nif/src/blocks/<additional>.cc` — created on demand per Task 27 (manifest-driven gap-fill).
- `native/src/nif/docs/v1_block_manifest.md` — generated by `tools/list_nif_blocks.py`, committed.
- `native/src/nif/docs/v1_omitted_blocks.md` — Morrowind-only blocks deliberately skipped.
- `native/src/nif/docs/canonical_dump_format.md` — text format spec.
- `native/third_party/openmw_nif/CMakeLists.txt` — builds `openmw_nif_oracle` static lib.
- `native/third_party/openmw_nif/README.md`, `LICENSE`, `UPSTREAM_VERSION`, `patches/` — mirror metadata.
- `native/third_party/openmw_nif/*.cpp` / `*.hpp` — verbatim mirror of OpenMW's `components/nif/`, file headers preserved.
- `native/tests/CMakeLists.txt` — builds `nif_tests` GTest binary.
- `native/tests/nif/canonical_dump.h` / `.cc` — `nif::test::dump_canonical(File, ostream)`.
- `native/tests/nif/openmw_canonical_dump.cc` — wraps OpenMW's `Nif::NIFFile` in the same format.
- `native/tests/nif/header_test.cc` — header-level sanity per sample file.
- `native/tests/nif/diff_harness_test.cc` — parameterized over four sample files, compares dumps.
- `native/tests/nif/bc_block_test.cc` — one test per BC-specific block (added during manifest gap-fill).
- `native/tests/nif/resolver_test.cc` — synthetic in-memory NIFs.
- `native/tests/nif/error_test.cc` — synthetic malformed inputs.
- `native/tests/nif/sample_paths.h` — relative paths to the four sample NIFs + `GTEST_SKIP` helper.
- `tools/list_nif_blocks.py` — block-type inventory tool.
- `tools/sync_openmw_nif.sh` — re-mirror script.

**Modified (existing):**

- `CMakeLists.txt` (project root) — already calls `add_subdirectory(native)`. No changes; native subtree expands.
- `README.md` — add "References & acknowledgements" section.

---

## Block-parser recipe

Tasks 21–27 implement block parsers. Each follows this pattern. The recipe is documented here once; tasks reference it by name (e.g., "apply the block-parser recipe").

**Per-block deliverables:**

1. **Header struct** in `nif/block.h`. Add the new struct and append it to the `Block` `std::variant`. Field types come from NifSkope's `nif.xml` (read at `/Users/mward/Documents/Projects/nifskope/build/nif.xml` or the equivalent installed location — locate during Task 4) cross-referenced with OpenMW's parsing of the same block in `native/third_party/openmw_nif/<file>.cpp`.

2. **Parser function** `Block parse_<block_name>(Reader&, const HeaderInfo&)` in the appropriate `blocks/<group>.cc`. Reads each field from the Reader in declaration order. Cross-block references are read as raw `BlockId` (`int32_t`) — the resolver pass converts them to `BlockHandle`s later. The parser must consume *exactly* the bytes claimed in the block-size table (verified by an assertion at the end).

3. **Dispatch registration** in `file.cc`'s static dispatch table:
   ```cpp
   {"<NiBlockTypeName>", &parse_<block_name>},
   ```

4. **Canonical-dump emitter** in `tests/nif/canonical_dump.cc`. Format documented in `canonical_dump_format.md` (see Task 13). Each emitter is a `void emit_<BlockName>(const <BlockName>&, std::ostream&, int indent)` function, called from a central `std::visit` dispatch.

5. **OpenMW-side emitter** in `tests/nif/openmw_canonical_dump.cc` — same format, wraps OpenMW's record types. Required only for blocks OpenMW also handles. For BC-specific blocks, no OpenMW emitter exists; the diff harness sees `UnknownBlockType` from OpenMW and treats it as "expected divergence."

6. **Test:** load the relevant sample file, navigate to a known instance of the block, assert at least one non-trivial field. Expected values come from cross-referencing the file in NifSkope (a manual step done while writing the test, with the value committed inline).

**Per-block test naming convention:** `TEST(<BlockName>, <SampleFile>_<DescriptiveAssertion>)`, e.g. `TEST(NiNode, GalaxyRootHasExpectedChildCount)`.

---

## Phase A — Setup

### Task 1: Project-root attribution and README acknowledgements

**Files:**
- Create: `THIRD_PARTY_NOTICES.md`
- Modify: `README.md` (append section)

- [ ] **Step 1: Create `THIRD_PARTY_NOTICES.md`**

```markdown
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
```

- [ ] **Step 2: Add acknowledgements to `README.md`**

Append (after existing content):

```markdown

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
```

- [ ] **Step 3: Commit**

```bash
git add THIRD_PARTY_NOTICES.md README.md
git commit -m "docs(nif): third-party attribution for OpenMW + NifSkope"
```

---

### Task 2: Re-mirror script

**Files:**
- Create: `tools/sync_openmw_nif.sh`

- [ ] **Step 1: Write the script**

```bash
#!/usr/bin/env bash
# tools/sync_openmw_nif.sh
# Re-mirror native/third_party/openmw_nif/ from a sibling clone of OpenMW.
# Run this only when intentionally updating to a new OpenMW commit.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OPENMW_DIR="${OPENMW_DIR:-$PROJECT_ROOT/../openmw}"
MIRROR_DIR="$PROJECT_ROOT/native/third_party/openmw_nif"

if [[ ! -d "$OPENMW_DIR/.git" ]]; then
  echo "error: $OPENMW_DIR is not a git checkout" >&2
  exit 1
fi

if ! git -C "$OPENMW_DIR" diff --quiet || ! git -C "$OPENMW_DIR" diff --cached --quiet; then
  echo "error: $OPENMW_DIR has uncommitted changes" >&2
  exit 1
fi

UPSTREAM_SHA="$(git -C "$OPENMW_DIR" rev-parse HEAD)"
SRC="$OPENMW_DIR/components/nif/"

mkdir -p "$MIRROR_DIR"

# Mirror only .cpp/.hpp/.h files. Preserve patches/ and our metadata.
rsync -av --delete \
  --include='*.cpp' --include='*.hpp' --include='*.h' \
  --exclude='*' \
  "$SRC" "$MIRROR_DIR/"

# Copy upstream LICENSE if present at OpenMW root.
if [[ -f "$OPENMW_DIR/LICENSE" ]]; then
  cp "$OPENMW_DIR/LICENSE" "$MIRROR_DIR/LICENSE"
fi

echo "$UPSTREAM_SHA" > "$MIRROR_DIR/UPSTREAM_VERSION"

# Re-apply local patches if any.
if compgen -G "$MIRROR_DIR/patches/*.patch" > /dev/null; then
  for p in "$MIRROR_DIR"/patches/*.patch; do
    echo "Applying $p"
    git apply --directory="native/third_party/openmw_nif" "$p"
  done
fi

echo "Mirrored OpenMW NIF parser at $UPSTREAM_SHA into $MIRROR_DIR"
echo "Commit with: git add $MIRROR_DIR && git commit -m 'chore: sync openmw_nif from $UPSTREAM_SHA'"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x tools/sync_openmw_nif.sh
```

- [ ] **Step 3: Commit**

```bash
git add tools/sync_openmw_nif.sh
git commit -m "tools(nif): sync_openmw_nif.sh for OpenMW mirror updates"
```

---

### Task 3: Initial OpenMW NIF mirror

**Files:**
- Create: `native/third_party/openmw_nif/` (30 .cpp/.hpp files + LICENSE + UPSTREAM_VERSION + README.md + empty patches/)

- [ ] **Step 1: Verify OpenMW sibling is clean**

```bash
git -C ../openmw status
```

Expected: `nothing to commit, working tree clean`. If dirty, stop and ask the user.

- [ ] **Step 2: Create README + empty patches dir**

```bash
mkdir -p native/third_party/openmw_nif/patches
touch native/third_party/openmw_nif/patches/.gitkeep
```

Create `native/third_party/openmw_nif/README.md`:

```markdown
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
```

- [ ] **Step 3: Run the mirror script**

```bash
./tools/sync_openmw_nif.sh
```

Expected: prints `Mirrored OpenMW NIF parser at <sha> into ...`. Verify the directory now contains 30 .cpp/.hpp files plus `LICENSE` and `UPSTREAM_VERSION`.

- [ ] **Step 4: Commit**

```bash
git add native/third_party/openmw_nif/
git commit -m "chore(nif): initial mirror of openmw/components/nif/"
```

---

### Task 4: Locate NifSkope `nif.xml`

**Files:**
- Modify: `native/src/nif/docs/canonical_dump_format.md` (creation deferred to Task 13; no file change here, just documentation gathering)

- [ ] **Step 1: Find `nif.xml` in the cloned NifSkope tree**

```bash
find /Users/mward/Documents/Projects/nifskope -name "nif.xml" 2>/dev/null
```

If the file is missing (e.g. NifSkope's submodule wasn't initialized), run:

```bash
git -C /Users/mward/Documents/Projects/nifskope submodule update --init --recursive
find /Users/mward/Documents/Projects/nifskope -name "nif.xml" 2>/dev/null
```

Record the absolute path. It will be referenced by every block-parser task.

- [ ] **Step 2: Verify Bridge Commander is named in the schema**

```bash
grep -i "bridge commander\|bridge_commander\|bcommander" $(find /Users/mward/Documents/Projects/nifskope -name "nif.xml") | head -5
```

Expected: at least one match. This confirms BC's NIF version is documented in NifSkope's schema (resolves part of OQ-3.1 from `gap_analysis.md` before we even start parsing).

If no match: stop and report. The risk in `2026-05-08-nif-loader-design.md` (BC version isn't in OpenMW's supported set) becomes more likely; we may need to switch diff strategy. Discuss with the user before proceeding.

- [ ] **Step 3: No commit (information-gathering step only)**

---

### Task 5: Native build scaffolding — empty `nif` library compiles

**Files:**
- Create: `native/CMakeLists.txt`
- Create: `native/src/nif/CMakeLists.txt`
- Create: `native/src/nif/src/empty.cc` (placeholder so the static lib has at least one TU)

- [ ] **Step 1: Write `native/CMakeLists.txt`**

```cmake
cmake_minimum_required(VERSION 3.20)
# Native subtree of open_stbc: Phase 2 C++ engine.

# C++20 across the whole subtree.
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Warnings — treat as project-wide default.
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  add_compile_options(-Wall -Wextra -Wpedantic -Wno-unused-parameter)
endif()

# Public library.
add_subdirectory(src/nif)

# Tests + oracle. Off by default in a release config; on for dev/CI.
option(OPEN_STBC_BUILD_TESTS "Build native tests for open_stbc" ON)
if(OPEN_STBC_BUILD_TESTS)
  enable_testing()
  add_subdirectory(third_party/openmw_nif)
  add_subdirectory(tests)
endif()
```

- [ ] **Step 2: Write `native/src/nif/CMakeLists.txt`**

```cmake
add_library(nif STATIC
    src/empty.cc
)

target_include_directories(nif
    PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}/include
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}/src
)

target_compile_features(nif PUBLIC cxx_std_20)
```

- [ ] **Step 3: Write `native/src/nif/src/empty.cc`**

```cpp
// Placeholder TU so the `nif` static library has at least one source file
// before any block parsers are added. Removed in Task 14.
namespace nif { void _placeholder_anchor() {} }
```

- [ ] **Step 4: Configure and build**

```bash
cmake -S . -B build -DOPEN_STBC_BUILD_TESTS=OFF
cmake --build build -j
```

Expected: succeeds, produces `build/native/src/nif/libnif.a` (or `.lib` on Windows). If `OPEN_STBC_BUILD_TESTS=OFF` is needed because Task 6 hasn't created `tests/CMakeLists.txt` yet — fine, that's why this task explicitly disables tests.

- [ ] **Step 5: Commit**

```bash
git add native/CMakeLists.txt native/src/nif/CMakeLists.txt native/src/nif/src/empty.cc
git commit -m "build(nif): native scaffolding, empty nif static library compiles"
```

---

### Task 6: OpenMW oracle CMake target — confirm it compiles

**Files:**
- Create: `native/third_party/openmw_nif/CMakeLists.txt`

- [ ] **Step 1: Write the target**

```cmake
# Builds the mirrored OpenMW NIF parser as a static library, used only by
# nif_tests as the diff oracle. Never linked into `nif` itself.

file(GLOB OPENMW_NIF_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/*.cpp"
)

add_library(openmw_nif_oracle STATIC ${OPENMW_NIF_SOURCES})

target_include_directories(openmw_nif_oracle
    PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}
)

target_compile_features(openmw_nif_oracle PUBLIC cxx_std_20)

# OpenMW headers may use slightly older C++ idioms; suppress some warnings.
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  target_compile_options(openmw_nif_oracle PRIVATE
      -Wno-unused-parameter
      -Wno-unused-variable
      -Wno-deprecated-declarations
  )
endif()
```

- [ ] **Step 2: Try to build**

```bash
cmake -S . -B build -DOPEN_STBC_BUILD_TESTS=ON
cmake --build build --target openmw_nif_oracle -j
```

**Expected outcome A (clean compile):** target builds. Skip to Step 4.

**Expected outcome B (compile errors about missing OpenMW headers — `components/misc/`, `components/files/`, `components/debug/`, etc.):** the oracle has transitive dependencies. This was anticipated in the design's risks table.

- [ ] **Step 3 (only if Step 2 failed): Mirror additional OpenMW headers**

For each missing header reported by the compiler:

1. Locate it in `../openmw/components/`.
2. Mirror only the headers that are actually required (not full directories — cherry-pick).
3. Place them under `native/third_party/openmw_nif/_deps/<component>/`.
4. Add `target_include_directories(openmw_nif_oracle PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/_deps)` to the CMakeLists.
5. Update `THIRD_PARTY_NOTICES.md` to mention the additional files.
6. Re-run Step 2.

If a transitive dependency is non-trivial (e.g., `components/files/` pulls in Boost.filesystem which we don't want), stub it: create a minimal header at `_deps/<component>/<file>.hpp` that supplies only the symbols the OpenMW NIF parser uses, sufficient to satisfy the linker. Stub creation is a discovery process — keep iterating until `openmw_nif_oracle` builds.

Commit additional mirrored or stubbed files with: `git commit -m "chore(nif): mirror additional OpenMW headers required by oracle"`

- [ ] **Step 4: Commit the CMakeLists**

```bash
git add native/third_party/openmw_nif/CMakeLists.txt
git commit -m "build(nif): openmw_nif_oracle target compiles standalone"
```

---

### Task 7: GTest setup, empty `nif_tests` binary

**Files:**
- Create: `native/tests/CMakeLists.txt`
- Create: `native/tests/nif/sanity_test.cc` (placeholder until real tests arrive)

- [ ] **Step 1: Pull in GoogleTest via FetchContent**

Write `native/tests/CMakeLists.txt`:

```cmake
include(FetchContent)
FetchContent_Declare(
    googletest
    GIT_REPOSITORY https://github.com/google/googletest.git
    GIT_TAG        v1.14.0
)
set(gtest_force_shared_crt ON CACHE BOOL "" FORCE)
FetchContent_MakeAvailable(googletest)

include(GoogleTest)

add_executable(nif_tests
    nif/sanity_test.cc
)

target_link_libraries(nif_tests
    PRIVATE
        nif
        openmw_nif_oracle
        GTest::gtest_main
)

target_include_directories(nif_tests
    PRIVATE
        ${CMAKE_CURRENT_SOURCE_DIR}
)

gtest_discover_tests(nif_tests)
```

- [ ] **Step 2: Write the placeholder test**

```cpp
// native/tests/nif/sanity_test.cc
#include <gtest/gtest.h>

TEST(NifTestsBuild, GTestRuns) {
    EXPECT_EQ(1 + 1, 2);
}
```

- [ ] **Step 3: Build and run**

```bash
cmake -S . -B build -DOPEN_STBC_BUILD_TESTS=ON
cmake --build build -j
ctest --test-dir build --output-on-failure
```

Expected: `1 + 1 == 2` test passes. GTest discovery emits `[ RUN ] NifTestsBuild.GTestRuns`.

- [ ] **Step 4: Commit**

```bash
git add native/tests/CMakeLists.txt native/tests/nif/sanity_test.cc
git commit -m "build(nif): GTest scaffolding, nif_tests binary builds and runs"
```

---

## Phase B — Block-type inventory

### Task 8: `tools/list_nif_blocks.py`

**Files:**
- Create: `tools/list_nif_blocks.py`

- [ ] **Step 1: Implement the inventory tool**

```python
#!/usr/bin/env python3
"""
list_nif_blocks.py — list every block type used across a set of NIF files.

NIF format (versions ~v3-v20) starts with:
  - magic header line (length-prefixed string ending with \\x0A on older
    versions, fixed-width on newer)
  - 4-byte version number (LE)
  - in v10+, 4 more header bytes (endian byte + user-version)
  - block-type table: count (uint32) followed by `count` length-prefixed
    block-type strings

This tool reads only enough of each file to extract the block-type table
and prints a sorted, deduplicated summary. It is deliberately tolerant:
files it can't parse are reported but don't abort the run.
"""

from __future__ import annotations

import argparse
import struct
import sys
from collections import defaultdict
from pathlib import Path


def read_string(buf, offset, length_bytes=4):
    length = int.from_bytes(buf[offset:offset + length_bytes], "little")
    offset += length_bytes
    return buf[offset:offset + length].decode("ascii", errors="replace"), offset + length


def parse_header_and_block_types(path):
    """Return (block_type_counts: dict[str, int], version: int, user_version: int).

    Raises ValueError if the file is not a parseable NIF.
    """
    data = path.read_bytes()
    if len(data) < 16:
        raise ValueError("file too small to be a NIF")

    # Older NIFs start with an ASCII magic line ending in \\n.
    nl = data.find(b"\\n")
    if nl < 0 or nl > 80:
        raise ValueError("no magic line found in first 80 bytes")
    magic = data[:nl].decode("ascii", errors="replace")
    offset = nl + 1
    if "NetImmerse" not in magic and "Gamebryo" not in magic:
        raise ValueError(f"unexpected magic: {magic!r}")

    if len(data) < offset + 4:
        raise ValueError("truncated after magic line")
    version = struct.unpack_from("<I", data, offset)[0]
    offset += 4

    user_version = 0
    # v10.0.0.102 (0x0A000102) and later carry endian byte + user-version.
    if version >= 0x0A000102:
        if len(data) < offset + 5:
            raise ValueError("truncated header (post-v10)")
        endian = data[offset]
        offset += 1
        if endian != 1:
            raise ValueError("big-endian NIFs not supported")
        user_version = struct.unpack_from("<I", data, offset)[0]
        offset += 4

    # Some versions have a number-of-blocks field here, then block-type table.
    # Format details vary; we tolerate unparseable variants by failing fast.
    if version >= 0x0A010000:
        # num blocks (uint32)
        if len(data) < offset + 4:
            raise ValueError("truncated before block count")
        offset += 4
        # number of block types (uint16) — note: 16-bit, not 32-bit
        if len(data) < offset + 2:
            raise ValueError("truncated before block-type count")
        num_block_types = struct.unpack_from("<H", data, offset)[0]
        offset += 2
        block_types = []
        for _ in range(num_block_types):
            name, offset = read_string(data, offset, length_bytes=4)
            block_types.append(name)
        # block_type_index table follows (uint16 per block) — we don't need
        # the per-block mapping for inventory purposes.
        counts = defaultdict(int)
        for t in block_types:
            counts[t] += 1
        return counts, version, user_version
    else:
        # Older format: each block in the file starts with a length-prefixed
        # type-name string. We can walk the file, but it's more involved.
        raise ValueError(f"old NIF version {version:#010x} not supported by this tool")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--manifest", type=Path,
                    help="Write Markdown manifest to this path")
    args = ap.parse_args()

    per_file = {}
    aggregate = defaultdict(int)
    failures = []

    for p in args.paths:
        try:
            counts, version, user_version = parse_header_and_block_types(p)
            per_file[p] = (counts, version, user_version)
            for t, c in counts.items():
                aggregate[t] += c
        except Exception as e:
            failures.append((p, str(e)))

    if args.manifest:
        with args.manifest.open("w") as out:
            out.write("# v1 Block Manifest\\n\\n")
            out.write("Generated by `tools/list_nif_blocks.py`. Do not edit by hand.\\n\\n")
            out.write("## Files surveyed\\n\\n")
            for p, (counts, v, uv) in sorted(per_file.items()):
                out.write(f"- `{p}` — version `{v:#010x}`, user_version `{uv}`, "
                          f"{sum(counts.values())} blocks, {len(counts)} unique types\\n")
            if failures:
                out.write("\\n## Files that failed to parse\\n\\n")
                for p, err in failures:
                    out.write(f"- `{p}` — {err}\\n")
            out.write("\\n## Block types (aggregate, sorted)\\n\\n")
            out.write("| Block type | Total count | Files containing |\\n")
            out.write("|---|---:|---:|\\n")
            for t in sorted(aggregate):
                files_containing = sum(1 for (counts, _, _) in per_file.values() if t in counts)
                out.write(f"| `{t}` | {aggregate[t]} | {files_containing} |\\n")
        print(f"Wrote {args.manifest}")
    else:
        for t in sorted(aggregate):
            print(f"{aggregate[t]:6d}  {t}")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Smoke-test on one file**

```bash
uv run python tools/list_nif_blocks.py game/data/Models/Ships/Galaxy/Galaxy.nif
```

Expected: a sorted block-type list, one type per line. If the tool errors with "old NIF version not supported", BC NIFs predate v10.1.0.0 and the tool needs the older-format path. Fix in place if so — the older format is simpler (each block prefixed by length-prefixed type name as it's encountered, walk linearly).

- [ ] **Step 3: Commit**

```bash
git add tools/list_nif_blocks.py
git commit -m "tools(nif): list_nif_blocks.py block-type inventory"
```

---

### Task 9: Run inventory, commit manifests

**Files:**
- Create: `native/src/nif/docs/v1_block_manifest.md`
- Create: `native/src/nif/docs/v1_omitted_blocks.md`

- [ ] **Step 1: Run inventory on all four sample files**

```bash
mkdir -p native/src/nif/docs
uv run python tools/list_nif_blocks.py \
    game/data/Models/Ships/Galaxy/Galaxy.nif \
    game/data/Models/Bases/CardStarbase/CardStarbase.nif \
    game/data/Models/Characters/Bodies/BodyKlingon/BodyKlingon.nif \
    game/data/Models/Sets/EBridge/EBridge.nif \
    --manifest native/src/nif/docs/v1_block_manifest.md
```

Expected: `Wrote native/src/nif/docs/v1_block_manifest.md`. Open it and verify it lists block types from all four files. Record the NIF version and user_version values in the spec for later reference (these resolve OQ-3.1).

- [ ] **Step 2: Generate `v1_omitted_blocks.md`**

OpenMW's full block coverage = the union of class names parsed in `native/third_party/openmw_nif/*.cpp`. Produce that list with:

```bash
grep -hE "REGISTER_NIF\\b|registerType|^Ni[A-Z][a-zA-Z0-9]*::" native/third_party/openmw_nif/*.cpp \
    | grep -oE "Ni[A-Z][a-zA-Z0-9]*" \
    | sort -u > /tmp/openmw_blocks.txt
```

Extract our manifest's block list:

```bash
awk -F'`' '/^\\| `Ni/ { print $2 }' native/src/nif/docs/v1_block_manifest.md \
    | sort -u > /tmp/our_blocks.txt
```

Compute the difference:

```bash
comm -23 /tmp/openmw_blocks.txt /tmp/our_blocks.txt
```

Write the result into `native/src/nif/docs/v1_omitted_blocks.md`:

```markdown
# v1 Omitted Blocks

Block types OpenMW's parser handles but BC's four sample files do not use.
v1 deliberately does not implement these. Generated from the diff
`(types in openmw/components/nif) − (types in v1_block_manifest.md)`.

| Block type | OpenMW source |
|---|---|
| `<name>` | `<file>.cpp` |
| ... | ... |

To bring an omitted block into scope: add a sample file that exercises it,
re-run `tools/list_nif_blocks.py`, then design + implement the parser as a
follow-up task.
```

Fill in the table from the `comm` output above. (One row per missing block; for source attribution, `grep -l "<name>" native/third_party/openmw_nif/*.cpp` finds it.)

- [ ] **Step 3: Commit**

```bash
git add native/src/nif/docs/v1_block_manifest.md native/src/nif/docs/v1_omitted_blocks.md
git commit -m "docs(nif): commit v1 block manifest + omitted-blocks list"
```

---

## Phase C — Public API

### Task 10: `nif/types.h` primitives

**Files:**
- Create: `native/src/nif/include/nif/types.h`
- Create: `native/tests/nif/types_test.cc`
- Modify: `native/tests/CMakeLists.txt` (add `nif/types_test.cc` to `nif_tests` sources)

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/nif/types_test.cc
#include <gtest/gtest.h>
#include <nif/types.h>

TEST(Types, Vec3DefaultIsZero) {
    nif::Vec3 v{};
    EXPECT_FLOAT_EQ(v.x, 0.0f);
    EXPECT_FLOAT_EQ(v.y, 0.0f);
    EXPECT_FLOAT_EQ(v.z, 0.0f);
}

TEST(Types, Mat3x3RowMajorOrdering) {
    nif::Mat3x3 m{ .m = {1,2,3,  4,5,6,  7,8,9} };
    EXPECT_FLOAT_EQ(m.m[0], 1.0f);
    EXPECT_FLOAT_EQ(m.m[4], 5.0f);
    EXPECT_FLOAT_EQ(m.m[8], 9.0f);
}

TEST(Types, BlockIdNullSentinel) {
    nif::BlockId id = -1;
    EXPECT_EQ(id, nif::kNullBlockId);
}
```

Add to `native/tests/CMakeLists.txt` `nif_tests` sources: `nif/types_test.cc`.

- [ ] **Step 2: Run, expect compile failure (header doesn't exist)**

```bash
cmake --build build -j
```

Expected: `fatal error: nif/types.h: No such file or directory`.

- [ ] **Step 3: Write the header**

```cpp
// native/src/nif/include/nif/types.h
#pragma once

#include <array>
#include <cstdint>
#include <string>

namespace nif {

struct Vec3 { float x, y, z; };
struct Vec4 { float x, y, z, w; };
struct Quat { float x, y, z, w; };
struct Mat3x3 { std::array<float, 9> m; };  // row-major
struct Color3 { float r, g, b; };
struct Color4 { float r, g, b, a; };

using BlockId = std::int32_t;
constexpr BlockId kNullBlockId = -1;

using StringRef = std::string;

}  // namespace nif
```

- [ ] **Step 4: Build and run**

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure -R Types
```

Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add native/src/nif/include/nif/types.h native/tests/nif/types_test.cc native/tests/CMakeLists.txt
git commit -m "feat(nif): types.h primitives (Vec3, Mat3x3, BlockId, etc.)"
```

---

### Task 11: `Reader` — bounds-checked LE byte reader

**Files:**
- Create: `native/src/nif/src/reader.h`
- Create: `native/src/nif/src/reader.cc`
- Create: `native/tests/nif/reader_test.cc`
- Modify: `native/src/nif/CMakeLists.txt` (add `src/reader.cc`)
- Modify: `native/tests/CMakeLists.txt` (add `nif/reader_test.cc`)

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/nif/reader_test.cc
#include <gtest/gtest.h>
#include "../../src/nif/src/reader.h"

#include <cstdint>
#include <vector>

namespace {
nif::Reader make_reader(std::vector<unsigned char> bytes) {
    return nif::Reader(bytes.data(), bytes.size(), "<test>");
}
}

TEST(Reader, ReadsLittleEndianUint32) {
    auto r = make_reader({0x78, 0x56, 0x34, 0x12});
    EXPECT_EQ(r.read_uint32(), 0x12345678u);
    EXPECT_EQ(r.bytes_remaining(), 0u);
}

TEST(Reader, ReadsFloat) {
    // 1.0f little-endian
    auto r = make_reader({0x00, 0x00, 0x80, 0x3F});
    EXPECT_FLOAT_EQ(r.read_float(), 1.0f);
}

TEST(Reader, ReadsLengthPrefixedString) {
    auto r = make_reader({0x05, 0x00, 0x00, 0x00, 'h','e','l','l','o'});
    EXPECT_EQ(r.read_string_uint32(), "hello");
}

TEST(Reader, ThrowsOnTruncation) {
    auto r = make_reader({0x00, 0x00});
    EXPECT_THROW(r.read_uint32(), nif::ParseError);
}

TEST(Reader, OffsetAdvancesAfterRead) {
    auto r = make_reader({0x01, 0x00, 0x02, 0x00});
    EXPECT_EQ(r.read_uint16(), 1u);
    EXPECT_EQ(r.offset(), 2u);
    EXPECT_EQ(r.read_uint16(), 2u);
    EXPECT_EQ(r.offset(), 4u);
}

TEST(Reader, ReadsVec3) {
    // (1.0, 2.0, 3.0) as 12 bytes
    auto r = make_reader({
        0x00, 0x00, 0x80, 0x3F,
        0x00, 0x00, 0x00, 0x40,
        0x00, 0x00, 0x40, 0x40,
    });
    auto v = r.read_vec3();
    EXPECT_FLOAT_EQ(v.x, 1.0f);
    EXPECT_FLOAT_EQ(v.y, 2.0f);
    EXPECT_FLOAT_EQ(v.z, 3.0f);
}
```

Note: the test includes `error.h`-defined `ParseError` — that header is created in Task 12. If you're running tasks strictly in order, swap Tasks 11 and 12: do error.h first, then Reader. Either works; the dependency goes one direction only.

- [ ] **Step 2: Run, expect compile failure**

- [ ] **Step 3: Write `reader.h`**

```cpp
// native/src/nif/src/reader.h
#pragma once

#include <nif/error.h>
#include <nif/types.h>

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <string>

namespace nif {

class Reader {
public:
    Reader(const unsigned char* data, std::size_t size, std::filesystem::path source);

    std::uint8_t  read_uint8();
    std::uint16_t read_uint16();
    std::uint32_t read_uint32();
    std::int32_t  read_int32();
    float         read_float();
    Vec3          read_vec3();
    Vec4          read_vec4();
    Quat          read_quat();
    Mat3x3        read_mat3x3();
    Color3        read_color3();
    Color4        read_color4();

    /// Length-prefixed string with uint32 length.
    std::string read_string_uint32();
    /// Length-prefixed string with uint8 length (older NIF versions).
    std::string read_string_uint8();
    /// Read exactly `n` bytes into a buffer.
    void read_bytes(unsigned char* out, std::size_t n);

    std::size_t offset() const { return offset_; }
    std::size_t bytes_remaining() const { return size_ - offset_; }
    const std::filesystem::path& source() const { return source_; }

    /// Throw nif::TruncatedBlock if fewer than `n` bytes remain.
    void require(std::size_t n);

private:
    const unsigned char* data_;
    std::size_t size_;
    std::size_t offset_ = 0;
    std::filesystem::path source_;
};

}  // namespace nif
```

- [ ] **Step 4: Write `reader.cc`**

```cpp
// native/src/nif/src/reader.cc
#include "reader.h"

#include <cstring>

namespace nif {

Reader::Reader(const unsigned char* data, std::size_t size, std::filesystem::path source)
    : data_(data), size_(size), source_(std::move(source)) {}

void Reader::require(std::size_t n) {
    if (bytes_remaining() < n) {
        TruncatedBlock e("reader: truncated, " +
                         std::to_string(bytes_remaining()) + " of " +
                         std::to_string(n) + " required bytes available");
        e.file = source_;
        e.byte_offset = offset_;
        throw e;
    }
}

std::uint8_t Reader::read_uint8() {
    require(1);
    return data_[offset_++];
}

std::uint16_t Reader::read_uint16() {
    require(2);
    std::uint16_t v;
    std::memcpy(&v, data_ + offset_, 2);
    offset_ += 2;
    return v;
}

std::uint32_t Reader::read_uint32() {
    require(4);
    std::uint32_t v;
    std::memcpy(&v, data_ + offset_, 4);
    offset_ += 4;
    return v;
}

std::int32_t Reader::read_int32() {
    return static_cast<std::int32_t>(read_uint32());
}

float Reader::read_float() {
    require(4);
    float v;
    std::memcpy(&v, data_ + offset_, 4);
    offset_ += 4;
    return v;
}

Vec3 Reader::read_vec3() {
    Vec3 v;
    v.x = read_float();
    v.y = read_float();
    v.z = read_float();
    return v;
}

Vec4 Reader::read_vec4() {
    return {read_float(), read_float(), read_float(), read_float()};
}

Quat Reader::read_quat() {
    return {read_float(), read_float(), read_float(), read_float()};
}

Mat3x3 Reader::read_mat3x3() {
    Mat3x3 m;
    for (auto& f : m.m) f = read_float();
    return m;
}

Color3 Reader::read_color3() { return {read_float(), read_float(), read_float()}; }
Color4 Reader::read_color4() { return {read_float(), read_float(), read_float(), read_float()}; }

std::string Reader::read_string_uint32() {
    auto len = read_uint32();
    require(len);
    std::string s(reinterpret_cast<const char*>(data_ + offset_), len);
    offset_ += len;
    return s;
}

std::string Reader::read_string_uint8() {
    auto len = read_uint8();
    require(len);
    std::string s(reinterpret_cast<const char*>(data_ + offset_), len);
    offset_ += len;
    return s;
}

void Reader::read_bytes(unsigned char* out, std::size_t n) {
    require(n);
    std::memcpy(out, data_ + offset_, n);
    offset_ += n;
}

}  // namespace nif
```

- [ ] **Step 5: Update CMake — add `src/reader.cc` to `nif`, add `nif/reader_test.cc` to `nif_tests`. Build + run.**

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure -R Reader
```

Expected: 6 tests pass.

- [ ] **Step 6: Commit**

```bash
git add native/src/nif/src/reader.h native/src/nif/src/reader.cc native/src/nif/CMakeLists.txt native/tests/nif/reader_test.cc native/tests/CMakeLists.txt
git commit -m "feat(nif): bounds-checked little-endian Reader"
```

---

### Task 12: `nif/error.h` — exception hierarchy

**Files:**
- Create: `native/src/nif/include/nif/error.h`

Note: as flagged in Task 11, this header must exist before `reader.cc` includes it. If you arrived here via Task 11's order, you've effectively already needed it; do this task first if working strictly sequentially.

- [ ] **Step 1: Write the header**

```cpp
// native/src/nif/include/nif/error.h
#pragma once

#include <cstddef>
#include <filesystem>
#include <optional>
#include <stdexcept>
#include <string>

namespace nif {

class ParseError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
    std::filesystem::path file;
    std::optional<std::size_t> byte_offset;
    std::optional<std::string> block_type;
};

class UnknownBlockType : public ParseError { using ParseError::ParseError; };
class TruncatedBlock   : public ParseError { using ParseError::ParseError; };
class VersionMismatch  : public ParseError { using ParseError::ParseError; };

}  // namespace nif
```

- [ ] **Step 2: Build (no tests yet, just verify it compiles when included from the Reader)**

```bash
cmake --build build -j
```

- [ ] **Step 3: Commit**

```bash
git add native/src/nif/include/nif/error.h
git commit -m "feat(nif): exception hierarchy (ParseError + subtypes)"
```

---

### Task 13: `nif/version.h`

**Files:**
- Create: `native/src/nif/include/nif/version.h`
- Create: `native/tests/nif/version_test.cc`
- Modify: `native/tests/CMakeLists.txt` — add `nif/version_test.cc`

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/nif/version_test.cc
#include <gtest/gtest.h>
#include <nif/version.h>

TEST(Version, IsBcReturnsTrueForKnownBcVersion) {
    nif::Version v{ /* value */ nif::kBcVersionValue, /* user_version */ nif::kBcUserVersion };
    EXPECT_TRUE(nif::is_bc(v));
}

TEST(Version, IsBcReturnsFalseForMorrowind) {
    nif::Version v{ 0x04000002, 0 };  // Morrowind v4.0.0.2
    EXPECT_FALSE(nif::is_bc(v));
}
```

- [ ] **Step 2: Run, expect compile failure**

- [ ] **Step 3: Fill in the BC version constants**

Look at the Task 9 manifest output, find the version + user_version actually used by the four sample files, and embed them:

```cpp
// native/src/nif/include/nif/version.h
#pragma once

#include <cstdint>

namespace nif {

struct Version {
    std::uint32_t value;
    std::uint32_t user_version;
};

// Filled in from the v1_block_manifest.md inventory step.
// Galaxy.nif / CardStarbase.nif / BodyKlingon.nif / EBridge.nif all share these:
inline constexpr std::uint32_t kBcVersionValue   = /* TBD-from-manifest */ 0;
inline constexpr std::uint32_t kBcUserVersion    = /* TBD-from-manifest */ 0;

inline bool is_bc(Version v) {
    return v.value == kBcVersionValue && v.user_version == kBcUserVersion;
}

}  // namespace nif
```

Replace the two `/* TBD-from-manifest */` lines with the actual values reported in `v1_block_manifest.md` (recorded in Task 9 Step 1). If the four files don't all share the same version+user_version, that's an unexpected outcome — stop and report; the design assumed they would.

- [ ] **Step 4: Build and run**

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure -R Version
```

Expected: 2 tests pass.

- [ ] **Step 5: Commit**

```bash
git add native/src/nif/include/nif/version.h native/tests/nif/version_test.cc native/tests/CMakeLists.txt
git commit -m "feat(nif): version.h with BC version constants from manifest"
```

---

### Task 14: `nif/block.h` and `nif/file.h` (skeletons), drop placeholder anchor

**Files:**
- Create: `native/src/nif/include/nif/block.h`
- Create: `native/src/nif/include/nif/file.h`
- Create: `native/src/nif/src/file.cc`
- Delete: `native/src/nif/src/empty.cc`
- Modify: `native/src/nif/CMakeLists.txt` — replace `src/empty.cc` with `src/file.cc`

- [ ] **Step 1: Write `block.h`**

```cpp
// native/src/nif/include/nif/block.h
#pragma once

#include <nif/types.h>

#include <variant>
#include <vector>

namespace nif {

// Block variant grows as parsers land in subsequent tasks. Today: just the
// monostate placeholder, so the variant compiles.
using Block = std::variant<std::monostate>;

struct BlockHandle {
    const Block* ptr = nullptr;
    explicit operator bool() const { return ptr != nullptr; }
    const Block& operator*() const { return *ptr; }
    const Block* operator->() const { return ptr; }
};

}  // namespace nif
```

- [ ] **Step 2: Write `file.h`**

```cpp
// native/src/nif/include/nif/file.h
#pragma once

#include <nif/block.h>
#include <nif/version.h>

#include <filesystem>
#include <vector>

namespace nif {

struct File {
    Version version{};
    std::vector<Block> blocks;
    BlockHandle root{};
    std::vector<std::string> strings;
    std::filesystem::path source;

    File() = default;
    File(const File&) = delete;
    File(File&&) = default;
    File& operator=(const File&) = delete;
    File& operator=(File&&) = default;
};

File load(const std::filesystem::path& path);

}  // namespace nif
```

- [ ] **Step 3: Write a stub `file.cc`**

```cpp
// native/src/nif/src/file.cc
#include <nif/file.h>
#include <nif/error.h>

namespace nif {

File load(const std::filesystem::path& path) {
    // Real implementation lands in Task 16+. For now, throw so any caller
    // gets a clear "not yet implemented" message.
    ParseError e("nif::load not yet implemented");
    e.file = path;
    throw e;
}

}  // namespace nif
```

- [ ] **Step 4: Update CMake**

In `native/src/nif/CMakeLists.txt`, replace `src/empty.cc` with `src/file.cc src/reader.cc` (reader.cc was already added in Task 11).

- [ ] **Step 5: Delete the empty placeholder**

```bash
rm native/src/nif/src/empty.cc
```

- [ ] **Step 6: Build**

```bash
cmake --build build -j
```

Expected: succeeds.

- [ ] **Step 7: Commit**

```bash
git add -A native/src/nif/
git commit -m "feat(nif): block.h, file.h, file.cc skeleton (load throws NotImplemented)"
```

---

### Task 15: Canonical-text format spec + dumper skeleton

**Files:**
- Create: `native/src/nif/docs/canonical_dump_format.md`
- Create: `native/tests/nif/canonical_dump.h`
- Create: `native/tests/nif/canonical_dump.cc`
- Modify: `native/tests/CMakeLists.txt` — add to `nif_tests`

- [ ] **Step 1: Write the format spec**

```markdown
# Canonical Dump Format

Used by the diff harness to compare our `nif::File` against OpenMW's
`Nif::NIFFile` for the same input file. Both emitters MUST produce identical
output for shared block types.

## Rules

1. **Line-oriented.** Every field is on its own line.
2. **Indentation:** two spaces per level. The file is level 0; blocks are
   level 1; block fields are level 2; nested structs are level 3+.
3. **Floats** printed via `%.6g` (six significant digits, no trailing zeros).
4. **Vec3** printed as `(x, y, z)` with each component as a float per rule 3.
5. **Mat3x3** printed as three lines, one row each, each `(a, b, c)`.
6. **Strings** printed quoted with `"..."`. Embedded quotes escaped as `\\"`.
7. **Block IDs** printed as decimal integers. Null reference = `null`.
8. **Block headers:** `block <index> <type-name>` with no trailing colon.
9. **Field lines:** `<field-name>: <value>`.
10. **Skipped BC blocks** (in `shared_blocks_only=true` mode) emit a single
    line: `block <index> <type-name> [skipped: bc-specific]`.

## Example

```
file
  version: 0x14000005
  user_version: 11
  num_blocks: 3
  num_strings: 0
  block 0 NiNode
    name: "Scene Root"
    flags: 0x000e
    translation: (0, 0, 0)
    rotation:
      (1, 0, 0)
      (0, 1, 0)
      (0, 0, 1)
    scale: 1
    num_children: 1
    children:
      0: 1
  block 1 NiTriShape
    ...
```
```

- [ ] **Step 2: Write the dumper header**

```cpp
// native/tests/nif/canonical_dump.h
#pragma once

#include <nif/file.h>

#include <ostream>

namespace nif::test {

struct DumpOptions {
    bool shared_blocks_only = false;
};

void dump_canonical(const File& f, std::ostream& out, DumpOptions opt = {});

}  // namespace nif::test
```

- [ ] **Step 3: Write the dumper body — file-level header only for now**

```cpp
// native/tests/nif/canonical_dump.cc
#include "canonical_dump.h"

#include <iomanip>

namespace nif::test {

namespace {
void emit_indent(std::ostream& out, int n) {
    for (int i = 0; i < n; ++i) out << "  ";
}
}

void dump_canonical(const File& f, std::ostream& out, DumpOptions /*opt*/) {
    out << "file\\n";
    emit_indent(out, 1);
    out << "version: 0x" << std::hex << std::setw(8) << std::setfill('0')
        << f.version.value << std::dec << std::setfill(' ') << "\\n";
    emit_indent(out, 1);
    out << "user_version: " << f.version.user_version << "\\n";
    emit_indent(out, 1);
    out << "num_blocks: " << f.blocks.size() << "\\n";
    emit_indent(out, 1);
    out << "num_strings: " << f.strings.size() << "\\n";
    // Block bodies emitted starting in Task 22 (NiNode) and onwards.
}

}  // namespace nif::test
```

- [ ] **Step 4: Update CMake**

Add to `nif_tests` sources: `nif/canonical_dump.cc`. Build: `cmake --build build -j`. Expected: succeeds.

- [ ] **Step 5: Commit**

```bash
git add native/src/nif/docs/canonical_dump_format.md native/tests/nif/canonical_dump.h native/tests/nif/canonical_dump.cc native/tests/CMakeLists.txt
git commit -m "feat(nif): canonical dump format spec + file-header emitter"
```

---

## Phase D — File-level pipeline

### Task 16: Header parsing + dispatch table scaffolding

**Files:**
- Modify: `native/src/nif/src/file.cc`
- Create: `native/src/nif/src/header.h`, `header.cc`
- Create: `native/tests/nif/header_test.cc`
- Modify: `native/src/nif/CMakeLists.txt` — add `src/header.cc`
- Modify: `native/tests/CMakeLists.txt` — add `nif/header_test.cc` and a sample-paths helper

This task is large enough to be its own phase but stays as one task because the steps chain tightly. If splitting helps reviewability, split between Step 4 (header structs) and Step 5 (load wiring).

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/nif/header_test.cc
#include <gtest/gtest.h>
#include <nif/file.h>

#include "sample_paths.h"

class HeaderTest : public ::testing::TestWithParam<SampleFile> {};

TEST_P(HeaderTest, ParsesAndReportsExpectedHeader) {
    const auto& sample = GetParam();
    if (!std::filesystem::exists(sample.path)) {
        GTEST_SKIP() << "Sample missing: " << sample.path;
    }
    auto f = nif::load(sample.path);
    EXPECT_EQ(f.version.value, sample.expected_version);
    EXPECT_EQ(f.version.user_version, sample.expected_user_version);
    EXPECT_EQ(f.blocks.size(), sample.expected_block_count);
}

INSTANTIATE_TEST_SUITE_P(AllSamples, HeaderTest,
    ::testing::ValuesIn(kSampleFiles));
```

Create `native/tests/nif/sample_paths.h`:

```cpp
// native/tests/nif/sample_paths.h
#pragma once

#include <filesystem>
#include <string>
#include <vector>

struct SampleFile {
    std::filesystem::path path;
    std::uint32_t expected_version;
    std::uint32_t expected_user_version;
    std::size_t expected_block_count;
    std::string nickname;
};

inline const std::vector<SampleFile> kSampleFiles = {
    // Values for expected_version / expected_user_version / expected_block_count
    // come from `tools/list_nif_blocks.py` output committed in
    // native/src/nif/docs/v1_block_manifest.md. Replace zeros with manifest
    // values when this test is first written.
    { "game/data/Models/Ships/Galaxy/Galaxy.nif",                                0, 0, 0, "Galaxy" },
    { "game/data/Models/Bases/CardStarbase/CardStarbase.nif",                    0, 0, 0, "CardStarbase" },
    { "game/data/Models/Characters/Bodies/BodyKlingon/BodyKlingon.nif",          0, 0, 0, "BodyKlingon" },
    { "game/data/Models/Sets/EBridge/EBridge.nif",                               0, 0, 0, "EBridge" },
};
```

Replace the four `0, 0, 0` triples with values from the manifest before running the test.

- [ ] **Step 2: Run, expect failure (load currently throws)**

- [ ] **Step 3: Write `header.h`**

```cpp
// native/src/nif/src/header.h
#pragma once

#include <nif/version.h>

#include <cstdint>
#include <string>
#include <vector>

namespace nif {

class Reader;  // fwd

struct HeaderInfo {
    Version version;
    std::uint32_t num_blocks = 0;
    std::vector<std::string> block_types;       // distinct type-name strings
    std::vector<std::uint16_t> block_type_index; // per-block index into block_types
    std::vector<std::uint32_t> block_sizes;      // bytes per block
    std::vector<std::string> strings;            // string-table contents
};

HeaderInfo parse_header(Reader& r);

}  // namespace nif
```

- [ ] **Step 4: Write `header.cc`**

This implementation MUST handle the BC-version branch as discovered in the inventory step. The general structure (post-v10 NIF) is:

```cpp
// native/src/nif/src/header.cc
#include "header.h"
#include "reader.h"

#include <nif/error.h>

namespace nif {

HeaderInfo parse_header(Reader& r) {
    // 1. Read magic line ending with \\n.
    std::string magic;
    while (r.bytes_remaining() > 0) {
        auto b = r.read_uint8();
        if (b == 0x0A) break;
        magic.push_back(static_cast<char>(b));
    }
    if (magic.find("NetImmerse") == std::string::npos &&
        magic.find("Gamebryo")   == std::string::npos) {
        VersionMismatch e("not a NIF: bad magic line: " + magic);
        e.file = r.source();
        throw e;
    }

    HeaderInfo h;
    h.version.value = r.read_uint32();

    // post-v10.0.0.102: endian byte + user-version
    if (h.version.value >= 0x0A000102) {
        auto endian = r.read_uint8();
        if (endian != 1) {
            VersionMismatch e("big-endian NIFs not supported");
            e.file = r.source();
            throw e;
        }
        h.version.user_version = r.read_uint32();
    }

    // post-v10.1.0.0: num_blocks (uint32), then block-type table (uint16 count
    //                 + length-prefixed strings), then block-type index per
    //                 block (uint16), then block_sizes (uint32 each).
    if (h.version.value >= 0x0A010000) {
        h.num_blocks = r.read_uint32();

        // Some BC NIFs include an "unknown int" or "user_version_2" between
        // user_version and num_blocks — confirm by walking with NifSkope on a
        // sample file. If your first run of the header test fails with
        // "TruncatedBlock at offset N", inspect the bytes at offset N in
        // NifSkope and compare to the schema.

        auto num_block_types = r.read_uint16();
        h.block_types.reserve(num_block_types);
        for (std::uint16_t i = 0; i < num_block_types; ++i) {
            h.block_types.push_back(r.read_string_uint32());
        }

        h.block_type_index.reserve(h.num_blocks);
        for (std::uint32_t i = 0; i < h.num_blocks; ++i) {
            h.block_type_index.push_back(r.read_uint16());
        }

        h.block_sizes.reserve(h.num_blocks);
        for (std::uint32_t i = 0; i < h.num_blocks; ++i) {
            h.block_sizes.push_back(r.read_uint32());
        }

        // String table (post-v20.1.0.3-ish; verify with manifest).
        if (h.version.value >= 0x14010003) {
            auto num_strings = r.read_uint32();
            r.read_uint32();  // max length, unused
            h.strings.reserve(num_strings);
            for (std::uint32_t i = 0; i < num_strings; ++i) {
                h.strings.push_back(r.read_string_uint32());
            }
        }

        // Number of "groups" — used by NIFs that group blocks; usually 0.
        if (h.version.value >= 0x05000001) {
            auto num_groups = r.read_uint32();
            for (std::uint32_t i = 0; i < num_groups; ++i) {
                r.read_uint32();
            }
        }
    } else {
        // Pre-v10.1.0.0: blocks are walked linearly with their type names
        // inline. The `nif::load` driver uses a different path; HeaderInfo's
        // num_blocks stays 0 and block_types stays empty.
    }
    return h;
}

}  // namespace nif
```

- [ ] **Step 5: Wire `parse_header` into `nif::load`**

```cpp
// native/src/nif/src/file.cc (rewrite)
#include <nif/file.h>
#include <nif/error.h>

#include "reader.h"
#include "header.h"

#include <fstream>

namespace nif {

namespace {
std::vector<unsigned char> slurp(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary | std::ios::ate);
    if (!in) {
        ParseError e("could not open file");
        e.file = path;
        throw e;
    }
    auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0);
    std::vector<unsigned char> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()), size);
    return bytes;
}
}  // namespace

File load(const std::filesystem::path& path) {
    auto bytes = slurp(path);
    Reader r(bytes.data(), bytes.size(), path);

    File f;
    f.source = path;

    auto h = parse_header(r);
    f.version = h.version;
    f.strings = h.strings;
    f.blocks.resize(h.num_blocks);  // monostate placeholders; real bodies in later tasks.
    return f;
}

}  // namespace nif
```

- [ ] **Step 6: Run the test**

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure -R HeaderTest
```

Expected: all four parameterized cases pass.

- [ ] **Step 7: Commit**

```bash
git add -A native/src/nif/ native/tests/nif/header_test.cc native/tests/nif/sample_paths.h native/tests/CMakeLists.txt
git commit -m "feat(nif): header parsing + file load wiring; HeaderTest passes for all 4 samples"
```

---

### Task 17: Resolver pass infrastructure (no-op while blocks are monostate)

**Files:**
- Create: `native/src/nif/src/resolver.h`, `resolver.cc`
- Create: `native/tests/nif/resolver_test.cc`
- Modify: `native/src/nif/CMakeLists.txt`
- Modify: `native/tests/CMakeLists.txt`

The resolver gets exercised meaningfully in Task 21 (NiNode references); for now it's no-op + scaffolding so that block parsers can emit `BlockId`s freely and trust they'll be resolved.

- [ ] **Step 1: Write the failing test (synthetic, no real blocks yet)**

```cpp
// native/tests/nif/resolver_test.cc
#include <gtest/gtest.h>
#include "../../src/nif/src/resolver.h"

#include <nif/file.h>

TEST(Resolver, EmptyFileResolvesNoOp) {
    nif::File f;
    f.blocks.resize(3);
    EXPECT_NO_THROW(nif::resolve_references(f));
}

TEST(Resolver, NullSentinelResolvesToFalsyHandle) {
    nif::File f;
    f.blocks.resize(2);
    auto h = nif::resolve_handle(f, /*block_id=*/-1);
    EXPECT_FALSE(static_cast<bool>(h));
}

TEST(Resolver, ValidIndexResolvesToHandle) {
    nif::File f;
    f.blocks.resize(2);
    auto h = nif::resolve_handle(f, /*block_id=*/1);
    EXPECT_TRUE(static_cast<bool>(h));
    EXPECT_EQ(h.ptr, &f.blocks[1]);
}

TEST(Resolver, OutOfRangeIndexThrows) {
    nif::File f;
    f.blocks.resize(2);
    EXPECT_THROW(nif::resolve_handle(f, /*block_id=*/99), nif::ParseError);
}
```

- [ ] **Step 2: Run, expect compile failure**

- [ ] **Step 3: Write `resolver.h`**

```cpp
// native/src/nif/src/resolver.h
#pragma once

#include <nif/file.h>
#include <nif/types.h>

namespace nif {

BlockHandle resolve_handle(File& f, BlockId id);
void resolve_references(File& f);  // walks all blocks, replaces internal indices

}  // namespace nif
```

- [ ] **Step 4: Write `resolver.cc`**

```cpp
// native/src/nif/src/resolver.cc
#include "resolver.h"

#include <nif/error.h>

namespace nif {

BlockHandle resolve_handle(File& f, BlockId id) {
    if (id == kNullBlockId) return BlockHandle{};
    if (id < 0 || static_cast<std::size_t>(id) >= f.blocks.size()) {
        ParseError e("block reference out of range: " + std::to_string(id));
        e.file = f.source;
        throw e;
    }
    return BlockHandle{ &f.blocks[id] };
}

void resolve_references(File& /*f*/) {
    // Per-block-type reference fix-up is added by each block parser task as
    // it lands. Today: blocks are all monostate, no references exist.
}

}  // namespace nif
```

- [ ] **Step 5: Update CMake, build, run**

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure -R Resolver
```

Expected: 4 tests pass.

- [ ] **Step 6: Commit**

```bash
git add -A native/src/nif/ native/tests/nif/resolver_test.cc native/tests/CMakeLists.txt
git commit -m "feat(nif): resolver scaffolding + 4 synthetic resolver tests"
```

---

### Task 18: Block-dispatch table (registers parsers as they land)

**Files:**
- Create: `native/src/nif/src/dispatch.h`, `dispatch.cc`
- Modify: `native/src/nif/src/file.cc` — call dispatch instead of leaving blocks as monostate

- [ ] **Step 1: Write `dispatch.h`**

```cpp
// native/src/nif/src/dispatch.h
#pragma once

#include <nif/block.h>

#include <functional>
#include <string>
#include <unordered_map>

namespace nif {

class Reader;
struct HeaderInfo;

using BlockParser = std::function<Block(Reader&, const HeaderInfo&)>;

class Dispatch {
public:
    static Dispatch& instance();
    void register_parser(std::string type_name, BlockParser parser);
    Block parse_block(const std::string& type_name, Reader& r,
                      const HeaderInfo& h, std::uint32_t expected_size);

private:
    std::unordered_map<std::string, BlockParser> parsers_;
};

#define NIF_REGISTER_BLOCK(TypeName, ParserFn)                              \\
    namespace { struct _reg_##TypeName {                                     \\
        _reg_##TypeName() {                                                  \\
            ::nif::Dispatch::instance().register_parser(#TypeName, ParserFn);\\
        }                                                                    \\
    } _reg_##TypeName##_instance; }

}  // namespace nif
```

- [ ] **Step 2: Write `dispatch.cc`**

```cpp
// native/src/nif/src/dispatch.cc
#include "dispatch.h"
#include "reader.h"
#include "header.h"

#include <nif/error.h>

namespace nif {

Dispatch& Dispatch::instance() {
    static Dispatch d;
    return d;
}

void Dispatch::register_parser(std::string type_name, BlockParser parser) {
    parsers_[std::move(type_name)] = std::move(parser);
}

Block Dispatch::parse_block(const std::string& type_name, Reader& r,
                            const HeaderInfo& h, std::uint32_t expected_size) {
    auto it = parsers_.find(type_name);
    if (it == parsers_.end()) {
        UnknownBlockType e("no parser registered for block type: " + type_name);
        e.file = r.source();
        e.byte_offset = r.offset();
        e.block_type = type_name;
        throw e;
    }
    auto start = r.offset();
    auto block = it->second(r, h);
    auto consumed = r.offset() - start;
    if (consumed != expected_size) {
        TruncatedBlock e("block parser consumed " + std::to_string(consumed) +
                         " bytes, expected " + std::to_string(expected_size) +
                         " (" + type_name + ")");
        e.file = r.source();
        e.byte_offset = r.offset();
        e.block_type = type_name;
        throw e;
    }
    return block;
}

}  // namespace nif
```

- [ ] **Step 3: Wire dispatch into `nif::load`**

In `file.cc`, after `parse_header`, replace the `f.blocks.resize(h.num_blocks)` line with:

```cpp
f.blocks.reserve(h.num_blocks);
for (std::uint32_t i = 0; i < h.num_blocks; ++i) {
    const auto& type_name = h.block_types[h.block_type_index[i]];
    auto expected_size = h.block_sizes[i];
    try {
        f.blocks.push_back(Dispatch::instance().parse_block(type_name, r, h, expected_size));
    } catch (UnknownBlockType&) {
        // No parser registered yet (early implementation phase). Skip the
        // block bytes and leave it as monostate so the file still loads.
        r.read_bytes(nullptr, 0);  // Will be replaced; for now use:
        std::vector<unsigned char> skip(expected_size);
        r.read_bytes(skip.data(), expected_size);
        f.blocks.emplace_back();
    }
}
resolve_references(f);
```

(The `try/catch UnknownBlockType` block is intentionally permissive during early phases, so we can land block parsers one at a time. After Task 27's manifest gap-fill, this catch becomes a hard failure — the diff harness would already have caught any unhandled type.)

- [ ] **Step 4: Build**

Build should succeed with no test changes; existing HeaderTest still passes (blocks are monostate as before, since no parsers are registered yet).

- [ ] **Step 5: Commit**

```bash
git add native/src/nif/src/dispatch.h native/src/nif/src/dispatch.cc native/src/nif/src/file.cc native/src/nif/CMakeLists.txt
git commit -m "feat(nif): block dispatch table; load() iterates blocks (all monostate so far)"
```

---

### Task 19: Synthetic negative tests

**Files:**
- Create: `native/tests/nif/error_test.cc`
- Modify: `native/tests/CMakeLists.txt`

- [ ] **Step 1: Write the tests**

```cpp
// native/tests/nif/error_test.cc
#include <gtest/gtest.h>
#include <nif/file.h>

#include <fstream>
#include <filesystem>

namespace {

std::filesystem::path write_temp(const std::vector<unsigned char>& bytes) {
    auto path = std::filesystem::temp_directory_path() / "nif_error_test.nif";
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    out.write(reinterpret_cast<const char*>(bytes.data()), bytes.size());
    return path;
}

}  // namespace

TEST(ErrorTest, EmptyFileThrows) {
    auto path = write_temp({});
    EXPECT_THROW(nif::load(path), nif::ParseError);
}

TEST(ErrorTest, BadMagicThrowsVersionMismatch) {
    auto path = write_temp({'b','a','d','\\n', 0,0,0,0});
    EXPECT_THROW(nif::load(path), nif::VersionMismatch);
}

TEST(ErrorTest, TruncatedAfterMagicThrows) {
    auto path = write_temp({'N','e','t','I','m','m','e','r','s','e',' ','F','i','l','e',' ','F','o','r','m','a','t',',',' ','V','e','r','s','i','o','n',' ','4','.','0','.','0','.','2','\\n'});
    EXPECT_THROW(nif::load(path), nif::ParseError);
}

TEST(ErrorTest, NonexistentFileThrows) {
    EXPECT_THROW(nif::load("/nonexistent/path/file.nif"), nif::ParseError);
}
```

- [ ] **Step 2: Build, run**

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure -R ErrorTest
```

Expected: 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add native/tests/nif/error_test.cc native/tests/CMakeLists.txt
git commit -m "test(nif): synthetic negative tests for malformed inputs"
```

---

### Task 20: Diff harness scaffolding (header-level only)

**Files:**
- Create: `native/tests/nif/openmw_canonical_dump.h`, `openmw_canonical_dump.cc`
- Create: `native/tests/nif/diff_harness_test.cc`
- Modify: `native/tests/CMakeLists.txt`

- [ ] **Step 1: Write the OpenMW-side dumper, header-level only**

```cpp
// native/tests/nif/openmw_canonical_dump.h
#pragma once

#include "canonical_dump.h"  // for DumpOptions

#include <filesystem>
#include <ostream>

namespace nif::test {

// Loads the file via OpenMW's parser and emits the canonical-dump format.
void dump_canonical_openmw(const std::filesystem::path& path,
                           std::ostream& out, DumpOptions opt = {});

}  // namespace nif::test
```

```cpp
// native/tests/nif/openmw_canonical_dump.cc
#include "openmw_canonical_dump.h"

#include <components/nif/niffile.hpp>

#include <iomanip>

namespace nif::test {

void dump_canonical_openmw(const std::filesystem::path& path,
                           std::ostream& out, DumpOptions /*opt*/) {
    Nif::NIFFile nif(path.string());
    out << "file\\n";
    out << "  version: 0x" << std::hex << std::setw(8) << std::setfill('0')
        << nif.getVersion() << std::dec << std::setfill(' ') << "\\n";
    out << "  user_version: " << nif.getUserVersion() << "\\n";
    out << "  num_blocks: " << nif.numRecords() << "\\n";
    out << "  num_strings: " << nif.getStrings().size() << "\\n";
    // Block bodies emitted starting in Task 22.
}

}  // namespace nif::test
```

The exact OpenMW header path and accessor names may differ — adjust based on the mirrored source in `native/third_party/openmw_nif/niffile.hpp`. Common methods include `numRecords()`, `getVersion()`, `getStrings()`. Read the mirrored header to confirm.

- [ ] **Step 2: Write the diff harness test**

```cpp
// native/tests/nif/diff_harness_test.cc
#include <gtest/gtest.h>

#include "canonical_dump.h"
#include "openmw_canonical_dump.h"
#include "sample_paths.h"

#include <nif/file.h>

#include <sstream>

class DiffHarness : public ::testing::TestWithParam<SampleFile> {};

TEST_P(DiffHarness, MatchesOpenMWOnSharedBlocks) {
    const auto& sample = GetParam();
    if (!std::filesystem::exists(sample.path)) {
        GTEST_SKIP() << "Sample missing: " << sample.path;
    }

    auto our_file = nif::load(sample.path);
    std::ostringstream ours, theirs;
    nif::test::DumpOptions opt;
    opt.shared_blocks_only = true;
    nif::test::dump_canonical(our_file, ours, opt);
    nif::test::dump_canonical_openmw(sample.path, theirs, opt);

    EXPECT_EQ(ours.str(), theirs.str())
        << "\\nOurs:\\n" << ours.str() << "\\nTheirs:\\n" << theirs.str();
}

INSTANTIATE_TEST_SUITE_P(AllSamples, DiffHarness,
    ::testing::ValuesIn(kSampleFiles));
```

- [ ] **Step 3: Update CMake — add the new files; build, run**

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure -R DiffHarness
```

Expected: 4 tests pass (header-level info matches between parsers). If they don't match, the OpenMW header read uses different conventions (e.g., user_version stored differently); adjust the OpenMW dumper.

- [ ] **Step 4: Commit**

```bash
git add native/tests/nif/openmw_canonical_dump.h native/tests/nif/openmw_canonical_dump.cc native/tests/nif/diff_harness_test.cc native/tests/CMakeLists.txt
git commit -m "test(nif): diff harness scaffolding; header-level dumps match OpenMW"
```

---

## Phase E — Block parsers

Each block-parser task uses the recipe near the top of this document. Tasks below give the per-block specifics: file location, struct fields (per `nif.xml`), and the test assertions.

### Task 21: NiNode parser

**Reference sources:**
- Schema: NifSkope `nif.xml`, search for `<niobject name="NiNode">`.
- OpenMW: `native/third_party/openmw_nif/node.cpp` (look for `NiNode::read`).

**Files:**
- Create: `native/src/nif/src/blocks/ni_node.cc`
- Modify: `native/src/nif/include/nif/block.h` — add `NiNode` struct, append to variant.
- Modify: `native/tests/nif/canonical_dump.cc` — add `NiNode` emitter.
- Modify: `native/tests/nif/openmw_canonical_dump.cc` — add `NiNode` OpenMW emitter.
- Create: `native/tests/nif/blocks_test.cc` — first block-level tests.
- Modify: `native/src/nif/CMakeLists.txt`, `native/tests/CMakeLists.txt`.

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/nif/blocks_test.cc
#include <gtest/gtest.h>

#include <nif/file.h>
#include "sample_paths.h"

namespace {

const nif::NiNode* find_first_ninode(const nif::File& f) {
    for (const auto& b : f.blocks) {
        if (auto* n = std::get_if<nif::NiNode>(&b)) return n;
    }
    return nullptr;
}

}  // namespace

TEST(NiNode, GalaxyHasRootNiNode) {
    auto p = std::filesystem::path("game/data/Models/Ships/Galaxy/Galaxy.nif");
    if (!std::filesystem::exists(p)) GTEST_SKIP();
    auto f = nif::load(p);
    auto* root = find_first_ninode(f);
    ASSERT_NE(root, nullptr);
    EXPECT_FALSE(root->name.empty());
    EXPECT_GT(root->children.size(), 0u);
}
```

- [ ] **Step 2: Run, expect failure (no NiNode in variant)**

- [ ] **Step 3: Add `NiNode` struct to `block.h`**

```cpp
// in nif::Block scope, add the following types and append NiNode to the variant.
struct NiNode {
    std::string name;
    std::uint32_t flags = 0;
    Vec3 translation{};
    Mat3x3 rotation{};
    float scale = 1.0f;
    Vec3 velocity{};
    std::vector<BlockId> children_ids;
    std::vector<BlockHandle> children;
    std::vector<BlockId> effects_ids;
    std::vector<BlockHandle> effects;
    BlockId properties_first = kNullBlockId;
    // ... add fields per nif.xml schema for the BC version ...
};
```

Update `Block` variant: `using Block = std::variant<std::monostate, NiNode>;`.

- [ ] **Step 4: Write `parse_NiNode` in `blocks/ni_node.cc`**

```cpp
// native/src/nif/src/blocks/ni_node.cc
#include "../reader.h"
#include "../header.h"
#include "../dispatch.h"

#include <nif/block.h>

namespace nif {

namespace {

NiNode parse_NiNode_impl(Reader& r, const HeaderInfo& h) {
    NiNode n;
    // Field order strictly per nif.xml schema for v <h.version.value>:
    //   1. name (length-prefixed string OR string-table index, depending on version)
    //   2. extra-data refs
    //   3. controller ref
    //   4. flags (uint16 or uint32 depending on version)
    //   5. translation (Vec3)
    //   6. rotation (Mat3x3)
    //   7. scale (float)
    //   8. velocity (Vec3)
    //   9. properties (array of BlockIds)
    //   10. has_bbox + bbox (sometimes)
    //   11. children (array of BlockIds)
    //   12. effects (array of BlockIds)
    //
    // Implement per the schema, calling r.read_*() for each field.
    // Use h.strings for string-table-indexed names if version >= 0x14010003.

    if (h.version.value >= 0x14010003) {
        auto idx = r.read_uint32();
        if (idx < h.strings.size()) n.name = h.strings[idx];
    } else {
        n.name = r.read_string_uint32();
    }
    // ... rest of the fields ...
    return n;
}

}  // namespace

NIF_REGISTER_BLOCK(NiNode, [](Reader& r, const HeaderInfo& h) -> Block {
    return parse_NiNode_impl(r, h);
});

}  // namespace nif
```

The `// ...` is filled in by referencing `native/third_party/openmw_nif/node.cpp::NiNode::read` and the NifSkope schema. Each field translates directly to `r.read_<type>()`.

- [ ] **Step 5: Add canonical-dump emitter for NiNode**

In `canonical_dump.cc`, dispatch on each block via `std::visit`:

```cpp
namespace {

void emit_NiNode(const NiNode& n, std::ostream& out, int indent) {
    auto pfx = [&](int level) { for (int i = 0; i < level; ++i) out << "  "; };
    pfx(indent);     out << "name: \\"" << n.name << "\\"\\n";
    pfx(indent);     out << "flags: 0x" << std::hex << std::setw(4)
                       << std::setfill('0') << n.flags << std::dec
                       << std::setfill(' ') << "\\n";
    pfx(indent);     out << "translation: (" << n.translation.x << ", "
                       << n.translation.y << ", " << n.translation.z << ")\\n";
    // ... etc ...
}

void emit_block(const Block& b, std::ostream& out, int indent) {
    std::visit([&](const auto& concrete) {
        using T = std::decay_t<decltype(concrete)>;
        if constexpr (std::is_same_v<T, std::monostate>) {
            // skipped/unimplemented
        } else if constexpr (std::is_same_v<T, NiNode>) {
            emit_NiNode(concrete, out, indent);
        }
    }, b);
}

}  // namespace
```

In `dump_canonical`, after the file-header lines, iterate blocks and call `emit_block` for each.

- [ ] **Step 6: Add OpenMW NiNode emitter in `openmw_canonical_dump.cc`**

```cpp
// Pseudocode — adapt to OpenMW's actual API:
// for each record in NIFFile, if it's a NiNode, emit fields in same format.
```

Inspect `native/third_party/openmw_nif/node.hpp` for OpenMW's NiNode struct to know which member names to read.

- [ ] **Step 7: Wire resolver to fix up NiNode children/effects**

In `resolver.cc`, expand `resolve_references`:

```cpp
void resolve_references(File& f) {
    for (auto& b : f.blocks) {
        std::visit([&](auto& concrete) {
            using T = std::decay_t<decltype(concrete)>;
            if constexpr (std::is_same_v<T, NiNode>) {
                concrete.children.clear();
                concrete.children.reserve(concrete.children_ids.size());
                for (auto id : concrete.children_ids) {
                    concrete.children.push_back(resolve_handle(f, id));
                }
                concrete.effects.clear();
                concrete.effects.reserve(concrete.effects_ids.size());
                for (auto id : concrete.effects_ids) {
                    concrete.effects.push_back(resolve_handle(f, id));
                }
            }
        }, b);
    }
    // root: typically the first block. Some NIFs explicitly designate it
    // via a `roots` table after the footer; for v1, default to block 0.
    if (!f.blocks.empty()) {
        f.root = BlockHandle{ &f.blocks[0] };
    }
}
```

- [ ] **Step 8: Build, run all tests**

```bash
cmake --build build -j
ctest --test-dir build --output-on-failure
```

Expected: NiNode tests pass; HeaderTest still passes; DiffHarness either passes (if NiNode dumps match) or fails with a clear diff. If DiffHarness fails, examine the diff: usually a field-order or float-format issue. Fix and re-run.

- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(nif): NiNode parser, dumper, resolver fix-up"
```

---

### Tasks 22–25: NiTriShape, NiTriShapeData, NiTexturingProperty + NiSourceTexture, NiMaterialProperty

For each block, follow the **block-parser recipe** from the top of this plan. The procedure is identical to Task 21's structure — only the field list, OpenMW reference file, and test assertions change. Per task:

**Task 22: NiTriShape** — `blocks/ni_tri_shape.cc`. Reference: `node.cpp` in mirror. Extends NiNode-like base (translation, rotation, scale) and adds geometry-data-ref (`BlockId`), skin-instance-ref (`BlockId`), shader-property-ref (`BlockId` if ≥ v20). Test: load Galaxy, find a NiTriShape, assert it has a non-null geometry reference.

**Task 23: NiTriShapeData** — same file. Reference: `data.cpp` in mirror, search `NiTriShapeData::read`. Has vertex array, normals array, vertex-colors array, uv-sets, triangle-index array, bounding sphere. Test: load Galaxy, find a NiTriShapeData, assert vertex count > 0 and triangle count > 0.

**Task 24: NiTexturingProperty + NiSourceTexture** — `blocks/property.cc`. References: `property.cpp` and `texture.cpp` in mirror. NiTexturingProperty has up to 7 texture slots (base, dark, detail, gloss, glow, bump, decal) plus apply-mode flags. NiSourceTexture wraps a texture filename (string) + use-internal-texture flag. Test: load Galaxy, find first NiTexturingProperty, assert base-texture slot points to a NiSourceTexture whose filename ends in `.dds` or `.tga`.

**Task 25: NiMaterialProperty** — same file. Reference: `property.cpp::NiMaterialProperty`. Has ambient (Color3), diffuse (Color3), specular (Color3), emissive (Color3), glossiness (float), alpha (float). Test: load Galaxy, find a NiMaterialProperty, assert all four colors are within [0, 1] component-wise.

Each task:
1. Add struct + variant member to `block.h`.
2. Add `parse_<Block>` in the appropriate `blocks/<file>.cc` and `NIF_REGISTER_BLOCK`.
3. Add canonical-dump emitter in `canonical_dump.cc`.
4. Add OpenMW emitter in `openmw_canonical_dump.cc`.
5. Add resolver fix-up in `resolver.cc` for any cross-block ref fields.
6. Add a unit test in `blocks_test.cc` per the pattern.
7. Run `ctest`, verify diff harness still passes (now over more blocks).
8. Commit with message `feat(nif): <BlockName> parser`.

If diff harness fails on shared blocks: that's the whole point — the canonical dumps disagree. Read the diff output, identify which field, fix our parser. Common bugs: wrong field order, signed/unsigned mismatch, version-conditional fields read unconditionally.

---

### Tasks 26: Property family — alpha/vertex-color/zbuffer/specular

Same recipe. Reference: all in `native/third_party/openmw_nif/property.cpp`. These are smaller blocks (a few flags each). Add them in one task to avoid task-list bloat:

- NiAlphaProperty — flags (uint16), threshold (uint8).
- NiVertexColorProperty — flags (uint16), vertex-mode, lighting-mode.
- NiZBufferProperty — flags (uint16), function.
- NiSpecularProperty — flags (uint16).

Skip any block in this list that doesn't appear in `v1_block_manifest.md`. Test: one assertion per block (load any sample that contains it, assert flags field is reasonable, e.g. non-zero or matches NifSkope's display).

Commit: `feat(nif): alpha/vertex-color/zbuffer/specular property parsers`.

---

### Task 27: Skinning — NiSkinInstance, NiSkinData, NiSkinPartition

Reference: search the mirror for "Skin" — likely in `node.cpp` or its own file. Schema in NifSkope.

- NiSkinInstance — refs to NiSkinData, NiSkinPartition, skeleton-root NiNode; bone refs.
- NiSkinData — root transform; per-bone bone-data structs with inverse-bind transform + per-vertex weights.
- NiSkinPartition — per-partition vertex/index buffers for GPU skinning.

Test: load `BodyKlingon.nif`, find a NiSkinInstance, assert bone count > 0 and skin-data ref is non-null.

Commit: `feat(nif): skinning parsers (NiSkinInstance, NiSkinData, NiSkinPartition)`.

---

### Task 28: Manifest gap-fill

Now that the well-known blocks are implemented, see what's left.

- [ ] **Step 1: Diff manifest against implemented blocks**

```bash
# Manifest's block list:
awk -F'`' '/^\\| `Ni|^\\| `Bc|^\\| `BS/ { print $2 }' \
    native/src/nif/docs/v1_block_manifest.md | sort -u > /tmp/manifest.txt

# Implemented blocks (anything mentioned in NIF_REGISTER_BLOCK):
grep -hoE 'NIF_REGISTER_BLOCK\\(([A-Za-z0-9_]+)' \
    native/src/nif/src/blocks/*.cc | sed 's/NIF_REGISTER_BLOCK(//' \
    | sort -u > /tmp/done.txt

comm -23 /tmp/manifest.txt /tmp/done.txt
```

- [ ] **Step 2: For each remaining block, classify**

For each block in the diff:

- **Has an OpenMW analog?** Grep `native/third_party/openmw_nif/` for the type name. If yes, follow the block-parser recipe — diff harness validates correctness.
- **No OpenMW analog (BC-specific)?** Follow the recipe but skip steps that require an OpenMW emitter; instead, write a unit test in `bc_block_test.cc` asserting at least one non-trivial field, with the expected value cross-referenced in NifSkope.

Commit each block as its own commit: `feat(nif): <BlockName> parser` (Morrowind analog) or `feat(nif): <BlockName> parser (BC-specific) + unit test`.

- [ ] **Step 3: Tighten the dispatch fallback**

Once `comm -23 /tmp/manifest.txt /tmp/done.txt` is empty, replace the permissive `try/catch UnknownBlockType` in `file.cc` (Task 18 Step 3) with hard-fail behavior:

```cpp
f.blocks.push_back(Dispatch::instance().parse_block(type_name, r, h, expected_size));
// no try/catch; UnknownBlockType propagates up
```

Run all tests: `ctest --test-dir build --output-on-failure`. Expected: still green.

- [ ] **Step 4: Commit the tightening**

```bash
git add native/src/nif/src/file.cc
git commit -m "feat(nif): manifest fully covered, dispatch hard-fails on unknown blocks"
```

---

## Phase F — Ship gate

### Task 29: Verify success criteria

- [ ] **Step 1: Re-confirm spec criteria**

For each of the four success criteria in `2026-05-08-nif-loader-design.md`:

1. `nif::load(path)` parses each of the four sample files without throwing → run `ctest -R HeaderTest`, expect 4 passes.
2. Diff harness passes for shared blocks → run `ctest -R DiffHarness`, expect 4 passes.
3. BC-specific blocks have unit tests → run `ctest -R 'NiNode|NiTriShape|NiSkin|Bc'`, every BC-block test passes.
4. macOS + Linux builds clean → on each platform run `cmake -S . -B build && cmake --build build && ctest --test-dir build`. Document any platform-specific issues.

- [ ] **Step 2: Update spec status**

Change `**Status:** Approved` to `**Status:** Implemented` in `docs/superpowers/specs/2026-05-08-nif-loader-design.md`.

```bash
git add docs/superpowers/specs/2026-05-08-nif-loader-design.md
git commit -m "docs(nif): mark loader spec implemented; v1 ship gate met"
```

- [ ] **Step 3: Open follow-up issues for deferred work**

Review the spec's "Out of scope" section and the omitted-blocks list. Each item is a future sub-project (texture-pixel decode, scene-graph runtime, Python bindings, expanded asset coverage). Note them in `docs/gap_analysis.md` under their respective gaps so the next planning session has them surfaced.

---

## Self-review notes

Spec coverage check: every success criterion in the spec has a task. Block-type coverage relies on Task 9 (manifest) and Task 28 (gap-fill) — together they ensure every block in the four sample files is implemented before the ship gate.

Type consistency check: `BlockHandle`, `BlockId`, `Block` (variant), `File`, `HeaderInfo`, `Reader`, `Dispatch`, `parse_header` — all referenced consistently across tasks. `NIF_REGISTER_BLOCK` macro consistently invoked. `kNullBlockId = -1` consistent in types.h, error paths, and resolver.

Placeholder check: two intentional placeholders in Task 13 (`/* TBD-from-manifest */`) and Task 16's `sample_paths.h` (`0, 0, 0`) — both explicitly call out that values are filled in from `v1_block_manifest.md` once Task 9 completes. These are not omissions; they are dependency-ordered tasks.

The manifest-driven nature of Tasks 26–28 means later block parsers don't have fully-detailed code in this plan. That's deliberate: the field list and test assertions can only be specified once the manifest is committed (Task 9). Each remaining block follows the block-parser recipe documented at the top of the file, which is itself complete.
