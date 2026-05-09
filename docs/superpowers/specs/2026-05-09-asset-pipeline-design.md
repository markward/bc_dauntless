# Asset Pipeline — Design Spec

**Date:** 2026-05-09
**Status:** Approved (pending implementation)
**Phase:** 2 (Full C++ engine), second sub-project

## Goal

Build a C++20 `assets` library that turns a parsed `nif::File` plus referenced
TGA files on disk into renderer-ready domain objects (`Texture`, `Mesh`,
`Material`, `Skeleton`, `AnimationClip`) bundled into a `Model`, owns their GL
handles, and serves them from a refcounted, NIF-path-keyed cache.

This is the foundation the future render pipeline (item 4 of the renderer
breakdown) draws against. It depends on the completed NIF loader (item 1) and
sits between the loader and the future scene-graph runtime / render pipeline.

## Non-goals

- No window or GL-context creation (the future render-pipeline owns that)
- No draw submission, shaders, or render passes
- No animation *playback* (we produce resampled clip data; evaluation lives
  in the scene-graph runtime sub-project)
- No LOD-chain population in v1 (the field is reserved on `Mesh`; no code
  path fills it)
- No NIF writing
- No glow / specular suffix conventions (item 6 of the renderer plan)
- No mod or asset-overlay support
- No Python bindings
- No async loading; v1 is synchronous and single-threaded

## Success criteria (v1 ship gate)

1. Given a current GL 3.3 core context on the calling thread:
   ```cpp
   assets::AssetCache cache;
   auto model = cache.load(
       "game/data/Models/Ships/Galaxy/Galaxy.nif",
       "data/Models/SharedTextures/FedShips/High");
   ```
   returns a populated `ModelHandle` without throwing.

2. The returned `Model` exposes:
   - One or more `Mesh` objects with valid `GLuint` VAO/VBO/EBO
   - All referenced textures decoded and uploaded as `Texture` objects with
     valid `GLuint` IDs
   - For each `NiTriShape`, a resolved `Material` carrying its BC property
     values verbatim
   - A `Skeleton` (possibly empty for the Galaxy, populated for
     `BodyKlingon.nif`)
   - Zero or more `AnimationClip` objects with resampled key tracks

3. Calling `cache.load(...)` again with the same `nif_path` returns the
   *same* `ModelHandle` (deduplication works). When the last handle drops AND
   the cache evicts the entry, the GL handles are deleted on the GL thread.

4. `ctest` passes on macOS + Linux. CPU-side tests run with no GL context.
   GL-side tests run under a hidden offscreen GLFW context and skip cleanly
   if context creation fails.

5. Sample assets covered: the four NIFs from the loader's ship gate
   (`Galaxy.nif`, `CardStarbase.nif`, `BodyKlingon.nif`, `EBridge.nif`) plus
   their referenced textures.

---

## Architecture

### Where it lives

New top-level subtree `native/src/assets/`, parallel to `native/src/nif/`. The
renderer will live at `native/src/renderer/` (currently empty) when item 4
starts.

### Dependency graph

```
nif         ← already exists; assets links it
stb_image   ← public-domain single-header at native/third_party/stb/, used by assets only
GLAD 1.x    ← GL function loader (vendored generated source)
GLFW        ← test-only, for the offscreen-context fixture in assets_tests
GTest       ← test-only
glm         ← header-only math (mat4 / quat operators for skeleton & animation)
```

GLAD, GLFW, glm, and stb_image are new third-party deps. Each gets vendored
under `native/third_party/` with its `LICENSE` file and a
`THIRD_PARTY_NOTICES.md` entry, mirroring the OpenMW NIF mirror pattern. All
four are permissively licensed (GLAD generated MIT, GLFW zlib, glm MIT, stb
public-domain) and GPLv3-compatible.

### CMake targets

| Target | Type | Purpose |
|---|---|---|
| `assets` | static library | Public lib. Depends on `nif`, `stb_image`, `glad`, `glm`. |
| `glad` | static library | GL function loader. Vendored generated source. |
| `stb_image` | INTERFACE library | Header-only wrapper. |
| `glm` | INTERFACE library | Header-only wrapper. |
| `assets_tests` | GTest executable | All assets tests. Depends on `assets`, `gtest`, `glfw` (offscreen context for GPU tests). |

`nif` and `assets` remain the only libraries that production code outside
`native/` is expected to link.

### Directory layout

