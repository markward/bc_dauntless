# NIF Loader — Design Spec

**Date:** 2026-05-08
**Status:** Implemented (v1 ship gate met 2026-05-09)
**Phase:** 2 (Full C++ engine), first sub-project

## Outcome

The four spec sample files parse end-to-end and reach the `End Of File`
sentinel:

| Sample | Path | Blocks parsed |
|---|---|---|
| Galaxy ship | `game/data/Models/Ships/Galaxy/Galaxy.nif` | 68 |
| CardStarbase | `game/data/Models/Bases/CardStarbase/CardStarbase.nif` | 173 |
| BodyKlingon | `game/data/Models/Characters/Bodies/BodyKlingon/BodyKlingon.nif` | 169 |
| EBridge interior | `game/data/Models/Sets/EBridge/EBridge.nif` | 565 |

**Full corpus coverage: all 253 .nif files under `game/data/Models/` reach
End Of File.** Verified via `native/tools/scan_nifs/scan_nifs` walking the
entire asset tree.

Total block parsers implemented (v3.0 + v3.1): 27.
- Scene / spatial: NiNode, NiBone, NiCamera
- Geometry: NiTriShape, NiTriShapeData
- Materials / textures: NiMaterialProperty, NiTexturingProperty,
  NiMultiTextureProperty, NiTextureModeProperty, NiTextureProperty,
  NiImage, NiRawImageData
- Render-state properties: NiZBufferProperty, NiVertexColorProperty,
  NiAlphaProperty
- Lights: NiPointLight, NiSpotLight, NiAmbientLight, NiDirectionalLight
- Animation: NiKeyframeController, NiKeyframeData, NiTriShapeSkinController,
  NiFlipController, NiVisController, NiVisData, NiLookAtController,
  NiRollController, NiFloatData
- Extra data: NiStringExtraData, NiBinaryVoxelExtraData, NiBinaryVoxelData

44/44 GTests pass. `scan_nifs` reports 253/253 EOF, 0 stuck, 0 errors.

Key v3.1-specific findings discovered during implementation:

- **bool is uint32 (non-zero == true) for v3.1** — niflib's
  `ReadBool(version <= 0x04010001)` returns `(ReadUInt(in) != 0)`. BC files
  encode bool fields with hash-like sentinel uint32 values (e.g.
  `0x03e54648`), not literal 0/1.
- **NiMultiTextureProperty is NOT NiTexturingProperty** despite the
  schema's `inherit="NiTexturingProperty"` — niflib has custom code with a
  much simpler body (5 MultiTextureElement entries).
- **niflib (BSD)** at `niftools/niflib` was the authoritative reference for
  v3.1 reading order. nifxml documents the format but niflib's auto-gen
  Read methods capture v3.1 quirks the schema doesn't.
- **niftools/max_nif_plugin (BSD)** was the user's pointer that led us to
  niflib (it depends on niflib as a submodule). Both are now sibling clones
  used as algorithmic reference (not built or linked into open_stbc).

## v3.1 amendment (post-discovery, 2026-05-08)

During Task 4 of the implementation plan, we confirmed by inspecting
`Galaxy.nif` that **BC uses NIF version 3.1**, not v4.x or v10+/v20+ as the
original spec assumed. NifSkope's nifxml schema names BC explicitly under
`<version id="V3_1" num="3.1" supported="false">` — the format is documented
but unsupported by NifSkope's renderer. OpenMW targets Morrowind v4.0.0.2+
and does not parse v3.x; the diff oracle relationship described below is
therefore not viable on BC's actual files.

**Approved adjustments to this spec:**

1. **Oracle replaced with snapshot tests + End-Of-File sanity check.** The
   OpenMW-as-diff-oracle relationship is dropped. A separate "structural
   walker" oracle was briefly considered but isn't viable: v3.1's format
   stores no block-size info — block boundaries are only knowable by parsing
   each block to its end. So a thin walker would have to be the parser
   itself. Correctness is therefore established by:
   - Snapshot tests against committed canonical-text dumps, validated once
     by hand using a hex viewer cross-referenced with NifSkope's nifxml
     schema (the schema is authoritative even where NifSkope's renderer
     falls short).
   - One sanity test per sample file: the parser reaches the `End Of File`
     sentinel block (which closes every BC NIF) and consumes all bytes
     exactly. A misread block-body length anywhere in the file desynchronizes
     parsing and fails this check — so it catches whole categories of
     structural bugs cheaply.