```
native/
  src/
    assets/
      CMakeLists.txt
      include/assets/
        asset.h              # forward decls, AssetHandle / ModelHandle, public typedefs
        texture.h            # Texture (GL handle + metadata) and Image (CPU pixels)
        mesh.h               # Mesh (GL VAO/VBO/EBO + CPU MeshCpu) and MeshCpu
        material.h           # Material (BC-faithful, holds NiTexturingProperty etc.)
        skeleton.h           # Skeleton, Bone
        animation.h          # AnimationClip, key-track types
        model.h              # Model (flat-arrays scene graph)
        cache.h              # AssetCache, AssetCache::Config, exceptions
      src/
        cache.cc             # NIF-path-keyed cache, refcount + eviction
        path_resolver.cc     # texture-search-path → resolved file path (case-insensitive)
        texture_decode.cc    # TGA decode (stb_image), NiRawImageData decode → Image
        texture_upload.cc    # Image → Texture (only this file calls glTex*)
        mesh_build.cc        # NiTriShape + NiTriShapeData → MeshCpu
        mesh_upload.cc       # MeshCpu → Mesh (only this file calls glBuffer*/glVertex*)
        material_build.cc    # NiTexturingProperty/Alpha/ZBuf/VC/Material chain → Material
        skeleton_build.cc    # NiNode/NiBone walk + NiTriShapeSkinController → Skeleton
        animation_build.cc   # NiKeyframeController + NiKeyframeData → AnimationClip
        model_build.cc       # Orchestrator: nif::File → Model
        gl_handle.h          # RAII wrappers: TextureHandle, BufferHandle, VertexArrayHandle
      docs/
        material_translation.md   # Per-property notes; how to interpret BC enum values
        deferred_work.md          # Mirror of this spec's "Deferred / future work" section
  third_party/
    stb/
      stb_image.h            # single-header, public domain
      LICENSE                # stb's public-domain or MIT notice
    glad/
      include/glad/glad.h
      include/KHR/khrplatform.h
      src/glad.c
      LICENSE                # generated MIT
    glm/
      LICENSE                # MIT
    glfw/                    # test-only
      LICENSE                # zlib/libpng
  tests/
    assets/
      CMakeLists.txt
      cpu/                   # tests with no GL context
        path_resolver_test.cc
        texture_decode_test.cc
        material_build_test.cc
        mesh_build_test.cc
        skeleton_build_test.cc
        animation_build_test.cc
        cache_test.cc
      gpu/                   # tests requiring offscreen GL context
        gl_fixture.h
        texture_upload_test.cc
        mesh_upload_test.cc
        model_smoke_test.cc
THIRD_PARTY_NOTICES.md       # add stb, GLAD, GLFW, glm entries
```

### Boundary discipline

- `assets/include/assets/*.h` is the public surface. No transitive include of
  `nif/*` headers in *signatures* — public types own their own data.
  `nif::File` is held privately during `load`; the file is dropped before the
  `ModelHandle` is returned.
- Only `texture_upload.cc`, `mesh_upload.cc`, `gl_handle.h`, the GPU tests,
  and the public headers `texture.h` / `mesh.h` (for `GLuint` in handle
  accessors) include GLAD. Every other implementation file is GL-free, so
  CPU tests never need a context. Public headers including GL types is
  intentional — the pipeline is GPU-aware by design; consumers of the public
  API are expected to have a GL context current.
- `MeshCpu` and `Image` are public types (renderer or tooling can inspect raw
  data); `Texture` and `Mesh` carry the GL handle in addition. Loading
  produces both — the CPU-side type drops when the GPU-side type is built,
  unless `AssetCache::Config::keep_cpu_data` is set (default off; useful for
  testing or for a future "rebuild GL after context loss" path).
- **CPU/GPU split is enforced by file**, not by namespace. The only files
  that include GLAD are the four named above. Reviewable, mechanical.

---

## Public API

Sketches below pin down shape, not literal final code. Final names refined
during implementation.

### Math types

Use `glm::vec3 / vec4 / quat / mat4` in public signatures. Conversion from
`nif::Vec3 / Quat / Mat3x3` happens during build, not at the API boundary.
`nif::` types never appear in public assets headers.

### `assets/texture.h`

```cpp
namespace assets {

struct Image {                              // CPU pixels
    uint32_t width = 0, height = 0;
    enum class Format { RGBA8, RGB8, R8 };
    Format format = Format::RGBA8;
    std::vector<uint8_t> pixels;            // tightly packed; size = w*h*bytes_per_pixel
};

class Texture {                             // owns its GLuint
public:
    Texture() = default;
    Texture(Texture&&) noexcept;
    Texture& operator=(Texture&&) noexcept;
    Texture(const Texture&) = delete;
    ~Texture();                             // glDeleteTextures if non-zero
    GLuint id() const { return id_; }
    uint32_t width() const { return width_; }
    uint32_t height() const { return height_; }
    bool has_mipmaps() const { return mipmaps_; }
private:
    GLuint id_ = 0;
    uint32_t width_ = 0, height_ = 0;
    bool mipmaps_ = false;
};

// Public utilities also usable by the renderer for its own internal assets
// (lens-dirt textures, color-grading LUTs, etc.):
Image decode_tga(std::span<const uint8_t> bytes);
Texture upload_image(const Image&, bool generate_mipmaps = true);
}
```

### `assets/mesh.h`

Fixed vertex layout for v1 — interleaved 44-byte vertex carrying
pos/normal/primary-uv/color/bone-indices/bone-weights. Always present,
white-default for color, zero-default for skin weights. Trades a few bytes
per vertex for one VAO format the renderer hardcodes.

```cpp
namespace assets {

struct MeshCpu {
    struct Vertex {
        glm::vec3 position;                 // 12B
        glm::vec3 normal;                   // 12B
        glm::vec2 uv;                       // 8B  — primary UV
        glm::u8vec4 color = {255,255,255,255};  // 4B  — RGBA, white default
        glm::u8vec4 bone_indices = {0,0,0,0};   // 4B
        glm::u8vec4 bone_weights = {0,0,0,0};   // 4B  — sums to 255 if skinned
    };                                                  // 44B (will pad/align)

    std::vector<Vertex> vertices;
    std::vector<uint32_t> indices;          // 32-bit unconditionally in v1
    std::vector<std::vector<glm::vec2>> extra_uvs;  // empty for single-UV meshes
    int material_index = -1;                // into Model::materials
    int node_index = -1;                    // into Model::nodes
};

class Mesh {
public:
    Mesh() = default;
    Mesh(Mesh&&) noexcept;
    Mesh& operator=(Mesh&&) noexcept;
    ~Mesh();                                // glDelete{VertexArrays,Buffers}
    GLuint vao() const { return vao_; }
    uint32_t index_count() const { return index_count_; }
    int material_index() const { return material_index_; }
    int node_index() const { return node_index_; }
    const std::optional<MeshCpu>& cpu_data() const { return cpu_data_; }
    const std::vector<Mesh>& lod_chain() const { return lod_chain_; }  // empty in v1
private:
    GLuint vao_ = 0, vbo_ = 0, ebo_ = 0;
    uint32_t index_count_ = 0;
    int material_index_ = -1, node_index_ = -1;
    std::optional<MeshCpu> cpu_data_;
    std::vector<Mesh> lod_chain_;           // reserved for future LOD chains
};
}
```

### `assets/material.h`

Carries BC's property values verbatim. The renderer interprets them when it
sets GL state and binds shaders.

```cpp
namespace assets {

struct Material {
    // From NiMaterialProperty
    glm::vec3 ambient = {1,1,1};
    glm::vec3 diffuse = {1,1,1};
    glm::vec3 specular = {0,0,0};
    glm::vec3 emissive = {0,0,0};
    float glossiness = 0.0f;
    float alpha = 1.0f;

    // From NiTexturingProperty (and NiMultiTextureProperty merged in by
    // empirical mapping — NiMultiTextureProperty has 5 stages whose slot
    // assignment is determined during material_build.cc implementation by
    // sampling real BC NIFs and observing which stages drive which visual
    // effects; the mapping is then documented in material_translation.md)
    enum class StageSlot {
        Base = 0, Dark, Detail, Gloss, Glow, Bump, Decal0, Decal1, Decal2
    };
    struct TextureStage {
        int texture_index = -1;             // -1 = unused; otherwise → Model::textures
        uint32_t clamp_mode = 0;            // BC enum verbatim
        uint32_t filter_mode = 0;
        uint32_t uv_set = 0;
        uint32_t apply_mode = 0;            // BC's tex-blend op (modulate / decal / replace / additive)
    };
    std::array<TextureStage, 9> stages{};

    // From NiAlphaProperty (verbatim)
    bool blend_enabled = false;
    uint32_t blend_src_factor = 0, blend_dst_factor = 0;   // D3DBLEND_* enum values
    bool alpha_test_enabled = false;
    uint32_t alpha_test_func = 0;
    uint8_t alpha_test_threshold = 0;
    bool zwrite_when_blended = false;

    // From NiZBufferProperty
    bool depth_test_enabled = true;
    bool depth_write_enabled = true;
    uint32_t depth_func = 0;

    // From NiVertexColorProperty
    uint32_t vc_lighting_mode = 0;
    uint32_t vc_source = 0;
};
}
```