2. **OpenMW mirror retained as algorithmic reference.** Block-parsing logic
   for types that persisted across NIF versions (NiNode field order, vertex
   array layout in NiTriShapeData, etc.) draws on OpenMW's mirrored source.
   The mirror stops being a build target — it's documentation we can read
   alongside the schema.
3. **Success criterion #2 rewritten** as: "canonical-text dumps from our
   parser match committed snapshots for each of the four sample files; the
   parser reaches `End Of File` and consumes all bytes for each."
4. **NIF version constants in `nif/version.h`** target v3.1 specifically:
   `kBcVersionValue = 0x03010000` (or whatever the inventory tool reports).
5. **Header parsing format is the pre-v10 path.** v3.1 files start with
   several lines of vendor text, each ending in `\n` — line 1 is the magic
   line `"NetImmerse File Format, Version 3.1"`, followed by studio /
   copyright lines (e.g., "Numerical Design Limited, Chapel Hill, NC 27514"
   and "Copyright (c) 1996-2000"). After the text, blocks are walked
   linearly. No block-type table, no block-size table, no string table.
   Each block is prefixed with a `uint32_t name_length` and that many ASCII
   bytes naming the type, then the block body. The file ends with a sentinel
   block named `"End Of File"`.

The rest of this spec stands as written; treat any reference to "OpenMW
oracle" as "structural walker + snapshot," and any reference to "post-v10
header parsing" as "v3.1 header parsing" per item 5 above.

---

## Goal

Build a fresh C++20 NIF parser library, `nif::`, that reads four representative
BC asset files end-to-end into an in-memory representation. The parser is the
foundation for every subsequent Phase 2 sub-project (asset pipeline, scene
graph, render pipeline). Correctness of the loader is established by a
structural block-walker that agrees with our parser on every block boundary,
and by snapshot tests on canonical-text dumps validated once by hand using a
hex viewer cross-referenced with NifSkope's nifxml schema.

## Non-goals

- No rendering, GPU work, window, or input handling
- No scene-graph runtime (no transform stepping, animation playback, or
  controller evaluation)
- No Python integration / pybind11 bindings
- No texture-pixel loading (DDS/TGA decode is a later sub-project; we parse
  texture *references* only)
- No NIF writing — read-only library
- No NIF coverage beyond block types present in the four sample files
- No CLI tool — library + tests only in v1

## Success criteria (v1 ship gate)

1. `nif::load(path)` parses each of the four sample files without throwing.
2. For every block in those files whose type is also handled by OpenMW's
   parser, the canonical-text dump from our parser equals OpenMW's, byte for
   byte.
3. For every BC-specific block in those files, our parser produces a
   structured representation (not "unknown bytes"), and at least one GTest
   assertion verifies a non-trivial field of that block.
4. `cmake --build build && ctest` passes from a clean checkout on macOS and
   Linux. Windows-friendly is a bonus but not a v1 gate.

### Sample files

- Ship: `game/data/Models/Ships/Galaxy/Galaxy.nif`
- Base: `game/data/Models/Bases/CardStarbase/CardStarbase.nif`
- Character body: `game/data/Models/Characters/Bodies/BodyKlingon/BodyKlingon.nif`
- Interior set: `game/data/Models/Sets/EBridge/EBridge.nif`

These four cover the asset archetypes that vary most in NIF block usage.
"Effects" was considered as a fourth category but BC's particle effects appear
to be runtime-procedural rather than .nif-backed (gap_analysis.md notes:
"procedural effects reimplemented from Python source spec"); the interior set
substitutes to keep block-type variety high.

---

## Architecture

### License posture

open_stbc is GPLv3 (root `LICENSE`). OpenMW is GPLv3. NifSkope is reference
documentation only — its `nif.xml` schema and tree-view behaviour inform our
implementation but no NifSkope code is incorporated. Mirroring
`openmw/components/nif/` into our tree is straightforward: preserve original
file headers, copy `LICENSE`, add attribution in `THIRD_PARTY_NOTICES.md` at
the project root. README gets a "References & acknowledgements" section
calling out both OpenMW and NifSkope teams.

### CMake targets

| Target | Type | Purpose |
|---|---|---|
| `nif` | static library | Our parser. The only NIF artifact the rest of the engine ever links against. |
| `nif_dump_canonical` | object library | Canonical-text serializer for `nif::File`. Linked into the test binary only. |
| `openmw_nif_oracle` | static library | Mirrored OpenMW parser, compiled from `native/third_party/openmw_nif/`. Used **only** by the test binary. |
| `openmw_nif_dump_canonical` | object library | Canonical-text serializer wrapping OpenMW's parser output. |
| `nif_tests` | GTest executable | All unit tests + the diff harness. |

### Directory layout

```
native/
  CMakeLists.txt
  src/
    nif/
      CMakeLists.txt              # builds `nif` static lib
      include/nif/                # public headers
        file.h                    # nif::File, nif::load()
        block.h                   # std::variant of all block types
        types.h                   # Vec3, Mat3x3, BlockId, etc.
        version.h                 # nif::Version, BC version detection
      src/
        file.cc                   # nif::load entry point + dispatch
        reader.{h,cc}             # binary stream helpers (LE, bounds-checked)
        resolver.{h,cc}           # cross-block reference fix-up pass
        blocks/
          ni_node.cc              # NiNode + any BC variants in same file
          ni_tri_shape.cc         # NiTriShape + NiTriShapeData
          property.cc             # NiTexturingProperty, NiMaterialProperty, etc.
          skinning.cc             # NiSkinInstance, NiSkinData, NiSkinPartition
          # ... one .cc per block-family ...
      docs/
        v1_block_manifest.md      # generated by tools/list_nif_blocks.py, committed
        v1_omitted_blocks.md      # OpenMW-handled blocks deliberately not in v1
        canonical_dump_format.md  # canonical-text format spec (lives next to the dumper)
  third_party/
    openmw_nif/
      CMakeLists.txt              # builds `openmw_nif_oracle`
      README.md                   # "mirrored from openmw/components/nif/"
      LICENSE                     # OpenMW LICENSE copy (GPLv3)
      UPSTREAM_VERSION            # commit SHA of last sync_openmw_nif.sh run
      patches/                    # local patches re-applied by the sync script (initially empty)
      *.cpp / *.hpp               # 30 files mirrored verbatim, original headers preserved
  tests/
    CMakeLists.txt                # builds `nif_tests`
    nif/
      canonical_dump.{h,cc}       # nif_dump_canonical
      openmw_canonical_dump.cc    # mirrors canonical_dump for OpenMW types
      header_test.cc              # per-sample-file header sanity
      diff_harness_test.cc        # parameterized over the four sample files
      bc_block_test.cc            # one test per BC-specific block
      resolver_test.cc            # synthetic cross-block reference scenarios
      error_test.cc               # synthetic malformed inputs
tools/
  list_nif_blocks.py              # one-off block-type inventory (Python; OK for tooling)
  sync_openmw_nif.sh              # rsync ../openmw/components/nif/ → third_party/openmw_nif/
THIRD_PARTY_NOTICES.md            # project-root attribution for mirrored OpenMW NIF parser
```

### No runtime sibling dependency

The `../openmw` clone is needed only when running `tools/sync_openmw_nif.sh`
to re-mirror. Build, test, and CI work from a fresh checkout of `open_stbc`
alone. The first-time mirror is committed as part of the implementation;
future re-mirrors are explicit, reviewable single commits with the upstream
SHA in the message.

### Boundary discipline

- `nif` (the public library) never includes anything from `third_party/`.
- The OpenMW-oracle relationship lives entirely inside `nif_tests`.
- Anyone consuming `nif` later (the renderer sub-project, future Python
  bindings) sees a clean OpenMW-source-free library.