`material_translation.md` (alongside the source) documents which D3DBLEND_*
enum values BC writes and how to map them to GL when the renderer interprets
them.

### `assets/skeleton.h`

Skinning weights live directly on `MeshCpu::Vertex` (already in the layout
above) — at build time we resolve each `NiTriShapeSkinController`'s
per-vertex bone references against the `Skeleton`'s flat bone array and stuff
global indices straight into vertices. No separate `SkinBinding` type.

```cpp
namespace assets {

struct Bone {
    std::string name;
    int parent_index = -1;                   // -1 = root
    glm::mat4 local_transform = glm::mat4(1.0f);
    glm::mat4 inverse_bind_pose = glm::mat4(1.0f);
};

struct Skeleton {
    std::vector<Bone> bones;                 // flat; tree via parent_index
    int root_bone_index = -1;                // -1 = no skeleton (most ships)
};
}
```

### `assets/animation.h`

Resampled key tracks, named-keyed against node names. Runtime binds clip
to instance by walking `target_node_name` through `Model::nodes`.

```cpp
namespace assets {

struct AnimationClip {
    std::string name;
    float duration_seconds = 0.0f;

    struct TranslationKey { float time; glm::vec3 value; };
    struct RotationKey    { float time; glm::quat value; };
    struct ScaleKey       { float time; float value;     };
    struct VisibilityKey  { float time; bool  value;     };
    struct FloatKey       { float time; float value;     };

    struct NodeTrack {
        std::string target_node_name;
        std::vector<TranslationKey> translation;
        std::vector<RotationKey>    rotation;
        std::vector<ScaleKey>       scale;
        std::vector<VisibilityKey>  visibility;
        std::vector<FloatKey>       floats;     // e.g. material-alpha animation
    };
    std::vector<NodeTrack> tracks;
};
}
```

### `assets/model.h`

Flat-arrays scene graph (GLTF-style). Tree via `parent_index`. Resources in
arrays, references via integer indices. Const from the renderer's POV — built
once, immutable thereafter; per-frame state (animation playback, world
matrices) lives in a future *instance* type owned by the scene-graph-runtime
sub-project.

```cpp
namespace assets {

struct Node {
    std::string name;
    int parent_index = -1;
    glm::mat4 local_transform = glm::mat4(1.0f);
    std::vector<int> children;               // child node indices
    std::vector<int> meshes;                 // mesh indices attached to this node
};

struct Model {
    std::vector<Node>          nodes;
    int                        root_node = 0;
    std::vector<Mesh>          meshes;
    std::vector<Texture>       textures;     // deduped within this Model by basename
    std::vector<Material>      materials;
    Skeleton                   skeleton;
    std::vector<AnimationClip> animations;
    std::filesystem::path      source;       // diagnostic
};

using ModelHandle = std::shared_ptr<const Model>;
}
```

### `assets/cache.h`

```cpp
namespace assets {

class AssetCache {
public:
    struct Config {
        bool keep_cpu_data = false;          // retain MeshCpu/Image after upload

        // Test-only injection points. Defaulted std::functions are empty;
        // the cache substitutes the real GL uploaders (`upload_image` and
        // the equivalent for meshes) when the field is empty. Production
        // callers leave both fields default. CPU tests inject stubs that
        // return deterministic GL-id-like integers without calling GL,
        // letting cache_test.cc run in environments with no GL context.
        std::function<Texture(const Image&, bool)> texture_uploader;
        std::function<Mesh(MeshCpu, int /*material*/, int /*node*/)> mesh_uploader;
    };
    explicit AssetCache(Config = {});
    ~AssetCache();
    AssetCache(const AssetCache&) = delete;
    AssetCache& operator=(const AssetCache&) = delete;

    /// Synchronous load; requires a current GL 3.3 core context.
    /// Identical (nif_path, texture_search_path) inputs return the same handle.
    /// Different texture_search_path with the same nif_path: throws.
    ModelHandle load(const std::filesystem::path& nif_path,
                     const std::filesystem::path& texture_search_path);

    void evict(const std::filesystem::path& nif_path);
    void evict_unused();

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};

class AssetError : public std::runtime_error {
public:
    std::filesystem::path path;
};
class TextureNotFound      : public AssetError { /* basename + searched dir */ };
class TextureDecodeError   : public AssetError { /* what stb said */ };
class UnsupportedTga       : public AssetError { /* indexed/16bpp/etc. */ };
class ModelBuildError      : public AssetError { /* "no NiTriShape under root" etc. */ };
// nif::ParseError propagates unchanged from the loader.
}
```