- BC blocks are co-located with their related Morrowind block types in the
  same source file. No `bc/` subdirectory in either `include/` or `src/`.
- Morrowind-only block types not used by BC are not implemented in our
  parser. They are listed in `v1_omitted_blocks.md`.

### Parser data flow

1. `nif::load(path)` opens the file, reads the header (version, user-version,
   endianness, block-type table, block-size table, string table for BC's
   version).
2. The header drives a block-dispatch loop: each block-type-table entry calls
   a registered parser via a static dispatch table keyed on type name.
3. Each block parser consumes exactly the bytes claimed in the block-size
   table, populates a strongly-typed struct, returns it as a `nif::Block`
   variant member.
4. After all blocks are parsed, the resolver pass walks each block's
   reference fields and replaces file-offset block indices (`int32_t`) with
   `BlockHandle`s pointing into the file's block vector.
5. Result: `nif::File` is a value-type owning `std::vector<Block>` plus
   resolved root references.

---

## Public API

Sketches below pin down shape, not literal final code. Final names get
refined during implementation.

### `nif/version.h`

```cpp
namespace nif {
struct Version {
    uint32_t value;        // packed 4-byte version, e.g. 0x04000002 for v4.0.0.2
    uint32_t user_version; // BC and other games use this to disambiguate
};
bool is_bc(Version v);
}
```

The exact BC version constant is filled in empirically when the first sample
file parses successfully (resolves OQ-3.1 from `gap_analysis.md`). The design
does not pretend to know it now.

### `nif/types.h`

```cpp
namespace nif {
struct Vec3   { float x, y, z; };
struct Vec4   { float x, y, z, w; };
struct Quat   { float x, y, z, w; };
struct Mat3x3 { float m[9]; };           // row-major
struct Color3 { float r, g, b; };
struct Color4 { float r, g, b, a; };
using BlockId = int32_t;                  // -1 = null reference
using StringRef = std::string;
}
```

### `nif/block.h`

```cpp
namespace nif {
struct NiNode { /* fields, including std::vector<BlockHandle> children */ };
struct NiTriShape { /* ... */ };
struct NiTriShapeData { /* ... */ };
struct NiTexturingProperty { /* ... */ };
// ... only block types BC actually uses ...
struct BcHardpoint { /* BC-specific block, lives alongside related node code */ };

using Block = std::variant<
    std::monostate,        // null / unresolved
    NiNode,
    NiTriShape,
    NiTriShapeData,
    NiTexturingProperty,
    BcHardpoint,
    /* ... only block types listed in v1_block_manifest.md ... */
>;

struct BlockHandle {
    const Block* ptr;     // nullptr = null reference
    explicit operator bool() const { return ptr != nullptr; }
    const Block& operator*() const { return *ptr; }
    const Block* operator->() const { return ptr; }
};
}
```

`BlockHandle` is `const`-only in v1: the loader produces, consumers read.
No in-place mutation, no NIF writing.

### `nif/file.h`

```cpp
namespace nif {
struct File {
    Version version;
    std::vector<Block> blocks;       // owns all blocks
    BlockHandle root;                // typically the first / header-designated root NiNode
    std::vector<StringRef> strings;  // resolved string table (or empty if pre-stringtable version)
    std::filesystem::path source;    // for diagnostics

    File() = default;
    File(const File&) = delete;       // move-only; large vertex/index buffers
    File(File&&) = default;
    File& operator=(const File&) = delete;
    File& operator=(File&&) = default;
};

File load(const std::filesystem::path& path);   // throws nif::ParseError
}
```

### Error handling

Exceptions, not `Result`/`expected`. Parse errors are rare and unrecoverable
in practice (a malformed NIF means a missing model, which is a content/build
problem, not something callers handle routinely). A typed exception hierarchy
with file path + byte offset attached:

```cpp
namespace nif {
class ParseError : public std::runtime_error {
public:
    std::filesystem::path file;
    std::optional<size_t> byte_offset;
    std::optional<std::string> block_type;
};
class UnknownBlockType : public ParseError { /* ... */ };
class TruncatedBlock : public ParseError { /* ... */ };
class VersionMismatch : public ParseError { /* ... */ };
}
```

### Canonical-text dump (test-only API)

```cpp
// In tests/, NOT public:
namespace nif::test {
void dump_canonical(const File&, std::ostream&);
void dump_canonical_openmw(const Nif::NIFFile&, std::ostream&);
}
```

Format is line-oriented, deterministic, version-stable: one block per
indent-scope, fields in a fixed order, floats printed with `%.6g`, vectors
as `(x, y, z)`. The format itself is decided during implementation; a brief
spec lives in `native/src/nif/docs/canonical_dump_format.md`. The design
commits only to: deterministic output, identical shape between the two
emitters so byte-equal `==` is the diff.

### API rationale (rejected alternatives)

- **`std::variant` over virtual class hierarchy**: variant gives value
  semantics, no heap allocation per block, exhaustive `std::visit`, modern
  C++ style. Cost: `Block` size = size of largest variant member; mitigated
  because heavy blocks (vertex/index data) keep bulk in `std::vector`
  members so `sizeof(Block)` stays bounded.
- **Exceptions over `expected<File, Error>`**: callers can't realistically
  recover from a malformed NIF mid-mission; it propagates as "asset failed
  to load." Exceptions keep the happy path readable.
- **Move-only `File`**: owns large buffers; copying is almost always a bug.

---

## Block-type coverage

### Empirical manifest, not pre-declared

The v1 block manifest is determined by inspection, not guessing. The first
implementation task is the inventory step: `tools/list_nif_blocks.py` reads
only the block-type table at the start of each NIF (which sits at a known
offset right after the header and lists every block class as a
length-prefixed string). The tool walks the four sample files, prints a
deduplicated, sorted list of block types with per-file counts, and commits
the result as `native/src/nif/docs/v1_block_manifest.md`. That manifest is
the authoritative v1 coverage list.

A second pass produces `v1_omitted_blocks.md`:
`(types OpenMW handles) − (types in v1_block_manifest.md)`. Future
contributors then know which blocks are deliberately skipped versus which
weren't in scope.

### Implementation order (after the inventory step)

1. **File-level scaffolding + resolver** — `nif::Reader`, `nif::File`,
   header + footer + block-type table + block-size table + string table
   parsing, plus the resolver pass that converts cross-block indices to
   `BlockHandle`s. Block parsers are stubs that emit `std::monostate`, so
   the resolver has trivial work but is exercised from day one. Diff
   harness already runs: both parsers should agree on header fields.
2. **Scene-tree spine** — NiNode + NiTriShape + NiTriShapeData. The
   resolver is now exercised on real cross-block references (children
   arrays, geometry-data refs). After this, the four sample files have a
   parseable geometry skeleton.
3. **Materials & textures** — NiTexturingProperty, NiSourceTexture,
   NiMaterialProperty, then the alpha/vertex-color/specular/zbuffer
   properties as the manifest demands.
4. **Skinning** — NiSkinInstance + NiSkinData + NiSkinPartition (almost
   certainly required by `BodyKlingon.nif`).
5. **Controllers/animation** — only the controller types the manifest
   lists. If sample files have no animation, this step is empty.
6. **BC-specific blocks** — implemented one at a time with a per-block unit
   test. The OpenMW oracle will throw `UnknownBlockType` on these; the diff
   harness treats "OpenMW failed, ours succeeded with non-trivial parse" as
   a passing case for these block types.

### Diff-harness behaviour in asymmetric cases