---

## Data flow

`AssetCache::load(nif_path, texture_search_path)`:

1. **Canonicalize path.** Look up in `entries_`; if `weak_ptr` resolves and
   stored search path matches, return the handle. If `weak_ptr` resolves but
   search path differs, throw.
2. **Parse NIF.** Call `nif::load(nif_path)`. Failures propagate as
   `nif::ParseError`.
3. **Build Skeleton.** Walk root `NiNode` tree; collect `NiNode` and `NiBone`
   instances; produce flat `Skeleton::bones` with `parent_index`,
   `local_transform`, `inverse_bind_pose`.
4. **Resolve and decode textures.** Walk all `NiImage` blocks. For each:
   - `use_external != 0`: call `path_resolver.resolve(file_name,
     texture_search_path)`; load TGA bytes; `decode_tga()` → `Image`.
   - `use_external == 0`: read pixels from the linked `NiRawImageData` block
     directly.
   - Texture entries deduped within this Model by basename — same basename
     referenced twice produces one `Texture`.
5. **Upload textures.** `upload_image()` per `Image` → `Texture`. Mipmaps
   generated for textures larger than 4×4.
6. **Build materials.** For each `NiTriShape`, walk its property chain;
   translate `NiMaterialProperty / NiTexturingProperty / NiAlphaProperty /
   NiZBufferProperty / NiVertexColorProperty / NiMultiTextureProperty /
   NiTextureModeProperty` field-by-field into `Material`. Texture-stage slot
   indices reference the `Model::textures` array.
7. **Build CPU meshes.** For each `NiTriShape`, read its `NiTriShapeData`;
   produce `MeshCpu` with the fixed vertex layout. Skin-weight bone
   references resolved against the Skeleton's flat array.