| Block status | Our parser | OpenMW parser | Diff verdict |
|---|---|---|---|
| Shared (Morrowind+BC) | full parse | full parse | strings must equal |
| BC-specific | full parse | UnknownBlockType (or partial) | our parse exists; unit test on a known field |
| Morrowind-only | not implemented (won't appear in samples) | full parse | n/a — block never encountered |

### Manifest re-run policy

If a fifth sample file is added later (or scope expands to a wider asset set
in a follow-up sub-project), the inventory tool re-runs and produces a new
manifest. Adding a new block type is a deliberate edit-and-design action,
not silent drift.

---

## Test plan

Five test categories live in `native/tests/nif/`. All run under `ctest`;
full `nif_tests` binary completes in well under a minute on a developer
machine.

### 1. Header tests — `header_test.cc`

For each of the four sample files, read just the header (no block bodies)
and assert hardcoded expected values: NIF version, user-version (BC's
identifier), block count, root-block-index. Fast, deterministic, sanity-
checks the file-level reader before any block code runs.

### 2. Diff-harness tests — `diff_harness_test.cc`

Parameterized over the four sample files. Per file: full `nif::load` plus
full OpenMW oracle load, both emit canonical-text dumps, comparison via
`EXPECT_EQ`:

```cpp
TEST_P(DiffHarness, MatchesOpenMWOnSharedBlocks) {
    auto our_file = nif::load(GetParam().path);
    auto oracle = openmw_oracle::load(GetParam().path);

    auto our_dump = canonical_dump(our_file, /*shared_blocks_only=*/true);
    auto oracle_dump = canonical_dump_openmw(oracle, /*shared_blocks_only=*/true);

    EXPECT_EQ(our_dump, oracle_dump);
}
```

`shared_blocks_only=true` strips BC-specific blocks from both dumps before
comparison (BC blocks make OpenMW raise `UnknownBlockType`, which we catch
and represent as an explicit "skipped" placeholder in the OpenMW dump). On
failure, gtest's `EXPECT_EQ` prints a unified diff of the two strings.

### 3. BC-block unit tests — `bc_block_test.cc`

One test per BC-specific block type the manifest discovers. Each test loads
a file known to contain the block, navigates to a known instance, asserts
at least one non-trivial field. Expected values are cross-referenced against
NifSkope's tree view of the file during implementation and committed
alongside the test.

### 4. Resolver tests — `resolver_test.cc`

Synthetic in-memory NIF files (constructed in C++, not loaded from disk)
exercising:

- Forward and backward block references resolve to the right `BlockHandle`
- `BlockId == -1` resolves to a falsy `BlockHandle`
- Self-referential blocks don't infinite-loop
- Out-of-range block index throws `nif::ParseError`

### 5. Negative tests — `error_test.cc`

Hand-crafted malformed inputs (small `unsigned char[]` byte arrays, no
on-disk files):

- Truncated file mid-header → `TruncatedBlock` or `ParseError`
- Wrong magic bytes → `VersionMismatch`
- Block-size-table entry larger than remaining bytes → `TruncatedBlock`
- Block-type-table entry referencing an unknown name → `UnknownBlockType`
  with the offending name in the exception
- All exceptions carry file path (`"<synthetic>"` for in-memory inputs)
  and byte offset

### Fixture handling

Test files reference the four sample NIFs by relative path from the project
root: `game/data/Models/Ships/Galaxy/Galaxy.nif`. We do **not** copy them
into `tests/nif/fixtures/` — `game/` is gitignored (BC install) and copying
would either bloat the repo or invalidate tests for users without the
install. Tests that need a sample file check existence at startup and
`GTEST_SKIP()` with a clear message if missing, so contributors without a
BC install can still build and run header / resolver / error / synthetic
tests.

Synthetic fixtures used by resolver and negative tests live as
`unsigned char[]` arrays in the test sources (small enough to inline).

### CI implications (deferred)

Diff-harness and BC-block unit tests can't run in a public CI without a BC
install. Two options when CI is set up later: (a) self-hosted runner with
BC installed, (b) commit anonymized minimal NIFs constructed by hand to
exercise the same blocks. Decision deferred to whenever CI is actually set
up — likely during the renderer sub-project.

### Running tests

```bash
cmake -S . -B build
cmake --build build -j
ctest --test-dir build --output-on-failure
```

---

## Dev workflow

### Adding a new block parser

1. Add the block's struct to the appropriate header in
   `native/src/nif/include/nif/`. Co-locate with related blocks.
2. Add it as a member of the `nif::Block` `std::variant` in `block.h`.
3. Add a parsing function in the matching `.cc` under `src/blocks/`.
   Signature: `Block parse_<block_name>(Reader&, const Header&)`.
4. Register the parser in the central dispatch table in `file.cc`.
5. Add a canonical-dump emitter in `tests/nif/canonical_dump.cc`.
6. If the block has a Morrowind analogue OpenMW handles, add a matching
   emitter in `openmw_canonical_dump.cc`. Diff harness picks it up
   automatically. If BC-specific, write a unit test in `bc_block_test.cc`
   asserting at least one non-trivial field.
7. Run `ctest --output-on-failure`.

### Re-mirroring OpenMW

`tools/sync_openmw_nif.sh` is the only path for updating
`native/third_party/openmw_nif/`. The script:

1. Verifies `../openmw` is a clean git checkout.
2. Records the upstream commit SHA in
   `native/third_party/openmw_nif/UPSTREAM_VERSION`.
3. `rsync`s files from `../openmw/components/nif/` over the mirror.
4. Re-applies any local patches from
   `native/third_party/openmw_nif/patches/` (initially empty — patches only
   exist if upstream OpenMW breaks something we need).

Re-mirroring is a deliberate, reviewable single commit with the upstream
SHA in the commit message.

---

## Risks (ordered by likelihood × impact)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| OpenMW's `components/nif/` doesn't compile standalone — pulls helper headers from `components/misc/`, `components/files/`, etc. | medium | medium | First implementation step after scaffolding is "make `openmw_nif_oracle` compile." If it requires extra OpenMW headers, mirror those too into `third_party/openmw_nif/` (still GPLv3, still upstream). Update `THIRD_PARTY_NOTICES.md` with the expanded file list. |
| BC NIF version isn't in OpenMW's supported set, so the oracle rejects all four sample files and the diff harness is vacuous. | low | high | If this materializes, swap diff strategy: snapshot tests against our own first-stable output, validated once by hand in NifSkope. The diff harness becomes a future extension when oracle coverage expands. v1 ship gate is unaffected — we still parse the four files end-to-end, just without OpenMW asserting alongside. |
| The four sample files don't exhaust BC's block-type variety, so v1 is "complete" but a fifth sample file later reveals an unhandled block. | high | low | Expected and accepted. Adding a fifth sample file is a deliberate scope-extension action: re-run `tools/list_nif_blocks.py`, diff the manifest, design and implement any new blocks. Not an emergency, not a regression. |
| OQ-3.3 character body+head merge logic turns out to need parser-level support, pulling skeleton-merge complexity into v1. | low | medium | Treat as a v1 expansion if it materializes. Most likely the merge happens at scene-graph assembly (engine layer), not at parse time, so the parser exposes both files' skeleton trees and the engine merges. Confirm by inspection during implementation step 4. |
| Canonical-text format design churn slows implementation. | medium | low | Keep the format minimal at first (one field per line, trivial type-printers). Make it pretty only if/when test failures become hard to read. |

---

## Open questions resolved during implementation

These questions are deliberately not answered in the design — they are
empirical and resolve as a side effect of implementation step 0 or 1:

- **OQ-3.1** (BC NIF version compatibility with OpenMW) — answered when the
  inventory tool first reads a BC NIF header.
- **BC user_version value** — same.
- **Whether OpenMW's parser compiles standalone** — answered when
  `openmw_nif_oracle` first compiles or fails. Mitigation in the risks
  table.

The following remain open for follow-up sub-projects, **not** this one:

- **OQ-3.2** (damage-related node naming conventions) — Phase 2 renderer
  concern, not parser concern.
- **OQ-3.3** (character body/head NIF assembly) — engine-layer concern;
  parser exposes both files' skeleton trees, merge logic lives elsewhere.

---

## Out of scope (reiterated)

- Rendering / GPU / window
- Scene-graph runtime
- Texture-pixel loading
- NIF writing
- Python bindings
- CLI tool
- NIF coverage beyond block types in the four sample files
- Morrowind-only blocks not in BC

Each of these has its own future sub-project with its own design and plan.