8. **Upload meshes.** Each `MeshCpu` → `Mesh` via `mesh_upload.cc`.
9. **Build animations.** For each `NiKeyframeController` chain: produce
   `AnimationClip` with one `NodeTrack` per controller (target node name
   from controller's target field). `NiVisData` and `NiFloatData` produce
   `visibility` and `floats` tracks respectively.
10. **Assemble Model.** Flatten the `NiNode` tree into `Model::nodes` with
    `parent_index`, `children`, `meshes`. Set `root_node = 0`.
11. **Wrap in `shared_ptr<const Model>`,** store both `weak_ptr` and
    `shared_ptr` in `entries_`, return.

Any exception during steps 2–10 unwinds RAII handles. No partial entry is
committed.

---

## Path resolution

NIF blocks reference textures by **bare basename** (e.g., `Ent-D_wing.tga`).
Resolution proceeds:

1. **Resolve `texture_search_path`.** Accepted as either relative or
   absolute. Relative paths are resolved against the process working
   directory via `std::filesystem::weakly_canonical`. There is no
   asset-pipeline-side concept of a "data root" — the caller supplies the
   path it wants searched. (BC's Python ship scripts use
   `"data/Models/SharedTextures/..."` relative to the BC install dir, which
   is also the PWD when the engine runs.)
2. Compose `resolved_search_path / basename`.
3. **Case-insensitive lookup.** macOS APFS is case-insensitive by default;
   the lookup just works. On Linux we walk the directory once, build a
   lowercase→actual-name map cached on `AssetCache::Impl` for the lifetime
   of the cache, and look the lowercased basename up there.
4. **Auto-`.tga`-append.** If the basename's last path component contains
   no `.` at all, append `.tga`. Names that already end in `.tga`, `.TGA`,
   or any other extension are passed through verbatim. (This handles BC
   NIFs that omit the extension; it does *not* try alternative extensions
   for already-extensioned names.)
5. If still not found, throw `TextureNotFound` with basename and searched
   dir. **Failing loud** — we'd rather see "missing texture" early than ship
   a model with one stage replaced by a default-pink placeholder.
6. Resolution is *not* recursive. The texture share path is a single
   directory, not a tree — matches BC's `SetTextureSharePath` semantics.

`NiImage` blocks where `use_external == 0` (inline `NiRawImageData`) skip
resolution entirely; pixels come from the linked block.

On `TextureNotFound`, the lowercase map for the searched dir is rebuilt
once and the lookup retried before throwing — handles the case where mods
drop new TGAs at runtime.

---

## Cache mechanics

The cache holds two data structures keyed by canonicalized absolute path:

```cpp
struct Entry {
    std::weak_ptr<const Model> live;       // what handed-out handles point at
    std::shared_ptr<const Model> pinned;   // strong ref keeps it alive past last handle
    std::filesystem::path search_path;     // for same-path-different-search-path detection
};
std::unordered_map<std::string, Entry> entries_;
```

`load()`:
1. Canonicalize path. If `entries_[key].live.lock()` returns a model and
   `search_path` matches, return it.
2. If `entries_[key].live.lock()` returns a model but `search_path`
   differs, throw.
3. Otherwise build the model, wrap in `shared_ptr<const Model>`, store both
   `weak_ptr` and `shared_ptr` in `entries_[key]`, return.

`evict(path)`: drops `pinned` only. Outstanding handles keep the model
alive until they themselves drop.

`evict_unused()`: walks `entries_`; for each entry where
`pinned.use_count() == 1` (only the cache holds it), drops `pinned`.

---

## GL handle lifetime ordering

`Texture` and `Mesh` call `glDelete*` in their destructors. That call
requires a current GL context on the destroying thread. Two failure modes:

1. **Process shutdown.** If `AssetCache` is destroyed *after* the GL context
   is destroyed, all `glDelete*` calls hit a non-current/destroyed context.
   On most drivers silently ignored; on some, crash. Mitigation: the
   `AssetCache` destructor calls `entries_.clear()` first, and we document
   that the renderer must drop the cache *before* destroying the context.
2. **Cross-thread destruction.** A `ModelHandle` held on another thread,
   dropped there, runs `~Texture` / `~Mesh` on the wrong thread. Mitigation
   for v1: declare cache and handles single-threaded; nothing else holds
   them. Documented on `AssetCache`. No deferred-deletion queue in v1.

---

## Error handling

| Error | Type | Behavior |
|---|---|---|
| `nif::ParseError` (any flavor) | propagated | partial state in cache *not* committed |
| Texture file missing | `TextureNotFound` | fatal; no entry committed |
| TGA decode fails | `TextureDecodeError` | fatal; no entry committed |
| Unsupported TGA variant (indexed, 16bpp) | `UnsupportedTga` | fatal |
| GL upload fails (`glGetError != GL_NO_ERROR`) | `AssetError` with last GL error | fatal; partially-built GL handles released by destructors during unwind |
| Model has no NiTriShape | `ModelBuildError` | fatal; possibly a non-renderable NIF |
| Same-path different-search-path | `AssetError` | fatal |

The "no entry committed on failure" invariant is enforced by building the
entire `Model` in a local before storing it in `entries_`. RAII handles GL
cleanup if any step throws mid-build.

---

## Threading

Single-threaded. Documented on `AssetCache`. No internal locking. A second
thread calling `load()` is undefined behavior.

---

## Test plan

Five test groups, split by whether they need a GL context. CPU-only tests
are mandatory pass on every supported platform; GL tests `GTEST_SKIP()` if a
context can't be created.

### CPU-only tests

All synthetic — they construct `nif::File` objects in memory (or use small
hand-crafted TGA byte arrays) and assert on the resulting domain types.
Hermetic, deterministic, fast.

| File | Tests |
|---|---|
| `cpu/path_resolver_test.cc` | Case-insensitive basename → actual-path lookup against a synthetic temp dir; auto-append `.tga`; throws `TextureNotFound` with searched dir on miss; rebuild-and-retry after stale-cache miss. |
| `cpu/texture_decode_test.cc` | TGA decode of 24-bit / 32-bit / RLE / non-RLE hand-crafted byte arrays; `NiRawImageData` → `Image`; `UnsupportedTga` for indexed and 16bpp inputs. |
| `cpu/material_build_test.cc` | Synthetic property chains → expected `Material` field values: `NiAlphaProperty` enums verbatim, `NiZBufferProperty` sets depth state, `NiVertexColorProperty` modes preserved, `NiTexturingProperty` populates correct `StageSlot`s, `NiMultiTextureProperty` merges into the same slot table. |
| `cpu/mesh_build_test.cc` | Synthetic `NiTriShape` + `NiTriShapeData` → `MeshCpu`: vertex/index counts, white-default color, zero-default skin weights, primary UV in `Vertex::uv`, additional UVs in `extra_uvs`. |
| `cpu/skeleton_build_test.cc` | Synthetic `NiNode` tree containing `NiBone`s → `Skeleton`: bones flattened, `parent_index` reflects tree, root identified, inverse-bind-pose computed. |
| `cpu/animation_build_test.cc` | Synthetic `NiKeyframeController` + `NiKeyframeData` (translation/rotation/scale tracks), `NiVisData`, `NiFloatData` → `AnimationClip`: track count per node, key counts, duration = max key time, `target_node_name` resolved. |
| `cpu/cache_test.cc` | Lifetime semantics with **stub uploaders** (`Config::texture_uploader` / `mesh_uploader` injected). Verifies: `load(p)` twice returns same handle; `evict(p)` drops pinned but live handle keeps Model alive; `evict_unused()` respects refcount; `load(p, search_a)` then `load(p, search_b)` throws. |

The stub-uploader hook is `std::function` injection on `Config`, defaulting
to the real GL uploader. CPU tests don't link GL.

### GPU tests

| File | Tests |
|---|---|
| `gpu/gl_fixture.h` | GLFW hidden-window context creation; `GTEST_SKIP()` with clear message if context unavailable. |
| `gpu/texture_upload_test.cc` | `Image` → `Texture`: `glIsTexture(id)` true, dimensions match, mipmap chain when requested, format selection. |
| `gpu/mesh_upload_test.cc` | `MeshCpu` → `Mesh`: VAO/VBO/EBO valid, `glGetVertexAttrib*` confirms all 6 vertex attributes' offsets/strides/types. |
| `gpu/model_smoke_test.cc` | End-to-end: `cache.load("game/data/Models/Ships/Galaxy/Galaxy.nif", "data/Models/SharedTextures/FedShips/High")` → populated `Model`. `GTEST_SKIP()` if `game/` absent. |

### Sample-file expectations

| Sample | Expected highlights |
|---|---|
| `Galaxy.nif` + `FedShips/High` | non-zero meshes; multiple textures decoded; no skeleton; no animations |
| `CardStarbase.nif` + `CardBases` | many meshes; large material count |
| `BodyKlingon.nif` + (TBD search dir) | non-empty `Skeleton`; meshes carry non-zero `bone_weights` |
| `EBridge.nif` + (interior textures dir, TBD) | hundreds of meshes; lots of materials |

`(TBD search dir)` discovered during the path-resolver task by grepping the
corresponding ship Python scripts for `SetTextureSharePath` and baking the
values into the test.

### Out of test scope (v1)

- **Visual correctness** — no pixel comparison; renderer's domain.
- **Performance** — observe load time; no test gate.
- **Concurrent access** — single-threaded by spec; testing concurrency
  would test undefined behavior.

### Running

```bash
cmake -S . -B build
cmake --build build -j
ctest --test-dir build --output-on-failure
```

CPU tests run unconditionally. GPU tests run when GLFW gets a context. Tests
requiring `game/` skip cleanly when absent.

---

## Risks (likelihood × impact)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| GL handle destroyed after context (shutdown ordering bug) | medium | medium | `~AssetCache` asserts current GL context; document the rule; renderer drops cache before window. |
| Texture share path is actually a search-list, not a single dir | medium | low | Empirically driven — if a real BC NIF references a texture not in the per-class share dir, expand the resolver to walk a list. The change is local to `path_resolver.cc`. |
| TGA variants used by BC content beyond stb's coverage (16bpp, indexed) | low | low | `UnsupportedTga` thrown loudly. Most BC TGAs sampled appear to be 24/32-bit. |
| Property blocks present in BC NIFs that we haven't accounted for in `material_build.cc` | medium | low | `ModelBuildError` with the unhandled block-type name. Add the field to `Material` and re-run. The NIF loader already parses these blocks; we're only translating fields. |
| Cold-load latency (Galaxy.nif: ~70 blocks + ~30 textures × 1024² uploads) | medium | low | Sync v1 accepts this; mission-level preload keeps the in-flight loop smooth. Async retrofits behind the same API. |
| Vendoring four new third-parties (stb, GLAD, GLFW, glm) introduces build friction | low | medium | Each vendored in a separate implementation commit with its own CMake target; tests run per commit. Pin specific versions in `UPSTREAM_VERSION` files mirroring the OpenMW pattern. |
| Stale case-insensitive lowercase-map after a directory mtime change mid-session | low | low | On `TextureNotFound`, rebuild the lowercase map for the searched dir once before throwing. |

---

## Deferred / future work

This list is the durable record of what we punted from v1 and *why*. A copy
also lives at `native/src/assets/docs/deferred_work.md` next to the code for
future-contributor visibility. Anything added/removed here should be mirrored
there during implementation.

1. **LOD chain population.** `Mesh::lod_chain` field reserved; nothing
   populates it in v1. Future: meshoptimizer-driven decimation chain on the
   high mesh, indexed by screen-space size at draw time. Renderer's draw
   code is the only consumer that needs to know.
2. **Async loading.** Synchronous v1 by design. Future: state-machine handle
   (`Loading` → `Ready`) with a worker thread for parse + decode and the
   main thread retaining GL upload responsibility.
3. **Glow / specular suffix conventions** *(item 6 of the renderer
   breakdown)*. v1 doesn't auto-search for `_glow.tga` / `_specular.tga`
   siblings; only what NIF blocks reference is loaded. When item 6 lands,
   the convention extends `Material`'s stages or drives shader uniforms in
   the renderer.
4. **Med / Low LOD NIFs.** Pipeline knows nothing about LOD bundling. App.py
   shim absorbs `AddLOD` calls past the first.
5. **Material normalization layer (Approach C).** v1 is BC-faithful. When
   the renderer is fleshed out and shows what shape it wants, wrap
   `Material` in a renderer-friendly facade — the data is all there.
6. **Mod / asset-overlay support.** v1's texture search is a single
   directory. Future: search-path *list*, or a virtual filesystem layer.
7. **CI pipeline without BC install.** Same problem as the NIF loader.
   Either self-hosted runner with BC, or commit anonymized minimal
   fixtures.
8. **GL context-loss recovery.** `keep_cpu_data` retains CPU buffers after
   upload. Future: a `rebuild_gl()` walk that re-uploads everything if the
   context is lost (e.g., on driver reset).
9. **PNG / DDS / BC1-7 compressed textures.** TGA only for v1. stb_image
   already handles PNG/JPEG/BMP gratis if mods need them. DXT/BC compressed
   needs a separate decoder (or `glCompressedTexImage2D` pass-through).
10. **Vertex tangent slot.** 44-byte vertex has no tangent. Future: 56-byte
    vertex with `glm::vec3 tangent`, computed via mikkTSpace at build or
    in-shader from screen-space derivatives. Required for normal mapping.
11. **HDR texture format (`RGBA16F`).** `Image::Format` enum is LDR-only.
    Future: add `RGBA16F` for HDR cubemaps / IBL probes. One-line change.
12. **Phase 1 Python bindings.** No pybind11 in v1. Future: thin pybind11
    layer if Phase 1's headless logic ever needs to introspect mesh/skeleton
    data.
13. **Continuous LOD via cluster / mesh shaders.** Nanite-style. Off-table
    given GL 3.3; revisit if backend ever switches to Vulkan/Metal with
    mesh-shader support.
14. **Skinned animation playback.** `AnimationClip` is *static data* in v1.
    Playback (sampling tracks, combining with bone hierarchy, generating
    final per-vertex transforms) lives in the scene-graph runtime
    sub-project (item 3).
15. **Particle effects (`Effects/`).** `gap_analysis.md` notes BC particles
    are runtime-procedural, not NIF-backed. Out of scope for the asset
    pipeline entirely.
16. **`NiBinaryVoxelData` / `NiBinaryVoxelExtraData` semantics.** Parsed by
    the NIF loader; v1 ignores them. Almost certainly damage decals or
    volumetric occlusion data; defer to whichever sub-project (scene-graph
    runtime or physics) actually uses them.
17. **Save/load.** Phase 1 concern. Pipeline rebuilds `Model` from disk on
    load; no serialization of GPU-side handles.
18. **Streaming / virtual textures.** BC's whole texture set fits in VRAM;
    not needed today. If mods push asset count beyond VRAM, revisit.

The renderer's own internal-asset needs (lens-dirt textures for bloom,
color-grading LUTs, vignette masks) reuse the public `decode_tga()` and
`upload_image()` utilities exposed in `assets/texture.h` — not deferred,
just noted as a usage pattern.

---

## Out of scope (v1, reiterated)

- Window / GL context creation
- Shaders, draw submission, render passes
- Animation playback / scene-graph runtime
- Hardpoint / damage-node interpretation (item 6 of renderer plan)
- LOD bundling
- Glow / specular suffix conventions
- Mod / asset-overlay support
- Async loading
- Save/load of asset state
- Python bindings

Each is a deliberate future sub-project with its own design.
