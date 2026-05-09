# Asset Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a C++20 `assets` library that turns parsed `nif::File` plus referenced TGA files into renderer-ready `Model` (containing `Texture`/`Mesh`/`Material`/`Skeleton`/`AnimationClip`), owns GL handles, and serves them from a refcounted, NIF-path-keyed cache.

**Architecture:** GPU-aware, single-threaded synchronous loading. OpenGL 3.3 core; GL handles owned by the pipeline. BC-faithful Material (Approach A — verbatim property values). CPU/GPU split by file (`*_upload.cc` is the only code that calls GL), enabling tests to run without a context. See [`docs/superpowers/specs/2026-05-09-asset-pipeline-design.md`](../specs/2026-05-09-asset-pipeline-design.md) for the full design.

**Tech Stack:** C++20, CMake, GoogleTest, OpenGL 3.3 core, GLAD (vendored, GL function loader), GLFW (vendored, test-only offscreen context), glm (vendored, math), stb_image (vendored, TGA decode).

---

## Pre-flight check

Verify the repo state expected by this plan:

```bash
ls native/src/nif/include/nif/block.h     # NIF loader exists
ls native/src/assets/ 2>/dev/null         # should NOT exist yet
ls native/third_party/stb/ 2>/dev/null    # should NOT exist yet
git status                                # should be clean
```

---

### Task 1: Vendor stb_image (TGA + future PNG decoder)

**Files:**
- Create: `native/third_party/stb/stb_image.h`
- Create: `native/third_party/stb/LICENSE`
- Create: `native/third_party/stb/UPSTREAM_VERSION`
- Create: `native/third_party/stb/CMakeLists.txt`
- Modify: `native/CMakeLists.txt`
- Modify: `THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: Download stb_image.h pinned to a stable release**

```bash
mkdir -p native/third_party/stb
# Pin to v2.30 (last known stable as of 2026-05); update only deliberately
curl -L -o native/third_party/stb/stb_image.h \
  https://raw.githubusercontent.com/nothings/stb/f0569113c93ad095470c54bf34a17b36646bbbb5/stb_image.h
echo 'f0569113c93ad095470c54bf34a17b36646bbbb5' > native/third_party/stb/UPSTREAM_VERSION
```

- [ ] **Step 2: Copy stb's LICENSE text**

`stb_image.h` ships dual-licensed at the bottom of the file (public domain OR MIT). Extract the MIT block to `native/third_party/stb/LICENSE`:

```bash
# The license is in the last ~30 lines of stb_image.h. Extract manually:
cat > native/third_party/stb/LICENSE <<'EOF'
stb_image - v2.30 - public domain image loader

This software is dual-licensed under the public domain and MIT.

ALTERNATIVE B - MIT License
Copyright (c) 2017 Sean Barrett
Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies
of the Software, and to permit persons to whom the Software is furnished to do
so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
EOF
```

- [ ] **Step 3: Create the INTERFACE CMake target**

```cmake
# native/third_party/stb/CMakeLists.txt
add_library(stb_image INTERFACE)
target_include_directories(stb_image INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})
```

- [ ] **Step 4: Wire into top-level CMake**

Add to `native/CMakeLists.txt` (after the existing `add_subdirectory(src/nif)` line):

```cmake
add_subdirectory(third_party/stb)
```

- [ ] **Step 5: Update THIRD_PARTY_NOTICES.md**

Append a new section to `THIRD_PARTY_NOTICES.md`:

```markdown
## stb_image (native/third_party/stb)

Single-header image loader by Sean Barrett. Used by the `assets` library
for TGA (and optionally PNG/JPEG/BMP) decoding.

- Upstream: https://github.com/nothings/stb
- Pinned commit: see `native/third_party/stb/UPSTREAM_VERSION`
- License: dual public-domain / MIT (see `LICENSE` in vendor dir)
```

- [ ] **Step 6: Verify build still works**

```bash
cmake --build build -j
```

Expected: PASS, no errors. The new `stb_image` target exists but isn't yet linked.

- [ ] **Step 7: Commit**

```bash
git add native/third_party/stb/ native/CMakeLists.txt THIRD_PARTY_NOTICES.md
git commit -m "feat(assets): vendor stb_image for TGA decoding"
```

---

### Task 2: Vendor GLAD (OpenGL 3.3 core loader)

**Files:**
- Create: `native/third_party/glad/include/glad/glad.h`
- Create: `native/third_party/glad/include/KHR/khrplatform.h`
- Create: `native/third_party/glad/src/glad.c`
- Create: `native/third_party/glad/LICENSE`
- Create: `native/third_party/glad/UPSTREAM_VERSION`
- Create: `native/third_party/glad/CMakeLists.txt`
- Modify: `native/CMakeLists.txt`
- Modify: `THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: Generate GLAD output via the web generator**

Configuration (document this in `UPSTREAM_VERSION`):
- Generator: https://glad.dav1d.de/
- Specification: OpenGL
- gl: Version 3.3
- Profile: Core
- Extensions: (none)
- Options: Generate a loader (checked)

Download the resulting zip and extract into `native/third_party/glad/` so the layout matches the file list above.

```bash
mkdir -p native/third_party/glad/include/glad native/third_party/glad/include/KHR native/third_party/glad/src
# After download + extraction:
cat > native/third_party/glad/UPSTREAM_VERSION <<'EOF'
Generated from https://glad.dav1d.de/ on 2026-05-09 with:
  spec: OpenGL
  api: gl=3.3
  profile: core
  extensions: (none)
  options: loader=on
EOF
```

- [ ] **Step 2: Copy MIT LICENSE**

```bash
cat > native/third_party/glad/LICENSE <<'EOF'
The MIT License (MIT)

Copyright (c) 2013-2022 David Herberth

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
EOF
```

- [ ] **Step 3: Write GLAD CMakeLists.txt**

```cmake
# native/third_party/glad/CMakeLists.txt
add_library(glad STATIC src/glad.c)
target_include_directories(glad PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

if(UNIX)
    target_link_libraries(glad PUBLIC dl)
endif()

# GLAD generated source has unused params + may emit -Wpedantic warnings on some compilers.
target_compile_options(glad PRIVATE -w)
```

- [ ] **Step 4: Wire into top-level CMake**

```cmake
# native/CMakeLists.txt — add after stb subdirectory
add_subdirectory(third_party/glad)
```

- [ ] **Step 5: Update THIRD_PARTY_NOTICES.md**

```markdown
## GLAD (native/third_party/glad)

Generated OpenGL function loader by David Herberth. Used by the `assets`
library to load GL 3.3 core function pointers.

- Upstream: https://github.com/Dav1dde/glad / https://glad.dav1d.de/
- Generation parameters: see `native/third_party/glad/UPSTREAM_VERSION`
- License: MIT (see `LICENSE` in vendor dir)
```

- [ ] **Step 6: Verify build**

```bash
cmake --build build -j
```

Expected: PASS, including the new `glad` static library.

- [ ] **Step 7: Commit**

```bash
git add native/third_party/glad/ native/CMakeLists.txt THIRD_PARTY_NOTICES.md
git commit -m "feat(assets): vendor GLAD as OpenGL 3.3 core loader"
```

---

### Task 3: Vendor glm (header-only math)

**Files:**
- Create: `native/third_party/glm/glm/` (full glm header tree)
- Create: `native/third_party/glm/LICENSE`
- Create: `native/third_party/glm/UPSTREAM_VERSION`
- Create: `native/third_party/glm/CMakeLists.txt`
- Modify: `native/CMakeLists.txt`
- Modify: `THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: Download glm pinned release**

```bash
mkdir -p native/third_party/glm
# Pin to glm 1.0.1 release tag
curl -L https://github.com/g-truc/glm/archive/refs/tags/1.0.1.tar.gz -o /tmp/glm-1.0.1.tar.gz
tar -xzf /tmp/glm-1.0.1.tar.gz -C /tmp
cp -r /tmp/glm-1.0.1/glm native/third_party/glm/
cp /tmp/glm-1.0.1/copying.txt native/third_party/glm/LICENSE
echo '1.0.1' > native/third_party/glm/UPSTREAM_VERSION
rm -rf /tmp/glm-1.0.1*
```

- [ ] **Step 2: Write CMakeLists.txt**

```cmake
# native/third_party/glm/CMakeLists.txt
add_library(glm INTERFACE)
target_include_directories(glm INTERFACE ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(glm INTERFACE
    GLM_FORCE_RADIANS
    GLM_FORCE_DEPTH_ZERO_TO_ONE
    GLM_ENABLE_EXPERIMENTAL
)
```

- [ ] **Step 3: Wire into top-level CMake**

```cmake
# native/CMakeLists.txt
add_subdirectory(third_party/glm)
```

- [ ] **Step 4: Update THIRD_PARTY_NOTICES.md**

```markdown
## glm (native/third_party/glm)

Header-only math library for OpenGL. Used by the `assets` library for
matrix / quaternion math.

- Upstream: https://github.com/g-truc/glm
- Pinned release: see `native/third_party/glm/UPSTREAM_VERSION`
- License: MIT (see `LICENSE` in vendor dir)
```

- [ ] **Step 5: Smoke-test glm includes work**

Create a temp file at `native/third_party/glm/smoke_test.cc`:

```cpp
#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>
int main() {
    glm::vec3 v(1.0f, 2.0f, 3.0f);
    glm::quat q(1.0f, 0.0f, 0.0f, 0.0f);
    glm::mat4 m(1.0f);
    return (m * glm::vec4(v, 1.0f)).x > 0 ? 0 : 1;
}
```

Compile:

```bash
c++ -std=c++20 -Inative/third_party/glm native/third_party/glm/smoke_test.cc -o /tmp/glm_smoke && /tmp/glm_smoke; echo $?
rm native/third_party/glm/smoke_test.cc /tmp/glm_smoke
```

Expected: exit code 0, no compile errors.

- [ ] **Step 6: Commit**

```bash
git add native/third_party/glm/ native/CMakeLists.txt THIRD_PARTY_NOTICES.md
git commit -m "feat(assets): vendor glm 1.0.1 for math types"
```

---

### Task 4: Vendor GLFW (test-only offscreen context)

**Files:**
- Create: `native/third_party/glfw/` (full glfw source tree)
- Create: `native/third_party/glfw/UPSTREAM_VERSION`
- Modify: `native/CMakeLists.txt`
- Modify: `THIRD_PARTY_NOTICES.md`

- [ ] **Step 1: Download glfw pinned release**

```bash
mkdir -p native/third_party
curl -L https://github.com/glfw/glfw/releases/download/3.4/glfw-3.4.zip -o /tmp/glfw-3.4.zip
unzip -q /tmp/glfw-3.4.zip -d /tmp
mv /tmp/glfw-3.4 native/third_party/glfw
echo '3.4' > native/third_party/glfw/UPSTREAM_VERSION
rm /tmp/glfw-3.4.zip
```

- [ ] **Step 2: Wire into top-level CMake — gated to test builds only**

In `native/CMakeLists.txt`, after the existing `option(OPEN_STBC_BUILD_TESTS ...)` line:

```cmake
if(OPEN_STBC_BUILD_TESTS)
    set(GLFW_BUILD_DOCS OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(GLFW_BUILD_TESTS OFF CACHE BOOL "" FORCE)
    set(GLFW_INSTALL OFF CACHE BOOL "" FORCE)
    add_subdirectory(third_party/glfw)
endif()
```

- [ ] **Step 3: Update THIRD_PARTY_NOTICES.md**

```markdown
## GLFW (native/third_party/glfw)

Multi-platform window/context library. Used **test-only** by the `assets`
library to create offscreen GL contexts in GPU tests.

- Upstream: https://github.com/glfw/glfw
- Pinned release: 3.4
- License: zlib/libpng (see `LICENSE.md` in vendor dir)
```

- [ ] **Step 4: Verify build**

```bash
cmake --build build -j
```

Expected: PASS. The new `glfw` static library builds when `OPEN_STBC_BUILD_TESTS=ON`.

- [ ] **Step 5: Commit**

```bash
git add native/third_party/glfw/ native/CMakeLists.txt THIRD_PARTY_NOTICES.md
git commit -m "feat(assets): vendor GLFW 3.4 for test-only offscreen contexts"
```

---

### Task 5: Scaffolding — empty `assets` library + test target

**Files:**
- Create: `native/src/assets/CMakeLists.txt`
- Create: `native/src/assets/include/assets/asset.h`
- Create: `native/src/assets/src/_placeholder.cc`
- Create: `native/tests/assets/CMakeLists.txt`
- Create: `native/tests/assets/cpu/sanity_test.cc`
- Modify: `native/CMakeLists.txt`
- Modify: `native/tests/CMakeLists.txt`

- [ ] **Step 1: Create the public-include skeleton**

```cpp
// native/src/assets/include/assets/asset.h
#pragma once

#include <memory>

namespace assets {

// Forward declarations of the public domain types defined in later headers.
struct Image;
class  Texture;
struct MeshCpu;
class  Mesh;
struct Material;
struct Bone;
struct Skeleton;
struct AnimationClip;
struct Node;
struct Model;

using ModelHandle = std::shared_ptr<const Model>;

}  // namespace assets
```

- [ ] **Step 2: Placeholder source so the static library has something to link**

```cpp
// native/src/assets/src/_placeholder.cc
// Linker placeholder; removed when first real .cc lands.
namespace assets { void _placeholder() noexcept {} }
```

- [ ] **Step 3: assets/ CMakeLists.txt**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/_placeholder.cc
)
target_include_directories(assets PUBLIC include)
target_compile_features(assets PUBLIC cxx_std_20)
target_link_libraries(assets PUBLIC nif glm glad stb_image)
```

- [ ] **Step 4: Wire into native/CMakeLists.txt**

After `add_subdirectory(src/nif)`:

```cmake
add_subdirectory(src/assets)
```

- [ ] **Step 5: Sanity test that compiles against the empty library**

```cpp
// native/tests/assets/cpu/sanity_test.cc
#include <gtest/gtest.h>
#include <assets/asset.h>

TEST(AssetsSanity, ForwardDeclsCompile) {
    assets::ModelHandle h;
    EXPECT_FALSE(static_cast<bool>(h));
}
```

- [ ] **Step 6: Tests CMakeLists for assets**

```cmake
# native/tests/assets/CMakeLists.txt
add_executable(assets_tests
    cpu/sanity_test.cc
)
target_link_libraries(assets_tests PRIVATE assets gtest gtest_main)
add_test(NAME assets_tests COMMAND assets_tests)
```

- [ ] **Step 7: Wire into native/tests/CMakeLists.txt**

Append:

```cmake
add_subdirectory(assets)
```

- [ ] **Step 8: Run the test**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: PASS. `AssetsSanity.ForwardDeclsCompile` succeeds.

- [ ] **Step 9: Commit**

```bash
git add native/src/assets/ native/tests/assets/ native/CMakeLists.txt native/tests/CMakeLists.txt
git commit -m "feat(assets): scaffold assets library + test target"
```

---

### Task 6: Public headers — domain types

**Files:**
- Create: `native/src/assets/include/assets/texture.h`
- Create: `native/src/assets/include/assets/mesh.h`
- Create: `native/src/assets/include/assets/material.h`
- Create: `native/src/assets/include/assets/skeleton.h`
- Create: `native/src/assets/include/assets/animation.h`
- Create: `native/src/assets/include/assets/model.h`
- Create: `native/tests/assets/cpu/header_compile_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: texture.h**

```cpp
// native/src/assets/include/assets/texture.h
#pragma once
#include <cstdint>
#include <span>
#include <vector>
#include <glad/glad.h>

namespace assets {

struct Image {
    enum class Format { RGBA8, RGB8, R8 };
    std::uint32_t width = 0, height = 0;
    Format format = Format::RGBA8;
    std::vector<std::uint8_t> pixels;
};

class Texture {
public:
    Texture() = default;
    Texture(GLuint id, std::uint32_t w, std::uint32_t h, bool mipmaps) noexcept;
    Texture(Texture&&) noexcept;
    Texture& operator=(Texture&&) noexcept;
    Texture(const Texture&) = delete;
    Texture& operator=(const Texture&) = delete;
    ~Texture();

    GLuint id() const noexcept { return id_; }
    std::uint32_t width() const noexcept { return width_; }
    std::uint32_t height() const noexcept { return height_; }
    bool has_mipmaps() const noexcept { return mipmaps_; }

private:
    GLuint id_ = 0;
    std::uint32_t width_ = 0, height_ = 0;
    bool mipmaps_ = false;
};

Image decode_tga(std::span<const std::uint8_t> bytes);
Texture upload_image(const Image& image, bool generate_mipmaps = true);

}  // namespace assets
```

- [ ] **Step 2: mesh.h**

```cpp
// native/src/assets/include/assets/mesh.h
#pragma once
#include <cstdint>
#include <optional>
#include <vector>
#include <glm/glm.hpp>
#include <glad/glad.h>

namespace assets {

struct MeshCpu {
    struct Vertex {
        glm::vec3      position{};
        glm::vec3      normal{};
        glm::vec2      uv{};
        glm::u8vec4    color{255, 255, 255, 255};
        glm::u8vec4    bone_indices{0, 0, 0, 0};
        glm::u8vec4    bone_weights{0, 0, 0, 0};
    };

    std::vector<Vertex> vertices;
    std::vector<std::uint32_t> indices;
    std::vector<std::vector<glm::vec2>> extra_uvs;
    int material_index = -1;
    int node_index = -1;
};

class Mesh {
public:
    Mesh() = default;
    Mesh(GLuint vao, GLuint vbo, GLuint ebo,
         std::uint32_t index_count, int material_index, int node_index) noexcept;
    Mesh(Mesh&&) noexcept;
    Mesh& operator=(Mesh&&) noexcept;
    Mesh(const Mesh&) = delete;
    Mesh& operator=(const Mesh&) = delete;
    ~Mesh();

    GLuint vao() const noexcept { return vao_; }
    GLuint vbo() const noexcept { return vbo_; }
    GLuint ebo() const noexcept { return ebo_; }
    std::uint32_t index_count() const noexcept { return index_count_; }
    int material_index() const noexcept { return material_index_; }
    int node_index() const noexcept { return node_index_; }

    const std::optional<MeshCpu>& cpu_data() const noexcept { return cpu_data_; }
    void set_cpu_data(MeshCpu data) { cpu_data_ = std::move(data); }

    const std::vector<Mesh>& lod_chain() const noexcept { return lod_chain_; }  // empty in v1

private:
    GLuint vao_ = 0, vbo_ = 0, ebo_ = 0;
    std::uint32_t index_count_ = 0;
    int material_index_ = -1, node_index_ = -1;
    std::optional<MeshCpu> cpu_data_;
    std::vector<Mesh> lod_chain_;
};

}  // namespace assets
```

- [ ] **Step 3: material.h**

```cpp
// native/src/assets/include/assets/material.h
#pragma once
#include <array>
#include <cstdint>
#include <glm/glm.hpp>

namespace assets {

struct Material {
    // From NiMaterialProperty
    glm::vec3 ambient{1.0f, 1.0f, 1.0f};
    glm::vec3 diffuse{1.0f, 1.0f, 1.0f};
    glm::vec3 specular{0.0f, 0.0f, 0.0f};
    glm::vec3 emissive{0.0f, 0.0f, 0.0f};
    float glossiness = 0.0f;
    float alpha = 1.0f;

    enum class StageSlot {
        Base = 0, Dark, Detail, Gloss, Glow, Bump, Decal0, Decal1, Decal2,
        Count
    };

    struct TextureStage {
        int           texture_index = -1;   // -1 = unused
        std::uint32_t clamp_mode    = 0;
        std::uint32_t filter_mode   = 0;
        std::uint32_t uv_set        = 0;
        std::uint32_t apply_mode    = 0;    // BC's tex-blend op
    };
    std::array<TextureStage, static_cast<std::size_t>(StageSlot::Count)> stages{};

    // From NiAlphaProperty (verbatim)
    bool          blend_enabled = false;
    std::uint32_t blend_src_factor = 0;
    std::uint32_t blend_dst_factor = 0;
    bool          alpha_test_enabled = false;
    std::uint32_t alpha_test_func = 0;
    std::uint8_t  alpha_test_threshold = 0;
    bool          zwrite_when_blended = false;

    // From NiZBufferProperty
    bool          depth_test_enabled = true;
    bool          depth_write_enabled = true;
    std::uint32_t depth_func = 0;

    // From NiVertexColorProperty
    std::uint32_t vc_lighting_mode = 0;
    std::uint32_t vc_source = 0;
};

}  // namespace assets
```

- [ ] **Step 4: skeleton.h**

```cpp
// native/src/assets/include/assets/skeleton.h
#pragma once
#include <string>
#include <vector>
#include <glm/glm.hpp>

namespace assets {

struct Bone {
    std::string name;
    int         parent_index = -1;
    glm::mat4   local_transform{1.0f};
    glm::mat4   inverse_bind_pose{1.0f};
};

struct Skeleton {
    std::vector<Bone> bones;
    int               root_bone_index = -1;
};

}  // namespace assets
```

- [ ] **Step 5: animation.h**

```cpp
// native/src/assets/include/assets/animation.h
#pragma once
#include <string>
#include <vector>
#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>

namespace assets {

struct AnimationClip {
    std::string name;
    float duration_seconds = 0.0f;

    struct TranslationKey { float time; glm::vec3 value; };
    struct RotationKey    { float time; glm::quat value; };
    struct ScaleKey       { float time; float     value; };
    struct VisibilityKey  { float time; bool      value; };
    struct FloatKey       { float time; float     value; };

    struct NodeTrack {
        std::string                  target_node_name;
        std::vector<TranslationKey>  translation;
        std::vector<RotationKey>     rotation;
        std::vector<ScaleKey>        scale;
        std::vector<VisibilityKey>   visibility;
        std::vector<FloatKey>        floats;
    };

    std::vector<NodeTrack> tracks;
};

}  // namespace assets
```

- [ ] **Step 6: model.h**

```cpp
// native/src/assets/include/assets/model.h
#pragma once
#include <filesystem>
#include <memory>
#include <string>
#include <vector>
#include <glm/glm.hpp>

#include <assets/animation.h>
#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/skeleton.h>
#include <assets/texture.h>

namespace assets {

struct Node {
    std::string       name;
    int               parent_index = -1;
    glm::mat4         local_transform{1.0f};
    std::vector<int>  children;
    std::vector<int>  meshes;
};

struct Model {
    std::vector<Node>          nodes;
    int                        root_node = 0;
    std::vector<Mesh>          meshes;
    std::vector<Texture>       textures;
    std::vector<Material>      materials;
    Skeleton                   skeleton;
    std::vector<AnimationClip> animations;
    std::filesystem::path      source;
};

}  // namespace assets
```

- [ ] **Step 7: Header-compile sanity test**

```cpp
// native/tests/assets/cpu/header_compile_test.cc
#include <gtest/gtest.h>
#include <assets/asset.h>
#include <assets/animation.h>
#include <assets/material.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/skeleton.h>
#include <assets/texture.h>

TEST(AssetsHeaders, AllPublicHeadersInclude) {
    assets::Image img;
    assets::MeshCpu mesh;
    assets::Material mat;
    assets::Skeleton skel;
    assets::AnimationClip clip;
    assets::Model model;
    EXPECT_EQ(img.width, 0u);
    EXPECT_EQ(mesh.material_index, -1);
    EXPECT_EQ(mat.alpha, 1.0f);
    EXPECT_EQ(skel.root_bone_index, -1);
    EXPECT_EQ(clip.duration_seconds, 0.0f);
    EXPECT_EQ(model.root_node, 0);
}
```

- [ ] **Step 8: Add to test sources**

```cmake
# native/tests/assets/CMakeLists.txt
add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
)
target_link_libraries(assets_tests PRIVATE assets gtest gtest_main)
add_test(NAME assets_tests COMMAND assets_tests)
```

- [ ] **Step 9: Build and test**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: PASS. Both `AssetsSanity.*` and `AssetsHeaders.*` succeed.

- [ ] **Step 10: Commit**

```bash
git add native/src/assets/include/assets/ native/tests/assets/CMakeLists.txt native/tests/assets/cpu/header_compile_test.cc
git commit -m "feat(assets): add public domain-type headers"
```

---

### Task 7: gl_handle.h — RAII GL handle wrappers

**Files:**
- Create: `native/src/assets/src/gl_handle.h`
- Create: `native/src/assets/src/gl_handle.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Create: `native/tests/assets/gpu/gl_handle_test.cc` *(will be activated in Task 15 once the GL fixture exists)*

- [ ] **Step 1: gl_handle.h**

```cpp
// native/src/assets/src/gl_handle.h
#pragma once
#include <glad/glad.h>
#include <utility>

namespace assets::detail {

/// RAII wrapper for a single GL texture. Calls glDeleteTextures on destruction
/// if id_ != 0. Move-only.
class TextureHandle {
public:
    TextureHandle() = default;
    explicit TextureHandle(GLuint id) noexcept : id_(id) {}
    TextureHandle(TextureHandle&& o) noexcept : id_(std::exchange(o.id_, 0)) {}
    TextureHandle& operator=(TextureHandle&& o) noexcept {
        if (this != &o) { reset(); id_ = std::exchange(o.id_, 0); }
        return *this;
    }
    ~TextureHandle() { reset(); }
    TextureHandle(const TextureHandle&) = delete;
    TextureHandle& operator=(const TextureHandle&) = delete;

    GLuint get() const noexcept { return id_; }
    GLuint release() noexcept { return std::exchange(id_, 0); }
    void   reset() noexcept;

private:
    GLuint id_ = 0;
};

/// RAII wrapper for a single GL buffer (VBO/EBO). Calls glDeleteBuffers.
class BufferHandle {
public:
    BufferHandle() = default;
    explicit BufferHandle(GLuint id) noexcept : id_(id) {}
    BufferHandle(BufferHandle&& o) noexcept : id_(std::exchange(o.id_, 0)) {}
    BufferHandle& operator=(BufferHandle&& o) noexcept {
        if (this != &o) { reset(); id_ = std::exchange(o.id_, 0); }
        return *this;
    }
    ~BufferHandle() { reset(); }
    BufferHandle(const BufferHandle&) = delete;
    BufferHandle& operator=(const BufferHandle&) = delete;

    GLuint get() const noexcept { return id_; }
    GLuint release() noexcept { return std::exchange(id_, 0); }
    void   reset() noexcept;

private:
    GLuint id_ = 0;
};

/// RAII wrapper for a single GL VAO. Calls glDeleteVertexArrays.
class VertexArrayHandle {
public:
    VertexArrayHandle() = default;
    explicit VertexArrayHandle(GLuint id) noexcept : id_(id) {}
    VertexArrayHandle(VertexArrayHandle&& o) noexcept : id_(std::exchange(o.id_, 0)) {}
    VertexArrayHandle& operator=(VertexArrayHandle&& o) noexcept {
        if (this != &o) { reset(); id_ = std::exchange(o.id_, 0); }
        return *this;
    }
    ~VertexArrayHandle() { reset(); }
    VertexArrayHandle(const VertexArrayHandle&) = delete;
    VertexArrayHandle& operator=(const VertexArrayHandle&) = delete;

    GLuint get() const noexcept { return id_; }
    GLuint release() noexcept { return std::exchange(id_, 0); }
    void   reset() noexcept;

private:
    GLuint id_ = 0;
};

}  // namespace assets::detail
```

- [ ] **Step 2: gl_handle.cc**

```cpp
// native/src/assets/src/gl_handle.cc
#include "gl_handle.h"

namespace assets::detail {

void TextureHandle::reset() noexcept {
    if (id_) { glDeleteTextures(1, &id_); id_ = 0; }
}
void BufferHandle::reset() noexcept {
    if (id_) { glDeleteBuffers(1, &id_); id_ = 0; }
}
void VertexArrayHandle::reset() noexcept {
    if (id_) { glDeleteVertexArrays(1, &id_); id_ = 0; }
}

}  // namespace assets::detail
```

- [ ] **Step 3: Update assets CMakeLists.txt to include gl_handle.cc**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/_placeholder.cc
    src/gl_handle.cc
)
target_include_directories(assets PUBLIC include)
target_compile_features(assets PUBLIC cxx_std_20)
target_link_libraries(assets PUBLIC nif glm glad stb_image)
```

- [ ] **Step 4: Verify build**

```bash
cmake --build build -j
```

Expected: PASS. `gl_handle.cc` compiles; tests still pass.

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/src/gl_handle.h native/src/assets/src/gl_handle.cc native/src/assets/CMakeLists.txt
git commit -m "feat(assets): add RAII GL handle wrappers (texture/buffer/VAO)"
```

---

### Task 8: Path resolver

**Files:**
- Create: `native/src/assets/include/assets/path_resolver.h`
- Create: `native/src/assets/src/path_resolver.cc`
- Create: `native/tests/assets/cpu/path_resolver_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/assets/cpu/path_resolver_test.cc
#include <gtest/gtest.h>
#include <assets/path_resolver.h>

#include <filesystem>
#include <fstream>
#include <unistd.h>          // getpid for unique tmp dirs

namespace fs = std::filesystem;

namespace {

class PathResolverTest : public ::testing::Test {
protected:
    fs::path tmp_dir;

    void SetUp() override {
        // fs::unique_path is non-standard; build our own.
        auto base = fs::temp_directory_path() / "assets-resolver";
        for (int i = 0; ; ++i) {
            auto candidate = base;
            candidate += "-" + std::to_string(::getpid()) + "-" + std::to_string(i);
            if (!fs::exists(candidate)) { tmp_dir = candidate; break; }
        }
        fs::create_directories(tmp_dir);
    }
    void TearDown() override {
        std::error_code ec;
        fs::remove_all(tmp_dir, ec);
    }
    void create_file(const fs::path& p) {
        fs::create_directories(p.parent_path());
        std::ofstream(p) << "x";
    }
};

}  // namespace

TEST_F(PathResolverTest, ExactBasenameMatch) {
    create_file(tmp_dir / "Ent-D_wing.tga");
    assets::PathResolver r;
    auto resolved = r.resolve("Ent-D_wing.tga", tmp_dir);
    EXPECT_EQ(resolved, tmp_dir / "Ent-D_wing.tga");
}

TEST_F(PathResolverTest, CaseInsensitiveLookup) {
    create_file(tmp_dir / "Ent-D_wing.tga");
    assets::PathResolver r;
    auto resolved = r.resolve("ent-d_wing.tga", tmp_dir);
    EXPECT_EQ(resolved, tmp_dir / "Ent-D_wing.tga");
}

TEST_F(PathResolverTest, AppendsTgaWhenNoExtension) {
    create_file(tmp_dir / "hull.tga");
    assets::PathResolver r;
    auto resolved = r.resolve("hull", tmp_dir);
    EXPECT_EQ(resolved, tmp_dir / "hull.tga");
}

TEST_F(PathResolverTest, ThrowsTextureNotFoundOnMiss) {
    assets::PathResolver r;
    EXPECT_THROW(r.resolve("missing.tga", tmp_dir), assets::TextureNotFound);
}

TEST_F(PathResolverTest, RebuildsCacheAfterMiss) {
    assets::PathResolver r;
    EXPECT_THROW(r.resolve("late.tga", tmp_dir), assets::TextureNotFound);
    create_file(tmp_dir / "late.tga");
    auto resolved = r.resolve("late.tga", tmp_dir);
    EXPECT_EQ(resolved, tmp_dir / "late.tga");
}
```

- [ ] **Step 2: Path resolver header**

```cpp
// native/src/assets/include/assets/path_resolver.h
#pragma once
#include <filesystem>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace assets {

class TextureNotFound : public std::runtime_error {
public:
    TextureNotFound(std::string basename, std::filesystem::path searched_dir);
    const std::string& basename() const noexcept { return basename_; }
    const std::filesystem::path& searched_dir() const noexcept { return searched_dir_; }
private:
    std::string basename_;
    std::filesystem::path searched_dir_;
};

class PathResolver {
public:
    /// Find the actual on-disk path for `basename` under `search_dir`.
    /// Case-insensitive. Auto-appends ".tga" when basename has no extension.
    /// Throws TextureNotFound on miss; rebuilds cache once and retries.
    std::filesystem::path resolve(
        std::string basename,
        const std::filesystem::path& search_dir);

private:
    using LowerToActual = std::unordered_map<std::string, std::string>;
    std::unordered_map<std::string, LowerToActual> cache_;

    LowerToActual& cache_for(const std::filesystem::path& dir, bool force_rebuild);
    static std::string to_lower(std::string_view s);
    static bool has_extension(std::string_view basename);
};

}  // namespace assets
```

- [ ] **Step 3: Path resolver impl**

```cpp
// native/src/assets/src/path_resolver.cc
#include <assets/path_resolver.h>

#include <algorithm>
#include <cctype>

namespace fs = std::filesystem;

namespace assets {

TextureNotFound::TextureNotFound(std::string basename, fs::path searched_dir)
    : std::runtime_error("texture not found: " + basename + " in " + searched_dir.string())
    , basename_(std::move(basename))
    , searched_dir_(std::move(searched_dir)) {}

std::string PathResolver::to_lower(std::string_view s) {
    std::string out(s);
    std::transform(out.begin(), out.end(), out.begin(),
        [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return out;
}

bool PathResolver::has_extension(std::string_view basename) {
    auto last_slash = basename.find_last_of("/\\");
    auto last_dot = basename.find_last_of('.');
    if (last_dot == std::string_view::npos) return false;
    if (last_slash != std::string_view::npos && last_dot < last_slash) return false;
    return true;
}

PathResolver::LowerToActual&
PathResolver::cache_for(const fs::path& dir, bool force_rebuild) {
    auto key = fs::weakly_canonical(dir).string();
    if (force_rebuild) cache_.erase(key);
    auto it = cache_.find(key);
    if (it != cache_.end()) return it->second;

    LowerToActual map;
    if (fs::is_directory(dir)) {
        for (auto& entry : fs::directory_iterator(dir)) {
            if (!entry.is_regular_file()) continue;
            auto fname = entry.path().filename().string();
            map[to_lower(fname)] = fname;
        }
    }
    return cache_.emplace(key, std::move(map)).first->second;
}

fs::path PathResolver::resolve(std::string basename, const fs::path& search_dir) {
    if (!has_extension(basename)) basename += ".tga";

    auto& dir_map = cache_for(search_dir, /*force_rebuild=*/false);
    auto lower = to_lower(basename);

    auto it = dir_map.find(lower);
    if (it != dir_map.end()) return search_dir / it->second;

    // Miss: rebuild map once and retry (handles new files dropped at runtime).
    auto& fresh = cache_for(search_dir, /*force_rebuild=*/true);
    it = fresh.find(lower);
    if (it != fresh.end()) return search_dir / it->second;

    throw TextureNotFound(std::move(basename), search_dir);
}

}  // namespace assets
```

- [ ] **Step 4: Add to library + tests**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/gl_handle.cc
    src/path_resolver.cc
)
# (drop _placeholder.cc — we have real code now)
target_include_directories(assets PUBLIC include)
target_compile_features(assets PUBLIC cxx_std_20)
target_link_libraries(assets PUBLIC nif glm glad stb_image)
```

```cmake
# native/tests/assets/CMakeLists.txt
add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/path_resolver_test.cc
)
target_link_libraries(assets_tests PRIVATE assets gtest gtest_main)
add_test(NAME assets_tests COMMAND assets_tests)
```

- [ ] **Step 5: Delete _placeholder.cc**

```bash
rm native/src/assets/src/_placeholder.cc
```

- [ ] **Step 6: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: All five `PathResolverTest.*` tests PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): case-insensitive path resolver with cache rebuild on miss"
```

---

### Task 9: TGA decoder via stb_image

**Files:**
- Create: `native/src/assets/src/texture_decode.cc`
- Create: `native/tests/assets/cpu/texture_decode_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`
- Add error types to: `native/src/assets/include/assets/texture.h`

- [ ] **Step 1: Add error types to texture.h** *(append at namespace level)*

```cpp
// native/src/assets/include/assets/texture.h — add near the top (after #includes)
#include <stdexcept>

// ... existing Image / Texture types ...

namespace assets {

class TextureDecodeError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class UnsupportedTga : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

}  // namespace assets
```

- [ ] **Step 2: Write the failing test**

```cpp
// native/tests/assets/cpu/texture_decode_test.cc
#include <gtest/gtest.h>
#include <assets/texture.h>

#include <cstdint>
#include <vector>

namespace {

// Hand-crafted minimal 2x1 24-bit uncompressed TGA: red pixel, blue pixel.
// TGA header: 18 bytes, then pixels in BGR order (TGA uses BGR).
std::vector<std::uint8_t> make_tga_24bit_2x1() {
    return {
        0,                    // id length
        0,                    // color map type
        2,                    // image type: uncompressed true-color
        0, 0, 0, 0, 0,        // color map spec (5 bytes, all zero)
        0, 0, 0, 0,           // x/y origin (4 bytes)
        2, 0,                 // width = 2
        1, 0,                 // height = 1
        24,                   // bits per pixel
        0,                    // image descriptor
        // pixel 0: red (BGR: 0x00, 0x00, 0xFF)
        0x00, 0x00, 0xFF,
        // pixel 1: blue (BGR: 0xFF, 0x00, 0x00)
        0xFF, 0x00, 0x00,
    };
}

std::vector<std::uint8_t> make_tga_indexed_unsupported() {
    return {
        0,
        1,                    // color map type: present
        1,                    // image type: uncompressed color-mapped
        0, 0, 0, 0, 16,       // color map spec
        0, 0, 0, 0,
        2, 0,
        1, 0,
        8,
        0,
        // (truncated; just enough to identify type)
    };
}

}  // namespace

TEST(TextureDecode, Tga24BitDecodes) {
    auto bytes = make_tga_24bit_2x1();
    auto img = assets::decode_tga(bytes);
    EXPECT_EQ(img.width, 2u);
    EXPECT_EQ(img.height, 1u);
    EXPECT_EQ(img.format, assets::Image::Format::RGB8);
    ASSERT_EQ(img.pixels.size(), 6u);
    // Pixel 0 should be red (RGB: 0xFF, 0x00, 0x00) after BGR→RGB conversion
    EXPECT_EQ(img.pixels[0], 0xFFu);
    EXPECT_EQ(img.pixels[1], 0x00u);
    EXPECT_EQ(img.pixels[2], 0x00u);
    EXPECT_EQ(img.pixels[3], 0x00u);
    EXPECT_EQ(img.pixels[4], 0x00u);
    EXPECT_EQ(img.pixels[5], 0xFFu);
}

TEST(TextureDecode, IndexedTgaThrowsUnsupported) {
    auto bytes = make_tga_indexed_unsupported();
    EXPECT_THROW(assets::decode_tga(bytes), assets::UnsupportedTga);
}

TEST(TextureDecode, GarbageThrowsDecodeError) {
    std::vector<std::uint8_t> garbage = {0xDE, 0xAD, 0xBE, 0xEF};
    EXPECT_THROW(assets::decode_tga(garbage), assets::TextureDecodeError);
}
```

- [ ] **Step 3: Implement decode_tga**

```cpp
// native/src/assets/src/texture_decode.cc
#include <assets/texture.h>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_TGA
#define STBI_NO_STDIO
#include <stb_image.h>

#include <cstring>

namespace assets {

namespace {

bool is_indexed_tga(std::span<const std::uint8_t> bytes) {
    if (bytes.size() < 18) return false;
    // Byte 1 = color map type; byte 2 = image type.
    // Image type 1 = uncompressed color-mapped, 9 = RLE color-mapped.
    return bytes[1] != 0 || bytes[2] == 1 || bytes[2] == 9;
}

bool is_16bpp_tga(std::span<const std::uint8_t> bytes) {
    if (bytes.size() < 18) return false;
    return bytes[16] == 16;  // bits-per-pixel field
}

}  // namespace

Image decode_tga(std::span<const std::uint8_t> bytes) {
    // Pre-flight: stb decodes 16bpp + indexed but the output format is awkward
    // for our use; reject up front so callers see a clear error.
    if (is_indexed_tga(bytes)) {
        throw UnsupportedTga("indexed (color-mapped) TGA is not supported");
    }
    if (is_16bpp_tga(bytes)) {
        throw UnsupportedTga("16bpp TGA is not supported");
    }

    int w = 0, h = 0, channels = 0;
    stbi_uc* data = stbi_load_from_memory(
        bytes.data(), static_cast<int>(bytes.size()),
        &w, &h, &channels, /*desired_channels=*/0);
    if (!data) {
        throw TextureDecodeError(stbi_failure_reason() ? stbi_failure_reason()
                                                       : "tga decode failed");
    }

    Image img;
    img.width  = static_cast<std::uint32_t>(w);
    img.height = static_cast<std::uint32_t>(h);
    switch (channels) {
        case 1: img.format = Image::Format::R8;   break;
        case 3: img.format = Image::Format::RGB8; break;
        case 4: img.format = Image::Format::RGBA8; break;
        default:
            stbi_image_free(data);
            throw UnsupportedTga(
                "unexpected channel count from stb: " + std::to_string(channels));
    }

    const std::size_t total = static_cast<std::size_t>(w * h * channels);
    img.pixels.assign(data, data + total);
    stbi_image_free(data);
    return img;
}

}  // namespace assets
```

- [ ] **Step 4: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/gl_handle.cc
    src/path_resolver.cc
    src/texture_decode.cc
)
```

```cmake
# native/tests/assets/CMakeLists.txt
add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/path_resolver_test.cc
    cpu/texture_decode_test.cc
)
```

- [ ] **Step 5: Build and test**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: `TextureDecode.*` (3 tests) and existing tests all PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): TGA decoder via stb_image"
```

---

### Task 10: NiRawImageData decoder

**Files:**
- Modify: `native/src/assets/src/texture_decode.cc`
- Modify: `native/src/assets/include/assets/texture.h`
- Create: `native/tests/assets/cpu/raw_image_decode_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: Add the public function declaration**

In `texture.h`, after `Image decode_tga(...)`:

```cpp
// Forward-declared because nif::NiRawImageData requires <nif/block.h>.
}  // namespace assets

namespace nif { struct NiRawImageData; }

namespace assets {
Image decode_raw_image(const nif::NiRawImageData& raw);
}  // namespace assets
```

- [ ] **Step 2: Write the failing test**

```cpp
// native/tests/assets/cpu/raw_image_decode_test.cc
#include <gtest/gtest.h>
#include <assets/texture.h>
#include <nif/block.h>

TEST(RawImageDecode, Rgb24Decodes) {
    nif::NiRawImageData raw;
    raw.width = 2;
    raw.height = 1;
    raw.image_type = 1;  // RGB
    // 2 pixels × 3 bytes = 6 bytes; row-major
    raw.pixels = {0xFF, 0x00, 0x00, 0x00, 0x00, 0xFF};

    auto img = assets::decode_raw_image(raw);
    EXPECT_EQ(img.width, 2u);
    EXPECT_EQ(img.height, 1u);
    EXPECT_EQ(img.format, assets::Image::Format::RGB8);
    EXPECT_EQ(img.pixels.size(), 6u);
    EXPECT_EQ(img.pixels[0], 0xFFu);
}

TEST(RawImageDecode, Rgba32Decodes) {
    nif::NiRawImageData raw;
    raw.width = 1;
    raw.height = 1;
    raw.image_type = 2;  // RGBA
    raw.pixels = {0x10, 0x20, 0x30, 0x40};

    auto img = assets::decode_raw_image(raw);
    EXPECT_EQ(img.format, assets::Image::Format::RGBA8);
    EXPECT_EQ(img.pixels.size(), 4u);
}

TEST(RawImageDecode, MismatchedPixelLengthThrows) {
    nif::NiRawImageData raw;
    raw.width = 4;
    raw.height = 4;
    raw.image_type = 1;  // RGB → expects 48 bytes
    raw.pixels = {0, 0, 0};  // 3 bytes — wrong

    EXPECT_THROW(assets::decode_raw_image(raw), assets::TextureDecodeError);
}
```

- [ ] **Step 3: Implement decode_raw_image**

Append to `texture_decode.cc`:

```cpp
#include <nif/block.h>

namespace assets {

Image decode_raw_image(const nif::NiRawImageData& raw) {
    Image img;
    img.width  = raw.width;
    img.height = raw.height;

    std::size_t channels;
    switch (raw.image_type) {
        case 1: img.format = Image::Format::RGB8;  channels = 3; break;
        case 2: img.format = Image::Format::RGBA8; channels = 4; break;
        default:
            throw UnsupportedTga(
                "NiRawImageData::image_type expected 1 (RGB) or 2 (RGBA), got "
                + std::to_string(raw.image_type));
    }

    const std::size_t expected = static_cast<std::size_t>(raw.width) * raw.height * channels;
    if (raw.pixels.size() != expected) {
        throw TextureDecodeError(
            "NiRawImageData payload size mismatch: expected "
            + std::to_string(expected) + ", got " + std::to_string(raw.pixels.size()));
    }
    img.pixels = raw.pixels;
    return img;
}

}  // namespace assets
```

- [ ] **Step 4: Add test to CMake**

```cmake
# native/tests/assets/CMakeLists.txt — add raw_image_decode_test.cc
add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/path_resolver_test.cc
    cpu/texture_decode_test.cc
    cpu/raw_image_decode_test.cc
)
```

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: 3 new `RawImageDecode.*` tests PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/src/texture_decode.cc native/src/assets/include/assets/texture.h native/tests/assets/
git commit -m "feat(assets): decode NiRawImageData blocks to Image"
```

---

### Task 11: Mesh build (NiTriShape + NiTriShapeData → MeshCpu)

**Files:**
- Create: `native/src/assets/src/mesh_build.h`
- Create: `native/src/assets/src/mesh_build.cc`
- Create: `native/tests/assets/cpu/mesh_build_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: mesh_build.h (internal)**

```cpp
// native/src/assets/src/mesh_build.h
#pragma once
#include <assets/mesh.h>
#include <nif/block.h>

namespace assets::detail {

/// Build a MeshCpu from a NiTriShape and its referenced NiTriShapeData.
/// `material_index` and `node_index` are stamped into the output but
/// otherwise opaque (resolved by the caller / orchestrator).
MeshCpu build_mesh_cpu(
    const nif::NiTriShape& shape,
    const nif::NiTriShapeData& data,
    int material_index,
    int node_index);

}  // namespace assets::detail
```

- [ ] **Step 2: Write the failing test**

```cpp
// native/tests/assets/cpu/mesh_build_test.cc
// Note: include is bare ("mesh_build.h") because tests/assets/CMakeLists.txt
// adds native/src/assets/src to the test target's PRIVATE include path.
#include <gtest/gtest.h>

#include "mesh_build.h"

TEST(MeshBuild, MinimalTriangle) {
    nif::NiTriShape shape;
    nif::NiTriShapeData data;
    data.num_vertices = 3;
    data.has_vertices = true;
    data.vertices = {{0.0f, 0.0f, 0.0f}, {1.0f, 0.0f, 0.0f}, {0.0f, 1.0f, 0.0f}};
    data.has_normals = true;
    data.normals = {{0, 0, 1}, {0, 0, 1}, {0, 0, 1}};
    data.has_uv = true;
    data.uv_sets.push_back({{0.0f, 0.0f}, {1.0f, 0.0f}, {0.0f, 1.0f}});
    data.num_triangles = 1;
    data.num_triangle_points = 3;
    data.triangles.push_back({0, 1, 2});

    auto mesh = assets::detail::build_mesh_cpu(shape, data, /*mat=*/0, /*node=*/2);
    EXPECT_EQ(mesh.vertices.size(), 3u);
    EXPECT_EQ(mesh.indices.size(), 3u);
    EXPECT_EQ(mesh.indices[0], 0u);
    EXPECT_EQ(mesh.indices[1], 1u);
    EXPECT_EQ(mesh.indices[2], 2u);
    EXPECT_EQ(mesh.material_index, 0);
    EXPECT_EQ(mesh.node_index, 2);
    EXPECT_FLOAT_EQ(mesh.vertices[1].position.x, 1.0f);
    EXPECT_EQ(mesh.vertices[0].color, glm::u8vec4(255, 255, 255, 255));
}

TEST(MeshBuild, VertexColorsAreCopied) {
    nif::NiTriShape shape;
    nif::NiTriShapeData data;
    data.num_vertices = 1;
    data.has_vertices = true;
    data.vertices = {{0, 0, 0}};
    data.has_vertex_colors = true;
    data.vertex_colors = {{0.5f, 0.25f, 1.0f, 0.75f}};
    data.has_uv = true;
    data.uv_sets.push_back({{0.0f, 0.0f}});

    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_EQ(mesh.vertices[0].color.r, static_cast<std::uint8_t>(0.5f * 255));
    EXPECT_EQ(mesh.vertices[0].color.a, static_cast<std::uint8_t>(0.75f * 255));
}

TEST(MeshBuild, ExtraUvSetsArePreserved) {
    nif::NiTriShape shape;
    nif::NiTriShapeData data;
    data.num_vertices = 1;
    data.has_vertices = true;
    data.vertices = {{0, 0, 0}};
    data.has_uv = true;
    data.uv_sets.push_back({{0.1f, 0.2f}});  // primary
    data.uv_sets.push_back({{0.3f, 0.4f}});  // extra (detail map)

    auto mesh = assets::detail::build_mesh_cpu(shape, data, -1, -1);
    EXPECT_FLOAT_EQ(mesh.vertices[0].uv.x, 0.1f);
    ASSERT_EQ(mesh.extra_uvs.size(), 1u);
    EXPECT_FLOAT_EQ(mesh.extra_uvs[0][0].x, 0.3f);
}
```

- [ ] **Step 3: Implement build_mesh_cpu**

```cpp
// native/src/assets/src/mesh_build.cc
#include "mesh_build.h"

#include <algorithm>

namespace assets::detail {

namespace {
inline std::uint8_t to_u8(float f) {
    f = std::clamp(f, 0.0f, 1.0f);
    return static_cast<std::uint8_t>(f * 255.0f + 0.5f);
}
}

MeshCpu build_mesh_cpu(
    const nif::NiTriShape& /*shape*/,
    const nif::NiTriShapeData& data,
    int material_index,
    int node_index)
{
    MeshCpu mesh;
    mesh.material_index = material_index;
    mesh.node_index = node_index;

    mesh.vertices.resize(data.num_vertices);

    // Positions (required for v1; if absent leave at default {0,0,0}).
    if (data.has_vertices) {
        for (std::size_t i = 0; i < data.vertices.size(); ++i) {
            const auto& v = data.vertices[i];
            mesh.vertices[i].position = {v.x, v.y, v.z};
        }
    }
    // Normals (optional).
    if (data.has_normals) {
        for (std::size_t i = 0; i < data.normals.size(); ++i) {
            const auto& n = data.normals[i];
            mesh.vertices[i].normal = {n.x, n.y, n.z};
        }
    }
    // Primary UV.
    if (data.has_uv && !data.uv_sets.empty()) {
        const auto& primary = data.uv_sets[0];
        for (std::size_t i = 0; i < primary.size(); ++i) {
            mesh.vertices[i].uv = {primary[i].u, primary[i].v};
        }
        // Extra UV sets stored separately.
        for (std::size_t set = 1; set < data.uv_sets.size(); ++set) {
            std::vector<glm::vec2> extra;
            extra.reserve(data.uv_sets[set].size());
            for (auto& tc : data.uv_sets[set]) extra.push_back({tc.u, tc.v});
            mesh.extra_uvs.push_back(std::move(extra));
        }
    }
    // Vertex colors (optional; default white).
    if (data.has_vertex_colors) {
        for (std::size_t i = 0; i < data.vertex_colors.size(); ++i) {
            const auto& c = data.vertex_colors[i];
            mesh.vertices[i].color = glm::u8vec4(
                to_u8(c.r), to_u8(c.g), to_u8(c.b), to_u8(c.a));
        }
    }

    // Indices: flatten triangle list. NIF gives uint16; we widen to uint32.
    mesh.indices.reserve(data.triangles.size() * 3);
    for (auto& tri : data.triangles) {
        mesh.indices.push_back(tri[0]);
        mesh.indices.push_back(tri[1]);
        mesh.indices.push_back(tri[2]);
    }
    return mesh;
}

}  // namespace assets::detail
```

- [ ] **Step 4: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/gl_handle.cc
    src/mesh_build.cc
    src/path_resolver.cc
    src/texture_decode.cc
)
```

```cmake
# native/tests/assets/CMakeLists.txt
add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/mesh_build_test.cc
    cpu/path_resolver_test.cc
    cpu/raw_image_decode_test.cc
    cpu/texture_decode_test.cc
)
target_link_libraries(assets_tests PRIVATE assets gtest gtest_main)
# Tests need internal-header access:
target_include_directories(assets_tests PRIVATE ${CMAKE_SOURCE_DIR}/native/src/assets/src)
```

Note the include path adjustment — tests reach into `src/` for the internal `mesh_build.h`. Without it, the test won't find the header.

Update the test's `#include` accordingly:

```cpp
#include "mesh_build.h"   // resolved via target_include_directories above
```

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: 3 new `MeshBuild.*` tests PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): build MeshCpu from NiTriShape/NiTriShapeData"
```

---

### Task 12: Material build (property chain → Material)

**Files:**
- Create: `native/src/assets/src/material_build.h`
- Create: `native/src/assets/src/material_build.cc`
- Create: `native/src/assets/docs/material_translation.md`
- Create: `native/tests/assets/cpu/material_build_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: material_build.h (internal)**

```cpp
// native/src/assets/src/material_build.h
#pragma once
#include <assets/material.h>
#include <nif/block.h>

#include <unordered_map>

namespace assets::detail {

/// Inputs for building a Material — the property blocks linked from a
/// NiTriShape, plus an image-link → texture-index map produced by the
/// orchestrator (which has already loaded all textures into Model::textures).
struct MaterialInputs {
    const nif::NiMaterialProperty*     material      = nullptr;
    const nif::NiTexturingProperty*    texturing     = nullptr;
    const nif::NiMultiTextureProperty* multi_texture = nullptr;
    const nif::NiAlphaProperty*        alpha         = nullptr;
    const nif::NiZBufferProperty*      zbuffer       = nullptr;
    const nif::NiVertexColorProperty*  vertex_color  = nullptr;
    /// Maps NIF block index of a NiImage → assets::Model::textures index.
    const std::unordered_map<std::uint32_t, int>* image_to_texture = nullptr;
};

Material build_material(const MaterialInputs&);

}  // namespace assets::detail
```

- [ ] **Step 2: material_translation.md (place-holder doc)**

```markdown
# Material Translation Notes

This file documents how BC NIF property values map onto the
`assets::Material` fields. v1 is BC-faithful: enum values are stored
verbatim and interpreted by the renderer at draw time.

## NiMaterialProperty
- `ambient/diffuse/specular/emissive` → `Material::ambient/diffuse/specular/emissive`
  (Color3 → glm::vec3; alpha component carried separately as `Material::alpha`).
- `glossiness` → `Material::glossiness`.

## NiAlphaProperty
- `flags` is a packed bitfield (D3D7-era). Decoded as:
  - bit 0: alpha-blend enable
  - bits 1–4: src blend factor (D3DBLEND_*)
  - bits 5–8: dst blend factor (D3DBLEND_*)
  - bit 9: alpha-test enable
  - bits 10–12: alpha-test func
  - bit 13: zwrite enable (when blended)
- `threshold` → `Material::alpha_test_threshold` (uint8 0–255).

## NiZBufferProperty
- `flags`: bit 0 = depth test enable; bit 1 = depth write enable; remaining
  bits encode comparison function (low values from D3DCMP_*).

## NiVertexColorProperty
- `vertex_mode` → `Material::vc_source` (replace / multiply / etc.).
- `lighting_mode` → `Material::vc_lighting_mode`.

## NiTexturingProperty → Material::stages
| NIF slot   | StageSlot |
|------------|-----------|
| base       | Base      |
| dark       | Dark      |
| detail     | Detail    |
| gloss      | Gloss     |
| glow       | Glow      |
| bump_map   | Bump      |
| decal0     | Decal0    |
| decal1     | Decal1    |
| decal2     | Decal2    |

`apply_mode` from the NiTexturingProperty propagates into
`TextureStage::apply_mode` for all populated stages (BC has one apply mode
per property, not per stage).

## NiMultiTextureProperty → Material::stages
NiMultiTextureProperty has 5 `MultiTextureElement`s. Their slot mapping is
established empirically during implementation by checking which BC ships use
this block and which visual effects they drive. Initial mapping (subject to
revision in the implementation commit):

| NMT element index | StageSlot |
|-------------------|-----------|
| 0 | Base |
| 1 | Dark |
| 2 | Detail |
| 3 | Glow |
| 4 | Gloss |

Update this table when implementation reveals different usage.
```

- [ ] **Step 3: Write the failing test**

```cpp
// native/tests/assets/cpu/material_build_test.cc
#include <gtest/gtest.h>
#include "material_build.h"

namespace {

assets::detail::MaterialInputs basic_inputs() {
    return {};
}

}  // namespace

TEST(MaterialBuild, NiMaterialPropertyCopiesColors) {
    nif::NiMaterialProperty mat;
    mat.ambient = {0.1f, 0.2f, 0.3f};
    mat.diffuse = {0.4f, 0.5f, 0.6f};
    mat.specular = {0.7f, 0.8f, 0.9f};
    mat.emissive = {1.0f, 1.0f, 1.0f};
    mat.glossiness = 32.0f;
    mat.alpha = 0.5f;

    assets::detail::MaterialInputs in = basic_inputs();
    in.material = &mat;
    auto m = assets::detail::build_material(in);
    EXPECT_FLOAT_EQ(m.ambient.x, 0.1f);
    EXPECT_FLOAT_EQ(m.diffuse.y, 0.5f);
    EXPECT_FLOAT_EQ(m.specular.z, 0.9f);
    EXPECT_FLOAT_EQ(m.emissive.x, 1.0f);
    EXPECT_FLOAT_EQ(m.glossiness, 32.0f);
    EXPECT_FLOAT_EQ(m.alpha, 0.5f);
}

TEST(MaterialBuild, NiAlphaPropertyDecodesFlags) {
    nif::NiAlphaProperty alpha;
    alpha.flags = 0b0000'0000'0000'0001u;  // only "blend enabled" bit
    alpha.threshold = 128;

    assets::detail::MaterialInputs in = basic_inputs();
    in.alpha = &alpha;
    auto m = assets::detail::build_material(in);
    EXPECT_TRUE(m.blend_enabled);
    EXPECT_FALSE(m.alpha_test_enabled);
    EXPECT_EQ(m.alpha_test_threshold, 128);
}

TEST(MaterialBuild, NiZBufferPropertyDecodesFlags) {
    nif::NiZBufferProperty zb;
    // bit 0: test enable, bit 1: write enable
    zb.flags = 0b11;

    assets::detail::MaterialInputs in = basic_inputs();
    in.zbuffer = &zb;
    auto m = assets::detail::build_material(in);
    EXPECT_TRUE(m.depth_test_enabled);
    EXPECT_TRUE(m.depth_write_enabled);
}

TEST(MaterialBuild, NiTexturingPropertyMapsStagesViaImageMap) {
    nif::NiImage image;        // not actually inspected — only its block index
    nif::NiTexturingProperty tex;
    tex.apply_mode = 2;
    tex.texture_count = 7;
    tex.base.has = true;
    tex.base.source_link = 42;
    tex.base.uv_set = 0;
    tex.glow.has = true;
    tex.glow.source_link = 17;

    std::unordered_map<std::uint32_t, int> image_to_texture = {
        {42, 3},  // base → Model::textures[3]
        {17, 7},  // glow → Model::textures[7]
    };

    assets::detail::MaterialInputs in = basic_inputs();
    in.texturing = &tex;
    in.image_to_texture = &image_to_texture;
    auto m = assets::detail::build_material(in);

    using S = assets::Material::StageSlot;
    EXPECT_EQ(m.stages[(int)S::Base].texture_index, 3);
    EXPECT_EQ(m.stages[(int)S::Glow].texture_index, 7);
    EXPECT_EQ(m.stages[(int)S::Dark].texture_index, -1);  // unused
    EXPECT_EQ(m.stages[(int)S::Base].apply_mode, 2u);
}

TEST(MaterialBuild, NiVertexColorPropertyCopiesModes) {
    nif::NiVertexColorProperty vc;
    vc.vertex_mode = 2;
    vc.lighting_mode = 1;

    assets::detail::MaterialInputs in = basic_inputs();
    in.vertex_color = &vc;
    auto m = assets::detail::build_material(in);
    EXPECT_EQ(m.vc_source, 2u);
    EXPECT_EQ(m.vc_lighting_mode, 1u);
}

TEST(MaterialBuild, DefaultsWhenNoPropertiesPresent) {
    assets::detail::MaterialInputs in = basic_inputs();
    auto m = assets::detail::build_material(in);
    EXPECT_FLOAT_EQ(m.alpha, 1.0f);
    EXPECT_FALSE(m.blend_enabled);
    EXPECT_TRUE(m.depth_test_enabled);
    EXPECT_TRUE(m.depth_write_enabled);
}
```

- [ ] **Step 4: Implement build_material**

```cpp
// native/src/assets/src/material_build.cc
#include "material_build.h"

namespace assets::detail {

namespace {

void apply_material_property(Material& m, const nif::NiMaterialProperty& src) {
    m.ambient    = {src.ambient.r, src.ambient.g, src.ambient.b};
    m.diffuse    = {src.diffuse.r, src.diffuse.g, src.diffuse.b};
    m.specular   = {src.specular.r, src.specular.g, src.specular.b};
    m.emissive   = {src.emissive.r, src.emissive.g, src.emissive.b};
    m.glossiness = src.glossiness;
    m.alpha      = src.alpha;
}

void apply_alpha_property(Material& m, const nif::NiAlphaProperty& src) {
    // Decode the legacy NiAlphaProperty bitfield. Layout (D3D7-era):
    //   bit 0     : alpha-blend enable
    //   bits 1-4  : src blend factor (D3DBLEND_*)
    //   bits 5-8  : dst blend factor (D3DBLEND_*)
    //   bit 9     : alpha-test enable
    //   bits 10-12: alpha-test func (D3DCMP_*)
    //   bit 13    : zwrite-when-blended enable
    auto f = src.flags;
    m.blend_enabled       = (f & 0x0001) != 0;
    m.blend_src_factor    = (f >> 1)  & 0x0F;
    m.blend_dst_factor    = (f >> 5)  & 0x0F;
    m.alpha_test_enabled  = (f & 0x0200) != 0;
    m.alpha_test_func     = (f >> 10) & 0x07;
    m.zwrite_when_blended = (f & 0x2000) != 0;
    m.alpha_test_threshold = src.threshold;
}

void apply_zbuffer_property(Material& m, const nif::NiZBufferProperty& src) {
    auto f = src.flags;
    m.depth_test_enabled  = (f & 0x01) != 0;
    m.depth_write_enabled = (f & 0x02) != 0;
    m.depth_func          = (f >> 2)  & 0x07;
}

void apply_vertex_color_property(Material& m, const nif::NiVertexColorProperty& src) {
    m.vc_source           = src.vertex_mode;
    m.vc_lighting_mode    = src.lighting_mode;
}

void apply_stage(
    Material::TextureStage& stage,
    const nif::TexDesc& src,
    std::uint32_t apply_mode,
    const std::unordered_map<std::uint32_t, int>* image_to_texture)
{
    if (!src.has) return;
    int tex_idx = -1;
    if (image_to_texture) {
        auto it = image_to_texture->find(src.source_link);
        if (it != image_to_texture->end()) tex_idx = it->second;
    }
    stage.texture_index = tex_idx;
    stage.clamp_mode    = src.clamp_mode;
    stage.filter_mode   = src.filter_mode;
    stage.uv_set        = src.uv_set;
    stage.apply_mode    = apply_mode;
}

void apply_texturing_property(
    Material& m,
    const nif::NiTexturingProperty& src,
    const std::unordered_map<std::uint32_t, int>* image_to_texture)
{
    using S = Material::StageSlot;
    apply_stage(m.stages[(int)S::Base],   src.base,     src.apply_mode, image_to_texture);
    apply_stage(m.stages[(int)S::Dark],   src.dark,     src.apply_mode, image_to_texture);
    apply_stage(m.stages[(int)S::Detail], src.detail,   src.apply_mode, image_to_texture);
    apply_stage(m.stages[(int)S::Gloss],  src.gloss,    src.apply_mode, image_to_texture);
    apply_stage(m.stages[(int)S::Glow],   src.glow,     src.apply_mode, image_to_texture);
    apply_stage(m.stages[(int)S::Bump],   src.bump_map, src.apply_mode, image_to_texture);
    apply_stage(m.stages[(int)S::Decal0], src.decal0,   src.apply_mode, image_to_texture);
    if (src.texture_count >= 8)
        apply_stage(m.stages[(int)S::Decal1], src.decal1, src.apply_mode, image_to_texture);
    if (src.texture_count >= 9)
        apply_stage(m.stages[(int)S::Decal2], src.decal2, src.apply_mode, image_to_texture);
}

void apply_multi_texture_property(
    Material& m,
    const nif::NiMultiTextureProperty& src,
    const std::unordered_map<std::uint32_t, int>* image_to_texture)
{
    using S = Material::StageSlot;
    static constexpr S slot_map[5] = {S::Base, S::Dark, S::Detail, S::Glow, S::Gloss};
    for (std::size_t i = 0; i < 5; ++i) {
        const auto& el = src.elements[i];
        if (!el.has_image) continue;
        auto& stage = m.stages[(int)slot_map[i]];
        int tex_idx = -1;
        if (image_to_texture) {
            auto it = image_to_texture->find(el.image_link);
            if (it != image_to_texture->end()) tex_idx = it->second;
        }
        stage.texture_index = tex_idx;
        stage.clamp_mode    = el.clamp_mode;
        stage.filter_mode   = el.filter_mode;
        stage.uv_set        = el.uv_set;
        stage.apply_mode    = 2;  // APPLY_MODULATE — niflib default
    }
}

}  // namespace

Material build_material(const MaterialInputs& in) {
    Material m;
    if (in.material)      apply_material_property(m, *in.material);
    if (in.alpha)         apply_alpha_property(m, *in.alpha);
    if (in.zbuffer)       apply_zbuffer_property(m, *in.zbuffer);
    if (in.vertex_color)  apply_vertex_color_property(m, *in.vertex_color);
    if (in.texturing)     apply_texturing_property(m, *in.texturing, in.image_to_texture);
    if (in.multi_texture) apply_multi_texture_property(m, *in.multi_texture, in.image_to_texture);
    return m;
}

}  // namespace assets::detail
```

- [ ] **Step 5: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/gl_handle.cc
    src/material_build.cc
    src/mesh_build.cc
    src/path_resolver.cc
    src/texture_decode.cc
)
```

```cmake
# native/tests/assets/CMakeLists.txt — add material_build_test.cc
add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/material_build_test.cc
    cpu/mesh_build_test.cc
    cpu/path_resolver_test.cc
    cpu/raw_image_decode_test.cc
    cpu/texture_decode_test.cc
)
```

- [ ] **Step 6: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: 6 new `MaterialBuild.*` tests PASS.

- [ ] **Step 7: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): build Material from BC NIF property chain (verbatim)"
```

---

### Task 13: Skeleton build (NiNode/NiTriShapeSkinController → Skeleton)

**Files:**
- Create: `native/src/assets/src/skeleton_build.h`
- Create: `native/src/assets/src/skeleton_build.cc`
- Create: `native/tests/assets/cpu/skeleton_build_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: skeleton_build.h**

```cpp
// native/src/assets/src/skeleton_build.h
#pragma once
#include <assets/skeleton.h>
#include <nif/file.h>

#include <unordered_map>

namespace assets::detail {

struct SkeletonBuildResult {
    Skeleton skeleton;
    /// Maps NIF block index of a NiNode used as a bone → Skeleton::bones index.
    /// Used by mesh-build to convert per-vertex bone references.
    std::unordered_map<std::uint32_t, int> nif_block_to_bone_index;
};

/// Walks all NiTriShapeSkinController blocks in the file, gathers the bones
/// they reference, and builds a flat Skeleton with parent indices derived
/// from the NIF scene graph. Returns an empty skeleton if no skinning is
/// present (typical for ships).
SkeletonBuildResult build_skeleton(const nif::File& file);

}  // namespace assets::detail
```

- [ ] **Step 2: Write the failing test**

```cpp
// native/tests/assets/cpu/skeleton_build_test.cc
#include <gtest/gtest.h>
#include "skeleton_build.h"

#include <nif/block.h>
#include <nif/file.h>

namespace {

// Build a synthetic nif::File: pelvis (bone 0) -> spine (bone 1) -> arm (bone 2),
// referenced by a NiTriShapeSkinController.
nif::File build_synthetic_skinned_file() {
    nif::File f;
    // Block 0: NiNode root
    {
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);
    }
    // Block 1: pelvis bone (NiNode) — child of root
    {
        nif::NiNode b;
        b.av.obj.name = "Pelvis";
        b.av.translation = {0, 0, 1};
        b.child_links = {2};
        f.blocks.push_back(b);
    }
    // Block 2: spine — child of pelvis
    {
        nif::NiNode b;
        b.av.obj.name = "Spine";
        b.av.translation = {0, 0, 2};
        b.child_links = {3};
        f.blocks.push_back(b);
    }
    // Block 3: arm — child of spine
    {
        nif::NiNode b;
        b.av.obj.name = "Arm";
        b.av.translation = {1, 0, 2};
        f.blocks.push_back(b);
    }
    // Block 4: NiTriShapeSkinController — references all three bones
    {
        nif::NiTriShapeSkinController c;
        c.num_bones = 3;
        c.bone_links = {1, 2, 3};
        f.blocks.push_back(c);
    }
    return f;
}

}  // namespace

TEST(SkeletonBuild, NoSkinningProducesEmptySkeleton) {
    nif::File f;
    nif::NiNode root;
    root.av.obj.name = "Root";
    f.blocks.push_back(root);

    auto result = assets::detail::build_skeleton(f);
    EXPECT_TRUE(result.skeleton.bones.empty());
    EXPECT_EQ(result.skeleton.root_bone_index, -1);
}

TEST(SkeletonBuild, FlattensBonesWithParentIndices) {
    auto f = build_synthetic_skinned_file();
    auto result = assets::detail::build_skeleton(f);

    ASSERT_EQ(result.skeleton.bones.size(), 3u);
    // Bones identified by name; parent_index reflects scene-graph nesting.
    auto find = [&](std::string n) -> int {
        for (std::size_t i = 0; i < result.skeleton.bones.size(); ++i)
            if (result.skeleton.bones[i].name == n) return static_cast<int>(i);
        return -1;
    };
    int pelvis = find("Pelvis"), spine = find("Spine"), arm = find("Arm");
    ASSERT_NE(pelvis, -1);
    ASSERT_NE(spine, -1);
    ASSERT_NE(arm, -1);

    EXPECT_EQ(result.skeleton.bones[pelvis].parent_index, -1);
    EXPECT_EQ(result.skeleton.bones[spine].parent_index, pelvis);
    EXPECT_EQ(result.skeleton.bones[arm].parent_index, spine);
}

TEST(SkeletonBuild, NifBlockIndexMapPopulated) {
    auto f = build_synthetic_skinned_file();
    auto result = assets::detail::build_skeleton(f);

    EXPECT_TRUE(result.nif_block_to_bone_index.count(1));  // pelvis
    EXPECT_TRUE(result.nif_block_to_bone_index.count(2));  // spine
    EXPECT_TRUE(result.nif_block_to_bone_index.count(3));  // arm
}
```

- [ ] **Step 3: Implement build_skeleton**

```cpp
// native/src/assets/src/skeleton_build.cc
#include "skeleton_build.h"

#include <nif/block.h>

#include <set>
#include <unordered_set>

namespace assets::detail {

namespace {

struct ParentMap {
    /// nif_block_index → parent nif_block_index (-1 = root)
    std::unordered_map<std::uint32_t, std::int64_t> parents;
};

ParentMap compute_parent_map(const nif::File& f) {
    ParentMap map;
    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* node = std::get_if<nif::NiNode>(&f.blocks[i]);
        if (!node) continue;
        for (auto child : node->child_links) {
            map.parents[child] = static_cast<std::int64_t>(i);
        }
    }
    return map;
}

std::set<std::uint32_t> gather_bone_block_indices(const nif::File& f) {
    std::set<std::uint32_t> bones;
    for (auto& b : f.blocks) {
        const auto* skin = std::get_if<nif::NiTriShapeSkinController>(&b);
        if (!skin) continue;
        for (auto link : skin->bone_links) bones.insert(link);
    }
    return bones;
}

const nif::NiNode* node_at(const nif::File& f, std::uint32_t idx) {
    if (idx >= f.blocks.size()) return nullptr;
    return std::get_if<nif::NiNode>(&f.blocks[idx]);
}

glm::mat4 av_to_local_transform(const nif::AvObjectBase& av) {
    glm::mat4 m(1.0f);
    // Rotation (row-major Mat3x3 → column-major glm).
    m[0] = {av.rotation.m[0], av.rotation.m[3], av.rotation.m[6], 0};
    m[1] = {av.rotation.m[1], av.rotation.m[4], av.rotation.m[7], 0};
    m[2] = {av.rotation.m[2], av.rotation.m[5], av.rotation.m[8], 0};
    m[3] = {av.translation.x, av.translation.y, av.translation.z, 1};
    if (av.scale != 1.0f) {
        m[0] *= av.scale;
        m[1] *= av.scale;
        m[2] *= av.scale;
    }
    return m;
}

}  // namespace

SkeletonBuildResult build_skeleton(const nif::File& f) {
    SkeletonBuildResult out;
    auto bone_indices = gather_bone_block_indices(f);
    if (bone_indices.empty()) return out;

    auto parents = compute_parent_map(f);

    // First pass: assign bone indices in stable order.
    int next_index = 0;
    for (auto nif_idx : bone_indices) {
        auto* node = node_at(f, nif_idx);
        if (!node) continue;  // skip missing nodes — robust to odd files
        Bone b;
        b.name = node->av.obj.name;
        b.local_transform = av_to_local_transform(node->av);
        // inverse_bind_pose left as identity in v1; computed by walking world
        // transforms when the scene-graph runtime arrives.
        out.skeleton.bones.push_back(std::move(b));
        out.nif_block_to_bone_index[nif_idx] = next_index++;
    }

    // Second pass: parent_index from the parent_map.
    for (auto nif_idx : bone_indices) {
        if (!out.nif_block_to_bone_index.count(nif_idx)) continue;
        int self_bone = out.nif_block_to_bone_index[nif_idx];
        auto pit = parents.parents.find(nif_idx);
        if (pit == parents.parents.end() || pit->second < 0) {
            out.skeleton.bones[self_bone].parent_index = -1;
            continue;
        }
        auto parent_nif = static_cast<std::uint32_t>(pit->second);
        auto bit = out.nif_block_to_bone_index.find(parent_nif);
        out.skeleton.bones[self_bone].parent_index =
            (bit != out.nif_block_to_bone_index.end()) ? bit->second : -1;
    }

    // Pick a root: first bone whose parent isn't itself a bone.
    for (std::size_t i = 0; i < out.skeleton.bones.size(); ++i) {
        if (out.skeleton.bones[i].parent_index == -1) {
            out.skeleton.root_bone_index = static_cast<int>(i);
            break;
        }
    }
    return out;
}

}  // namespace assets::detail
```

- [ ] **Step 4: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/gl_handle.cc
    src/material_build.cc
    src/mesh_build.cc
    src/path_resolver.cc
    src/skeleton_build.cc
    src/texture_decode.cc
)
```

```cmake
# native/tests/assets/CMakeLists.txt — add skeleton_build_test.cc
```

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: 3 new `SkeletonBuild.*` tests PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): build Skeleton from NiNode tree + NiTriShapeSkinController bone links"
```

---

### Task 14: Animation build (NiKeyframeController/Data → AnimationClip)

**Files:**
- Create: `native/src/assets/src/animation_build.h`
- Create: `native/src/assets/src/animation_build.cc`
- Create: `native/tests/assets/cpu/animation_build_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: animation_build.h**

```cpp
// native/src/assets/src/animation_build.h
#pragma once
#include <assets/animation.h>
#include <nif/file.h>

#include <vector>

namespace assets::detail {

/// Walk all NiKeyframeController, NiVisController, NiRollController blocks
/// in the file. Produce one AnimationClip per *target node*; tracks for the
/// same target are merged into a single clip's NodeTrack.
std::vector<AnimationClip> build_animations(const nif::File& f);

}  // namespace assets::detail
```

- [ ] **Step 2: Write the failing test**

```cpp
// native/tests/assets/cpu/animation_build_test.cc
#include <gtest/gtest.h>
#include "animation_build.h"

#include <nif/block.h>

namespace {

nif::File build_synthetic_keyframed_file() {
    nif::File f;
    // Block 0: NiNode "Saucer" — controller target
    nif::NiNode node;
    node.av.obj.name = "Saucer";
    node.av.obj.controller_link = 1;  // points at controller in block 1
    f.blocks.push_back(node);

    // Block 1: NiKeyframeController, data_link → block 2
    nif::NiKeyframeController kc;
    kc.start_time = 0.0f;
    kc.stop_time  = 2.0f;
    kc.data_link  = 2;
    f.blocks.push_back(kc);

    // Block 2: NiKeyframeData with two translation keys
    nif::NiKeyframeData kd;
    kd.translations.num_keys = 2;
    kd.translations.interpolation = 1;  // linear
    kd.translations.keys = {
        {.time = 0.0f, .value = nif::Vec3{0,0,0}},
        {.time = 2.0f, .value = nif::Vec3{10,0,0}},
    };
    f.blocks.push_back(kd);
    return f;
}

}  // namespace

TEST(AnimationBuild, NoControllersProducesEmptyList) {
    nif::File f;
    auto anims = assets::detail::build_animations(f);
    EXPECT_TRUE(anims.empty());
}

TEST(AnimationBuild, KeyframeControllerProducesClip) {
    auto f = build_synthetic_keyframed_file();
    auto anims = assets::detail::build_animations(f);
    ASSERT_EQ(anims.size(), 1u);
    EXPECT_FLOAT_EQ(anims[0].duration_seconds, 2.0f);
    ASSERT_EQ(anims[0].tracks.size(), 1u);
    auto& track = anims[0].tracks[0];
    EXPECT_EQ(track.target_node_name, "Saucer");
    EXPECT_EQ(track.translation.size(), 2u);
    EXPECT_FLOAT_EQ(track.translation[0].time, 0.0f);
    EXPECT_FLOAT_EQ(track.translation[1].value.x, 10.0f);
}
```

- [ ] **Step 3: Implement build_animations**

```cpp
// native/src/assets/src/animation_build.cc
#include "animation_build.h"

#include <nif/block.h>

#include <unordered_map>

namespace assets::detail {

namespace {

const nif::NiNode* find_controller_target(const nif::File& f, std::uint32_t controller_idx) {
    for (auto& b : f.blocks) {
        if (auto* node = std::get_if<nif::NiNode>(&b)) {
            if (node->av.obj.controller_link == controller_idx) return node;
        }
    }
    return nullptr;
}

template <typename DataBlock>
const DataBlock* data_at(const nif::File& f, std::uint32_t idx) {
    if (idx >= f.blocks.size()) return nullptr;
    return std::get_if<DataBlock>(&f.blocks[idx]);
}

void apply_keyframe_data(AnimationClip::NodeTrack& track,
                         const nif::NiKeyframeData& kd,
                         float& clip_duration) {
    for (auto& k : kd.translations.keys) {
        track.translation.push_back({k.time, glm::vec3(k.value.x, k.value.y, k.value.z)});
        clip_duration = std::max(clip_duration, k.time);
    }
    for (auto& k : kd.quaternion_keys) {
        track.rotation.push_back({k.time, glm::quat(k.value.w, k.value.x, k.value.y, k.value.z)});
        clip_duration = std::max(clip_duration, k.time);
    }
    for (auto& k : kd.scales.keys) {
        track.scale.push_back({k.time, k.value});
        clip_duration = std::max(clip_duration, k.time);
    }
}

void apply_vis_data(AnimationClip::NodeTrack& track,
                    const nif::NiVisData& vd,
                    float& clip_duration) {
    for (auto& k : vd.keys) {
        track.visibility.push_back({k.time, k.visible != 0});
        clip_duration = std::max(clip_duration, k.time);
    }
}

void apply_float_data(AnimationClip::NodeTrack& track,
                      const nif::NiFloatData& fd,
                      float& clip_duration) {
    for (auto& k : fd.keys) {
        track.floats.push_back({k.time, k.value});
        clip_duration = std::max(clip_duration, k.time);
    }
}

}  // namespace

std::vector<AnimationClip> build_animations(const nif::File& f) {
    // Group tracks by target node name into a single clip per node.
    std::unordered_map<std::string, AnimationClip::NodeTrack> tracks_by_target;
    float clip_duration = 0.0f;

    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        if (auto* kc = std::get_if<nif::NiKeyframeController>(&f.blocks[i])) {
            auto* target = find_controller_target(f, i);
            if (!target) continue;
            auto& track = tracks_by_target[target->av.obj.name];
            track.target_node_name = target->av.obj.name;
            if (auto* kd = data_at<nif::NiKeyframeData>(f, kc->data_link))
                apply_keyframe_data(track, *kd, clip_duration);
        } else if (auto* vc = std::get_if<nif::NiVisController>(&f.blocks[i])) {
            auto* target = find_controller_target(f, i);
            if (!target) continue;
            auto& track = tracks_by_target[target->av.obj.name];
            track.target_node_name = target->av.obj.name;
            if (auto* vd = data_at<nif::NiVisData>(f, vc->data_link))
                apply_vis_data(track, *vd, clip_duration);
        } else if (auto* rc = std::get_if<nif::NiRollController>(&f.blocks[i])) {
            auto* target = find_controller_target(f, i);
            if (!target) continue;
            auto& track = tracks_by_target[target->av.obj.name];
            track.target_node_name = target->av.obj.name;
            if (auto* fd = data_at<nif::NiFloatData>(f, rc->data_link))
                apply_float_data(track, *fd, clip_duration);
        }
    }

    if (tracks_by_target.empty()) return {};

    AnimationClip clip;
    clip.name = f.source.stem().string();
    clip.duration_seconds = clip_duration;
    for (auto& [_, track] : tracks_by_target) clip.tracks.push_back(std::move(track));
    return {std::move(clip)};
}

}  // namespace assets::detail
```

- [ ] **Step 4: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/animation_build.cc
    src/gl_handle.cc
    src/material_build.cc
    src/mesh_build.cc
    src/path_resolver.cc
    src/skeleton_build.cc
    src/texture_decode.cc
)
```

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: 2 new `AnimationBuild.*` tests PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): build AnimationClip from NiKeyframeController/Vis/Roll chains"
```

---

### Task 15: GL test fixture (offscreen GLFW context)

**Files:**
- Create: `native/tests/assets/gpu/gl_fixture.h`
- Create: `native/tests/assets/gpu/gl_fixture.cc`
- Create: `native/tests/assets/gpu/fixture_smoke_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: gl_fixture.h**

```cpp
// native/tests/assets/gpu/gl_fixture.h
#pragma once
#include <gtest/gtest.h>

namespace assets_test {

/// Test fixture providing a hidden, offscreen GL 3.3 core context.
/// SkipsTest with a clear message if context creation fails (e.g. no display).
/// One context per process — GTest creates one fixture instance per test, but
/// glfwInit/glfwTerminate are reference-counted across the whole process.
class GLContext : public ::testing::Test {
public:
    static bool Available();    // probe at startup; cached after first call
protected:
    void SetUp() override;
    void TearDown() override;
};

}  // namespace assets_test
```

- [ ] **Step 2: gl_fixture.cc**

```cpp
// native/tests/assets/gpu/gl_fixture.cc
#include "gl_fixture.h"

#include <glad/glad.h>
#include <GLFW/glfw3.h>

#include <atomic>
#include <mutex>

namespace assets_test {

namespace {
std::mutex g_mutex;
GLFWwindow* g_window = nullptr;
std::atomic<int>  g_refcount{0};
std::atomic<bool> g_probed{false};
std::atomic<bool> g_available{false};
std::atomic<bool> g_glad_loaded{false};

void create_window_locked() {
    glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 3);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 3);
    glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
#ifdef __APPLE__
    glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, GLFW_TRUE);
#endif
    g_window = glfwCreateWindow(1, 1, "assets_tests offscreen", nullptr, nullptr);
}

}  // namespace

bool GLContext::Available() {
    if (g_probed.load()) return g_available.load();
    std::lock_guard<std::mutex> lock(g_mutex);
    if (g_probed.load()) return g_available.load();

    if (!glfwInit()) { g_probed = true; return false; }
    create_window_locked();
    if (!g_window) { glfwTerminate(); g_probed = true; return false; }

    glfwMakeContextCurrent(g_window);
    if (!gladLoadGLLoader((GLADloadproc)glfwGetProcAddress)) {
        glfwDestroyWindow(g_window); g_window = nullptr;
        glfwTerminate();
        g_probed = true;
        return false;
    }
    g_glad_loaded = true;
    glfwMakeContextCurrent(nullptr);

    g_probed = true;
    g_available = true;
    return true;
}

void GLContext::SetUp() {
    if (!Available()) GTEST_SKIP() << "no GL context available (headless?)";
    std::lock_guard<std::mutex> lock(g_mutex);
    glfwMakeContextCurrent(g_window);
    g_refcount.fetch_add(1);
}

void GLContext::TearDown() {
    std::lock_guard<std::mutex> lock(g_mutex);
    glfwMakeContextCurrent(nullptr);
    g_refcount.fetch_sub(1);
    // We deliberately keep the window + GLFW alive across tests in the
    // process — re-creating the context per-test makes GLAD reload and
    // wastes time. Cleanup happens at process exit.
}

}  // namespace assets_test
```

- [ ] **Step 3: fixture smoke test**

```cpp
// native/tests/assets/gpu/fixture_smoke_test.cc
#include <gtest/gtest.h>
#include <glad/glad.h>
#include "gl_fixture.h"

class GlFixtureSmoke : public assets_test::GLContext {};

TEST_F(GlFixtureSmoke, GlGetStringReturnsRenderer) {
    auto* renderer = (const char*)glGetString(GL_RENDERER);
    ASSERT_NE(renderer, nullptr);
    SUCCEED() << "GL_RENDERER = " << renderer;
}

TEST_F(GlFixtureSmoke, NoErrorAtStartup) {
    EXPECT_EQ(glGetError(), GL_NO_ERROR);
}
```

- [ ] **Step 4: Wire into CMake**

```cmake
# native/tests/assets/CMakeLists.txt
add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/material_build_test.cc
    cpu/mesh_build_test.cc
    cpu/path_resolver_test.cc
    cpu/raw_image_decode_test.cc
    cpu/skeleton_build_test.cc
    cpu/animation_build_test.cc
    cpu/texture_decode_test.cc
    gpu/gl_fixture.cc
    gpu/fixture_smoke_test.cc
)
target_include_directories(assets_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/native/src/assets/src
    ${CMAKE_CURRENT_SOURCE_DIR}/gpu
)
target_link_libraries(assets_tests PRIVATE assets gtest gtest_main glfw)
add_test(NAME assets_tests COMMAND assets_tests)
```

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: `GlFixtureSmoke.*` either PASS (display available) or SKIP (CI-style headless). Either is acceptable.

- [ ] **Step 6: Commit**

```bash
git add native/tests/assets/
git commit -m "test(assets): offscreen GLFW fixture for GPU tests"
```

---

### Task 16: Texture upload (Image → Texture, GL)

**Files:**
- Create: `native/src/assets/src/texture_upload.cc`
- Create: `native/tests/assets/gpu/texture_upload_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: Implement Texture move ops + dtor + upload**

```cpp
// native/src/assets/src/texture_upload.cc
#include <assets/texture.h>
#include "gl_handle.h"

#include <utility>

namespace assets {

Texture::Texture(GLuint id, std::uint32_t w, std::uint32_t h, bool mipmaps) noexcept
    : id_(id), width_(w), height_(h), mipmaps_(mipmaps) {}

Texture::Texture(Texture&& o) noexcept
    : id_(std::exchange(o.id_, 0))
    , width_(std::exchange(o.width_, 0))
    , height_(std::exchange(o.height_, 0))
    , mipmaps_(std::exchange(o.mipmaps_, false)) {}

Texture& Texture::operator=(Texture&& o) noexcept {
    if (this != &o) {
        if (id_) glDeleteTextures(1, &id_);
        id_ = std::exchange(o.id_, 0);
        width_ = std::exchange(o.width_, 0);
        height_ = std::exchange(o.height_, 0);
        mipmaps_ = std::exchange(o.mipmaps_, false);
    }
    return *this;
}

Texture::~Texture() {
    if (id_) glDeleteTextures(1, &id_);
}

namespace {

GLenum gl_format_internal(Image::Format f) {
    switch (f) {
        case Image::Format::RGBA8: return GL_RGBA8;
        case Image::Format::RGB8:  return GL_RGB8;
        case Image::Format::R8:    return GL_R8;
    }
    return GL_RGBA8;
}
GLenum gl_format(Image::Format f) {
    switch (f) {
        case Image::Format::RGBA8: return GL_RGBA;
        case Image::Format::RGB8:  return GL_RGB;
        case Image::Format::R8:    return GL_RED;
    }
    return GL_RGBA;
}

}  // namespace

Texture upload_image(const Image& image, bool generate_mipmaps) {
    detail::TextureHandle handle;
    GLuint id = 0;
    glGenTextures(1, &id);
    handle = detail::TextureHandle(id);
    glBindTexture(GL_TEXTURE_2D, id);

    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexImage2D(
        GL_TEXTURE_2D, /*level=*/0,
        gl_format_internal(image.format),
        static_cast<GLsizei>(image.width),
        static_cast<GLsizei>(image.height),
        /*border=*/0,
        gl_format(image.format),
        GL_UNSIGNED_BYTE,
        image.pixels.data());

    bool mipmaps = generate_mipmaps && image.width > 4 && image.height > 4;
    if (mipmaps) {
        glGenerateMipmap(GL_TEXTURE_2D);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR);
    } else {
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
    }
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT);
    glBindTexture(GL_TEXTURE_2D, 0);

    return Texture(handle.release(), image.width, image.height, mipmaps);
}

}  // namespace assets
```

- [ ] **Step 2: Write the GPU test**

```cpp
// native/tests/assets/gpu/texture_upload_test.cc
#include <gtest/gtest.h>
#include <assets/texture.h>
#include "gl_fixture.h"
#include <glad/glad.h>

class TextureUploadTest : public assets_test::GLContext {};

TEST_F(TextureUploadTest, UploadsRgba8Texture) {
    assets::Image img;
    img.width = 8;
    img.height = 8;
    img.format = assets::Image::Format::RGBA8;
    img.pixels.assign(8 * 8 * 4, 0xCC);

    auto tex = assets::upload_image(img, /*generate_mipmaps=*/true);
    EXPECT_NE(tex.id(), 0u);
    EXPECT_TRUE(glIsTexture(tex.id()));
    EXPECT_EQ(tex.width(), 8u);
    EXPECT_EQ(tex.height(), 8u);
    EXPECT_TRUE(tex.has_mipmaps());

    GLint w = 0;
    glBindTexture(GL_TEXTURE_2D, tex.id());
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &w);
    EXPECT_EQ(w, 8);
    glBindTexture(GL_TEXTURE_2D, 0);
}

TEST_F(TextureUploadTest, MovedFromTextureIsZero) {
    assets::Image img;
    img.width = 4;
    img.height = 4;
    img.format = assets::Image::Format::RGBA8;
    img.pixels.assign(64, 0);

    auto a = assets::upload_image(img, false);
    auto b = std::move(a);
    EXPECT_EQ(a.id(), 0u);
    EXPECT_NE(b.id(), 0u);
}
```

- [ ] **Step 3: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/animation_build.cc
    src/gl_handle.cc
    src/material_build.cc
    src/mesh_build.cc
    src/path_resolver.cc
    src/skeleton_build.cc
    src/texture_decode.cc
    src/texture_upload.cc
)
```

```cmake
# native/tests/assets/CMakeLists.txt — add gpu/texture_upload_test.cc
```

- [ ] **Step 4: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: PASS or SKIP depending on context availability.

- [ ] **Step 5: Commit**

```bash
git add native/src/assets/src/texture_upload.cc native/src/assets/CMakeLists.txt native/tests/assets/
git commit -m "feat(assets): upload Image to GL texture with mipmaps + linear filter"
```

---

### Task 17: Mesh upload (MeshCpu → Mesh, GL)

**Files:**
- Create: `native/src/assets/src/mesh_upload.cc`
- Create: `native/src/assets/src/mesh_upload.h`
- Create: `native/tests/assets/gpu/mesh_upload_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: mesh_upload.h**

```cpp
// native/src/assets/src/mesh_upload.h
#pragma once
#include <assets/mesh.h>

namespace assets::detail {

/// Upload a MeshCpu to GL: VBO + EBO + VAO with attribute pointers
/// matching MeshCpu::Vertex's fixed layout.
///
/// Vertex layout (interleaved, all attributes always present):
///   loc 0: vec3  position        (offsetof = 0)
///   loc 1: vec3  normal          (offsetof = 12)
///   loc 2: vec2  uv              (offsetof = 24)
///   loc 3: vec4 ub  color        (offsetof = 32, normalized)
///   loc 4: ivec4 ub bone_indices (offsetof = 36, integer attribute)
///   loc 5: vec4 ub bone_weights  (offsetof = 40, normalized)
/// stride: sizeof(MeshCpu::Vertex)
Mesh upload_mesh(const MeshCpu& cpu);

}  // namespace assets::detail
```

- [ ] **Step 2: Implement Mesh move ops + dtor + upload**

```cpp
// native/src/assets/src/mesh_upload.cc
#include <assets/mesh.h>
#include "mesh_upload.h"
#include "gl_handle.h"

#include <utility>

namespace assets {

Mesh::Mesh(GLuint vao, GLuint vbo, GLuint ebo,
           std::uint32_t index_count, int material_index, int node_index) noexcept
    : vao_(vao), vbo_(vbo), ebo_(ebo)
    , index_count_(index_count)
    , material_index_(material_index), node_index_(node_index) {}

Mesh::Mesh(Mesh&& o) noexcept
    : vao_(std::exchange(o.vao_, 0))
    , vbo_(std::exchange(o.vbo_, 0))
    , ebo_(std::exchange(o.ebo_, 0))
    , index_count_(std::exchange(o.index_count_, 0))
    , material_index_(std::exchange(o.material_index_, -1))
    , node_index_(std::exchange(o.node_index_, -1))
    , cpu_data_(std::move(o.cpu_data_))
    , lod_chain_(std::move(o.lod_chain_)) {}

Mesh& Mesh::operator=(Mesh&& o) noexcept {
    if (this != &o) {
        if (vao_) glDeleteVertexArrays(1, &vao_);
        if (vbo_) glDeleteBuffers(1, &vbo_);
        if (ebo_) glDeleteBuffers(1, &ebo_);
        vao_ = std::exchange(o.vao_, 0);
        vbo_ = std::exchange(o.vbo_, 0);
        ebo_ = std::exchange(o.ebo_, 0);
        index_count_ = std::exchange(o.index_count_, 0);
        material_index_ = std::exchange(o.material_index_, -1);
        node_index_ = std::exchange(o.node_index_, -1);
        cpu_data_ = std::move(o.cpu_data_);
        lod_chain_ = std::move(o.lod_chain_);
    }
    return *this;
}

Mesh::~Mesh() {
    if (vao_) glDeleteVertexArrays(1, &vao_);
    if (vbo_) glDeleteBuffers(1, &vbo_);
    if (ebo_) glDeleteBuffers(1, &ebo_);
}

}  // namespace assets

namespace assets::detail {

Mesh upload_mesh(const MeshCpu& cpu) {
    GLuint vao = 0, vbo = 0, ebo = 0;
    glGenVertexArrays(1, &vao);
    glGenBuffers(1, &vbo);
    glGenBuffers(1, &ebo);
    VertexArrayHandle vao_h(vao);
    BufferHandle vbo_h(vbo), ebo_h(ebo);

    glBindVertexArray(vao);
    glBindBuffer(GL_ARRAY_BUFFER, vbo);
    glBufferData(
        GL_ARRAY_BUFFER,
        static_cast<GLsizeiptr>(cpu.vertices.size() * sizeof(MeshCpu::Vertex)),
        cpu.vertices.data(), GL_STATIC_DRAW);

    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ebo);
    glBufferData(
        GL_ELEMENT_ARRAY_BUFFER,
        static_cast<GLsizeiptr>(cpu.indices.size() * sizeof(std::uint32_t)),
        cpu.indices.data(), GL_STATIC_DRAW);

    using V = MeshCpu::Vertex;
    const GLsizei stride = sizeof(V);

    glEnableVertexAttribArray(0);
    glVertexAttribPointer(0, 3, GL_FLOAT, GL_FALSE, stride, (void*)offsetof(V, position));
    glEnableVertexAttribArray(1);
    glVertexAttribPointer(1, 3, GL_FLOAT, GL_FALSE, stride, (void*)offsetof(V, normal));
    glEnableVertexAttribArray(2);
    glVertexAttribPointer(2, 2, GL_FLOAT, GL_FALSE, stride, (void*)offsetof(V, uv));
    glEnableVertexAttribArray(3);
    glVertexAttribPointer(3, 4, GL_UNSIGNED_BYTE, GL_TRUE,  stride, (void*)offsetof(V, color));
    glEnableVertexAttribArray(4);
    glVertexAttribIPointer(4, 4, GL_UNSIGNED_BYTE, stride, (void*)offsetof(V, bone_indices));
    glEnableVertexAttribArray(5);
    glVertexAttribPointer(5, 4, GL_UNSIGNED_BYTE, GL_TRUE,  stride, (void*)offsetof(V, bone_weights));

    glBindVertexArray(0);
    glBindBuffer(GL_ARRAY_BUFFER, 0);
    glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, 0);

    return Mesh(
        vao_h.release(), vbo_h.release(), ebo_h.release(),
        static_cast<std::uint32_t>(cpu.indices.size()),
        cpu.material_index, cpu.node_index);
}

}  // namespace assets::detail
```

- [ ] **Step 3: GPU test**

```cpp
// native/tests/assets/gpu/mesh_upload_test.cc
#include <gtest/gtest.h>
#include "mesh_upload.h"
#include "gl_fixture.h"
#include <glad/glad.h>

class MeshUploadTest : public assets_test::GLContext {};

TEST_F(MeshUploadTest, UploadsTriangle) {
    assets::MeshCpu cpu;
    cpu.vertices.resize(3);
    cpu.vertices[0].position = {0.0f, 0.0f, 0.0f};
    cpu.vertices[1].position = {1.0f, 0.0f, 0.0f};
    cpu.vertices[2].position = {0.0f, 1.0f, 0.0f};
    cpu.indices = {0, 1, 2};
    cpu.material_index = 5;
    cpu.node_index = 11;

    auto mesh = assets::detail::upload_mesh(cpu);
    EXPECT_NE(mesh.vao(), 0u);
    EXPECT_NE(mesh.vbo(), 0u);
    EXPECT_NE(mesh.ebo(), 0u);
    EXPECT_EQ(mesh.index_count(), 3u);
    EXPECT_EQ(mesh.material_index(), 5);
    EXPECT_EQ(mesh.node_index(), 11);
    EXPECT_TRUE(glIsVertexArray(mesh.vao()));
    EXPECT_TRUE(glIsBuffer(mesh.vbo()));
    EXPECT_TRUE(glIsBuffer(mesh.ebo()));
}
```

- [ ] **Step 4: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/animation_build.cc
    src/gl_handle.cc
    src/material_build.cc
    src/mesh_build.cc
    src/mesh_upload.cc
    src/path_resolver.cc
    src/skeleton_build.cc
    src/texture_decode.cc
    src/texture_upload.cc
)
```

```cmake
# native/tests/assets/CMakeLists.txt — add gpu/mesh_upload_test.cc
```

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: `MeshUploadTest.*` PASS (or SKIP if no context).

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): upload MeshCpu to GL VAO/VBO/EBO with fixed vertex layout"
```

---

### Task 18: Model build orchestrator

**Files:**
- Create: `native/src/assets/src/model_build.h`
- Create: `native/src/assets/src/model_build.cc`
- Create: `native/tests/assets/cpu/model_build_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: model_build.h**

```cpp
// native/src/assets/src/model_build.h
#pragma once
#include <assets/model.h>
#include <assets/path_resolver.h>
#include <nif/file.h>

#include <filesystem>
#include <functional>

namespace assets::detail {

using TextureUploaderFn = std::function<Texture(const Image&, bool)>;
using MeshUploaderFn    = std::function<Mesh(MeshCpu)>;

struct ModelBuildContext {
    PathResolver*           resolver = nullptr;
    std::filesystem::path   texture_search_path;
    TextureUploaderFn       texture_uploader;     // empty → call upload_image
    MeshUploaderFn          mesh_uploader;        // empty → call upload_mesh
    bool                    keep_cpu_data = false;
};

class ModelBuildError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

Model build_model(const nif::File& f, const ModelBuildContext& ctx);

}  // namespace assets::detail
```

- [ ] **Step 2: Write the failing test using stub uploaders**

```cpp
// native/tests/assets/cpu/model_build_test.cc
#include <gtest/gtest.h>
#include "model_build.h"
#include <nif/block.h>

#include <filesystem>
#include <fstream>
#include <unistd.h>

namespace fs = std::filesystem;

namespace {

assets::Texture stub_texture(const assets::Image&, bool) {
    return assets::Texture(/*id=*/1234, 1, 1, false);
}
assets::Mesh stub_mesh(assets::MeshCpu cpu) {
    return assets::Mesh(/*vao=*/1, /*vbo=*/2, /*ebo=*/3,
                        static_cast<std::uint32_t>(cpu.indices.size()),
                        cpu.material_index, cpu.node_index);
}

class ModelBuildTest : public ::testing::Test {
protected:
    fs::path tmp_dir;
    assets::PathResolver resolver;

    void SetUp() override {
        auto base = fs::temp_directory_path() / "assets-mb";
        for (int i = 0; ; ++i) {
            auto candidate = base;
            candidate += "-" + std::to_string(::getpid()) + "-" + std::to_string(i);
            if (!fs::exists(candidate)) { tmp_dir = candidate; break; }
        }
        fs::create_directories(tmp_dir);
    }
    void TearDown() override {
        std::error_code ec;
        fs::remove_all(tmp_dir, ec);
    }
    nif::File trivial_file_with_one_trishape() {
        nif::File f;
        // Block 0: root NiNode → child block 1
        nif::NiNode root;
        root.av.obj.name = "Root";
        root.child_links = {1};
        f.blocks.push_back(root);
        // Block 1: NiTriShape → data block 2
        nif::NiTriShape tri;
        tri.av.obj.name = "Saucer";
        tri.data_link = 2;
        f.blocks.push_back(tri);
        // Block 2: NiTriShapeData with one triangle
        nif::NiTriShapeData d;
        d.num_vertices = 3;
        d.has_vertices = true;
        d.vertices = {{0,0,0},{1,0,0},{0,1,0}};
        d.has_uv = true;
        d.uv_sets.push_back({{0,0},{1,0},{0,1}});
        d.num_triangles = 1;
        d.triangles.push_back({0,1,2});
        f.blocks.push_back(d);
        return f;
    }
};

}  // namespace

TEST_F(ModelBuildTest, EmptyNifThrowsModelBuildError) {
    nif::File f;
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_path = tmp_dir;
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;

    EXPECT_THROW(assets::detail::build_model(f, ctx), assets::detail::ModelBuildError);
}

TEST_F(ModelBuildTest, TrivialFileProducesModel) {
    auto f = trivial_file_with_one_trishape();
    assets::detail::ModelBuildContext ctx;
    ctx.resolver = &resolver;
    ctx.texture_search_path = tmp_dir;
    ctx.texture_uploader = stub_texture;
    ctx.mesh_uploader = stub_mesh;

    auto model = assets::detail::build_model(f, ctx);
    EXPECT_FALSE(model.nodes.empty());
    EXPECT_EQ(model.meshes.size(), 1u);
    EXPECT_EQ(model.materials.size(), 1u);
    EXPECT_EQ(model.textures.size(), 0u);  // no NiImage in this trivial file
    EXPECT_EQ(model.skeleton.bones.size(), 0u);
    EXPECT_EQ(model.animations.size(), 0u);
    EXPECT_EQ(model.meshes[0].material_index(), 0);
}
```

- [ ] **Step 3: Implement build_model orchestrator**

```cpp
// native/src/assets/src/model_build.cc
#include "model_build.h"
#include "animation_build.h"
#include "material_build.h"
#include "mesh_build.h"
#include "mesh_upload.h"
#include "skeleton_build.h"

#include <fstream>
#include <unordered_map>

namespace fs = std::filesystem;

namespace assets::detail {

namespace {

std::vector<std::uint8_t> read_file(const fs::path& p) {
    std::ifstream in(p, std::ios::binary);
    if (!in) throw TextureNotFound(p.filename().string(), p.parent_path());
    in.seekg(0, std::ios::end);
    const auto size = static_cast<std::size_t>(in.tellg());
    in.seekg(0, std::ios::beg);
    std::vector<std::uint8_t> bytes(size);
    in.read(reinterpret_cast<char*>(bytes.data()), size);
    return bytes;
}

/// First pass: load every NiImage into the textures vector.
/// Returns block-index → Model::textures index.
std::unordered_map<std::uint32_t, int> load_all_textures(
    const nif::File& f,
    Model& model,
    const ModelBuildContext& ctx)
{
    std::unordered_map<std::uint32_t, int> map;
    auto upload = ctx.texture_uploader
        ? ctx.texture_uploader
        : TextureUploaderFn(&assets::upload_image);

    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* img = std::get_if<nif::NiImage>(&f.blocks[i]);
        if (!img) continue;
        Image decoded;
        if (img->use_external != 0) {
            auto path = ctx.resolver->resolve(img->file_name, ctx.texture_search_path);
            auto bytes = read_file(path);
            decoded = decode_tga(bytes);
        } else {
            const auto* raw = (img->image_data_link < f.blocks.size())
                ? std::get_if<nif::NiRawImageData>(&f.blocks[img->image_data_link])
                : nullptr;
            if (!raw) throw ModelBuildError(
                "NiImage " + std::to_string(i) + ": missing NiRawImageData");
            decoded = decode_raw_image(*raw);
        }
        Texture tex = upload(decoded, /*generate_mipmaps=*/true);
        map[i] = static_cast<int>(model.textures.size());
        model.textures.push_back(std::move(tex));
    }
    return map;
}

/// Walk the scene-graph blocks, output flat Node array; track NIF-block-index
/// → Node-index. Meshes get attached to their parent node.
struct NodeBuildResult {
    std::vector<Node> nodes;
    std::unordered_map<std::uint32_t, int> nif_block_to_node_index;
};

NodeBuildResult build_nodes(const nif::File& f) {
    NodeBuildResult r;
    // Find candidate roots: NiNodes that aren't anyone's child.
    std::unordered_map<std::uint32_t, int> child_count;
    for (auto& b : f.blocks)
        if (auto* n = std::get_if<nif::NiNode>(&b))
            for (auto c : n->child_links) child_count[c]++;

    std::function<void(std::uint32_t, int)> walk =
    [&](std::uint32_t nif_idx, int parent) {
        if (nif_idx >= f.blocks.size()) return;
        const auto* node = std::get_if<nif::NiNode>(&f.blocks[nif_idx]);
        if (!node) return;
        Node out;
        out.name = node->av.obj.name;
        out.parent_index = parent;
        // local_transform from av — same conversion as skeleton_build.
        glm::mat4 m(1.0f);
        m[0] = {node->av.rotation.m[0], node->av.rotation.m[3], node->av.rotation.m[6], 0};
        m[1] = {node->av.rotation.m[1], node->av.rotation.m[4], node->av.rotation.m[7], 0};
        m[2] = {node->av.rotation.m[2], node->av.rotation.m[5], node->av.rotation.m[8], 0};
        m[3] = {node->av.translation.x, node->av.translation.y, node->av.translation.z, 1};
        if (node->av.scale != 1.0f) { m[0] *= node->av.scale; m[1] *= node->av.scale; m[2] *= node->av.scale; }
        out.local_transform = m;
        int self = static_cast<int>(r.nodes.size());
        r.nodes.push_back(std::move(out));
        r.nif_block_to_node_index[nif_idx] = self;
        if (parent >= 0) r.nodes[parent].children.push_back(self);

        for (auto c : node->child_links) walk(c, self);
    };

    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* n = std::get_if<nif::NiNode>(&f.blocks[i]);
        if (!n) continue;
        if (child_count[i] == 0) {
            walk(i, /*parent=*/-1);
            break;  // first root only — BC files have one
        }
    }
    return r;
}

/// Resolve a NiTriShape's material from its property_links.
MaterialInputs gather_material_inputs(
    const nif::File& f,
    const nif::NiTriShape& shape,
    const std::unordered_map<std::uint32_t, int>& image_to_texture)
{
    MaterialInputs in;
    in.image_to_texture = &image_to_texture;
    for (auto link : shape.av.property_links) {
        if (link >= f.blocks.size()) continue;
        const auto& b = f.blocks[link];
        if (auto* p = std::get_if<nif::NiMaterialProperty>(&b))      in.material      = p;
        else if (auto* p = std::get_if<nif::NiTexturingProperty>(&b))    in.texturing     = p;
        else if (auto* p = std::get_if<nif::NiMultiTextureProperty>(&b)) in.multi_texture = p;
        else if (auto* p = std::get_if<nif::NiAlphaProperty>(&b))        in.alpha         = p;
        else if (auto* p = std::get_if<nif::NiZBufferProperty>(&b))      in.zbuffer       = p;
        else if (auto* p = std::get_if<nif::NiVertexColorProperty>(&b))  in.vertex_color  = p;
    }
    return in;
}

}  // namespace

Model build_model(const nif::File& f, const ModelBuildContext& ctx) {
    if (!ctx.resolver) throw ModelBuildError("ModelBuildContext::resolver is null");

    Model model;
    model.source = f.source;

    // 1. Skeleton (may be empty).
    auto skel = build_skeleton(f);
    model.skeleton = std::move(skel.skeleton);

    // 2. Textures.
    auto image_to_texture = load_all_textures(f, model, ctx);

    // 3. Nodes.
    auto nodes = build_nodes(f);
    model.nodes = std::move(nodes.nodes);
    model.root_node = model.nodes.empty() ? 0 : 0;

    if (model.nodes.empty()) {
        throw ModelBuildError("no NiNode root in NIF file");
    }

    // 4. Meshes + materials, in lock-step.
    auto mesh_upload = ctx.mesh_uploader
        ? ctx.mesh_uploader
        : MeshUploaderFn([](MeshCpu cpu) { return upload_mesh(cpu); });

    bool any_trishape = false;
    for (std::uint32_t i = 0; i < f.blocks.size(); ++i) {
        const auto* shape = std::get_if<nif::NiTriShape>(&f.blocks[i]);
        if (!shape) continue;
        any_trishape = true;
        const auto* data = (shape->data_link < f.blocks.size())
            ? std::get_if<nif::NiTriShapeData>(&f.blocks[shape->data_link])
            : nullptr;
        if (!data) continue;

        // Material: assemble inputs, build, append; remember the index.
        auto mat_inputs = gather_material_inputs(f, *shape, image_to_texture);
        Material mat = build_material(mat_inputs);
        int mat_index = static_cast<int>(model.materials.size());
        model.materials.push_back(std::move(mat));

        // Node index — find the parent node of this NiTriShape. NIFs store
        // the trishape under a NiNode's child_links, so look it up.
        int node_index = -1;
        for (auto& [nif_idx, node_idx] : nodes.nif_block_to_node_index) {
            const auto* n = std::get_if<nif::NiNode>(&f.blocks[nif_idx]);
            if (!n) continue;
            for (auto c : n->child_links) if (c == i) { node_index = node_idx; break; }
            if (node_index != -1) break;
        }

        MeshCpu cpu = build_mesh_cpu(*shape, *data, mat_index, node_index);
        if (node_index >= 0) model.nodes[node_index].meshes.push_back(
            static_cast<int>(model.meshes.size()));
        Mesh mesh = mesh_upload(std::move(cpu));
        if (ctx.keep_cpu_data) {
            // re-build for retention; cheaper than copying through the upload path
            mesh.set_cpu_data(build_mesh_cpu(*shape, *data, mat_index, node_index));
        }
        model.meshes.push_back(std::move(mesh));
    }
    if (!any_trishape) {
        throw ModelBuildError("no NiTriShape in NIF file");
    }

    // 5. Animations.
    model.animations = build_animations(f);

    return model;
}

}  // namespace assets::detail
```

- [ ] **Step 4: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/animation_build.cc
    src/gl_handle.cc
    src/material_build.cc
    src/mesh_build.cc
    src/mesh_upload.cc
    src/model_build.cc
    src/path_resolver.cc
    src/skeleton_build.cc
    src/texture_decode.cc
    src/texture_upload.cc
)
```

```cmake
# native/tests/assets/CMakeLists.txt — add cpu/model_build_test.cc
```

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: 2 new `ModelBuildTest.*` tests PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): build_model orchestrator wires NIF → Model end-to-end"
```

---

### Task 19: AssetCache (load + evict + refcount)

**Files:**
- Create: `native/src/assets/include/assets/cache.h`
- Create: `native/src/assets/src/cache.cc`
- Create: `native/tests/assets/cpu/cache_test.cc`
- Modify: `native/src/assets/CMakeLists.txt`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: cache.h**

```cpp
// native/src/assets/include/assets/cache.h
#pragma once
#include <assets/asset.h>
#include <assets/mesh.h>
#include <assets/model.h>
#include <assets/texture.h>

#include <filesystem>
#include <functional>
#include <memory>
#include <stdexcept>

namespace assets {

class AssetError : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};

class AssetCache {
public:
    struct Config {
        bool keep_cpu_data = false;
        std::function<Texture(const Image&, bool)> texture_uploader;
        std::function<Mesh(MeshCpu)>               mesh_uploader;
    };

    explicit AssetCache(Config = {});
    ~AssetCache();
    AssetCache(const AssetCache&) = delete;
    AssetCache& operator=(const AssetCache&) = delete;

    /// Synchronous load. Identical (nif_path, texture_search_path) returns the
    /// same handle. Different texture_search_path with the same nif_path:
    /// throws AssetError.
    ModelHandle load(const std::filesystem::path& nif_path,
                     const std::filesystem::path& texture_search_path);

    void evict(const std::filesystem::path& nif_path);
    void evict_unused();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace assets
```

- [ ] **Step 2: Write the failing test (uses stub uploaders)**

```cpp
// native/tests/assets/cpu/cache_test.cc
#include <gtest/gtest.h>
#include <assets/cache.h>
#include <nif/file.h>

#include <filesystem>
#include <fstream>

namespace fs = std::filesystem;

// We need a real on-disk NIF for the cache to load. The cache calls
// nif::load(path), which expects a real file. Use the existing four BC
// sample files and SKIP if game/ is absent.

namespace {

bool game_data_present() {
    return fs::exists("game/data/Models/Ships/Galaxy/Galaxy.nif");
}

assets::AssetCache::Config stub_config() {
    assets::AssetCache::Config cfg;
    cfg.texture_uploader = [](const assets::Image&, bool) {
        return assets::Texture(/*id=*/42, 1, 1, false);
    };
    cfg.mesh_uploader = [](assets::MeshCpu cpu) {
        return assets::Mesh(/*vao=*/1, /*vbo=*/2, /*ebo=*/3,
                            static_cast<std::uint32_t>(cpu.indices.size()),
                            cpu.material_index, cpu.node_index);
    };
    return cfg;
}

}  // namespace

TEST(AssetCacheTest, LoadSamePathReturnsSameHandle) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache(stub_config());
    auto a = cache.load(
        "game/data/Models/Ships/Galaxy/Galaxy.nif",
        "game/data/Models/SharedTextures/FedShips/High");
    auto b = cache.load(
        "game/data/Models/Ships/Galaxy/Galaxy.nif",
        "game/data/Models/SharedTextures/FedShips/High");
    EXPECT_EQ(a.get(), b.get());
}

TEST(AssetCacheTest, DifferentSearchPathThrows) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache(stub_config());
    cache.load(
        "game/data/Models/Ships/Galaxy/Galaxy.nif",
        "game/data/Models/SharedTextures/FedShips/High");
    EXPECT_THROW(
        cache.load(
            "game/data/Models/Ships/Galaxy/Galaxy.nif",
            "game/data/Models/SharedTextures/FedShips/Medium"),
        assets::AssetError);
}

TEST(AssetCacheTest, EvictDropsCachePin) {
    if (!game_data_present()) GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache(stub_config());
    auto handle = cache.load(
        "game/data/Models/Ships/Galaxy/Galaxy.nif",
        "game/data/Models/SharedTextures/FedShips/High");
    cache.evict("game/data/Models/Ships/Galaxy/Galaxy.nif");
    // Outstanding handle still keeps the model alive.
    EXPECT_TRUE(handle != nullptr);
}
```

- [ ] **Step 3: Implement the cache**

```cpp
// native/src/assets/src/cache.cc
#include <assets/cache.h>
#include "model_build.h"
#include <nif/file.h>

#include <unordered_map>

namespace fs = std::filesystem;

namespace assets {

struct AssetCache::Impl {
    Config config;
    PathResolver resolver;

    struct Entry {
        std::weak_ptr<const Model>   live;
        std::shared_ptr<const Model> pinned;
        fs::path                     search_path;
    };
    std::unordered_map<std::string, Entry> entries;
};

AssetCache::AssetCache(Config cfg) : impl_(std::make_unique<Impl>()) {
    impl_->config = std::move(cfg);
}

AssetCache::~AssetCache() {
    // GL handles in entries are released here. Caller must ensure a current
    // GL context. (Documented in the header.)
    impl_->entries.clear();
}

ModelHandle AssetCache::load(const fs::path& nif_path, const fs::path& search_path) {
    auto canon = fs::weakly_canonical(nif_path).string();
    auto it = impl_->entries.find(canon);
    if (it != impl_->entries.end()) {
        if (auto live = it->second.live.lock()) {
            if (it->second.search_path != search_path) {
                throw AssetError(
                    "asset already loaded with different texture_search_path: " + canon);
            }
            return live;
        }
    }

    auto file = nif::load(nif_path);

    detail::ModelBuildContext ctx;
    ctx.resolver = &impl_->resolver;
    ctx.texture_search_path = search_path;
    ctx.texture_uploader = impl_->config.texture_uploader;
    ctx.mesh_uploader    = impl_->config.mesh_uploader;
    ctx.keep_cpu_data    = impl_->config.keep_cpu_data;

    auto model = std::make_shared<const Model>(detail::build_model(file, ctx));

    Impl::Entry entry;
    entry.live = model;
    entry.pinned = model;
    entry.search_path = search_path;
    impl_->entries[canon] = std::move(entry);
    return model;
}

void AssetCache::evict(const fs::path& nif_path) {
    auto canon = fs::weakly_canonical(nif_path).string();
    auto it = impl_->entries.find(canon);
    if (it == impl_->entries.end()) return;
    it->second.pinned.reset();  // drop strong cache pin; handles keep it alive
}

void AssetCache::evict_unused() {
    for (auto& [_, entry] : impl_->entries) {
        if (entry.pinned && entry.pinned.use_count() == 1) entry.pinned.reset();
    }
}

}  // namespace assets
```

- [ ] **Step 4: Wire into CMake**

```cmake
# native/src/assets/CMakeLists.txt
add_library(assets STATIC
    src/animation_build.cc
    src/cache.cc
    src/gl_handle.cc
    src/material_build.cc
    src/mesh_build.cc
    src/mesh_upload.cc
    src/model_build.cc
    src/path_resolver.cc
    src/skeleton_build.cc
    src/texture_decode.cc
    src/texture_upload.cc
)
```

```cmake
# native/tests/assets/CMakeLists.txt — add cpu/cache_test.cc
```

- [ ] **Step 5: Build and run**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: `AssetCacheTest.*` either PASS (with game/) or SKIP cleanly.

- [ ] **Step 6: Commit**

```bash
git add native/src/assets/ native/tests/assets/
git commit -m "feat(assets): refcounted AssetCache keyed by NIF path"
```

---

### Task 20: End-to-end smoke test

**Files:**
- Create: `native/tests/assets/gpu/model_smoke_test.cc`
- Modify: `native/tests/assets/CMakeLists.txt`

- [ ] **Step 1: Smoke test using the real GL fixture and real BC assets**

```cpp
// native/tests/assets/gpu/model_smoke_test.cc
#include <gtest/gtest.h>
#include <assets/cache.h>
#include "gl_fixture.h"
#include <glad/glad.h>

#include <filesystem>

class ModelSmokeTest : public assets_test::GLContext {};

TEST_F(ModelSmokeTest, LoadsGalaxyEndToEnd) {
    namespace fs = std::filesystem;
    if (!fs::exists("game/data/Models/Ships/Galaxy/Galaxy.nif"))
        GTEST_SKIP() << "game/ not installed";

    assets::AssetCache cache;  // default config: real GL uploaders
    auto model = cache.load(
        "game/data/Models/Ships/Galaxy/Galaxy.nif",
        "game/data/Models/SharedTextures/FedShips/High");

    ASSERT_NE(model, nullptr);
    EXPECT_GT(model->meshes.size(), 0u);
    EXPECT_GT(model->materials.size(), 0u);
    EXPECT_GT(model->textures.size(), 0u);
    EXPECT_FALSE(model->nodes.empty());
    EXPECT_EQ(glGetError(), GL_NO_ERROR);

    for (auto& tex : model->textures) {
        EXPECT_NE(tex.id(), 0u);
        EXPECT_TRUE(glIsTexture(tex.id()));
    }
    for (auto& m : model->meshes) {
        EXPECT_NE(m.vao(), 0u);
        EXPECT_TRUE(glIsVertexArray(m.vao()));
    }
}
```

- [ ] **Step 2: Wire into CMake**

```cmake
# native/tests/assets/CMakeLists.txt — final form
add_executable(assets_tests
    cpu/sanity_test.cc
    cpu/header_compile_test.cc
    cpu/animation_build_test.cc
    cpu/cache_test.cc
    cpu/material_build_test.cc
    cpu/mesh_build_test.cc
    cpu/model_build_test.cc
    cpu/path_resolver_test.cc
    cpu/raw_image_decode_test.cc
    cpu/skeleton_build_test.cc
    cpu/texture_decode_test.cc
    gpu/gl_fixture.cc
    gpu/fixture_smoke_test.cc
    gpu/mesh_upload_test.cc
    gpu/model_smoke_test.cc
    gpu/texture_upload_test.cc
)
target_include_directories(assets_tests PRIVATE
    ${CMAKE_SOURCE_DIR}/native/src/assets/src
    ${CMAKE_CURRENT_SOURCE_DIR}/gpu
)
target_link_libraries(assets_tests PRIVATE assets gtest gtest_main glfw)
add_test(NAME assets_tests COMMAND assets_tests)
```

- [ ] **Step 3: Build, test, observe**

```bash
cmake --build build -j
ctest --test-dir build -R assets_tests --output-on-failure
```

Expected: All tests PASS or SKIP cleanly. The smoke test PASSes if `game/` is present and a GL context is available.

- [ ] **Step 4: Mirror deferred-work doc into the source tree**

```bash
mkdir -p native/src/assets/docs
```

```markdown
<!-- native/src/assets/docs/deferred_work.md -->
# Asset Pipeline — Deferred Work

This file mirrors the "Deferred / future work" section of
[`docs/superpowers/specs/2026-05-09-asset-pipeline-design.md`](../../../../docs/superpowers/specs/2026-05-09-asset-pipeline-design.md).

The spec is the authoritative source. Update both when items move on or off
the list.

1. LOD chain population — `Mesh::lod_chain` reserved field; meshoptimizer-driven decimation when wanted.
2. Async loading — sync v1; state-machine handle for v2.
3. Glow / specular suffix conventions — item 6 of renderer plan.
4. Med / Low LOD NIFs — pipeline ignores; App.py shim absorbs.
5. Material normalization layer (Approach C) — defer until renderer asks.
6. Mod / asset-overlay support — single search dir today.
7. CI without BC install — same problem as nif loader.
8. GL context-loss recovery — `keep_cpu_data` is the seed.
9. PNG / DDS / BC1-7 — TGA only for v1.
10. Vertex tangent slot — required for normal mapping.
11. HDR texture format (RGBA16F).
12. Phase 1 Python bindings.
13. Continuous LOD via cluster / mesh shaders.
14. Skinned animation playback — scene-graph-runtime concern.
15. Particle effects — runtime-procedural per gap_analysis.
16. NiBinaryVoxelData semantics — defer to scene-graph or physics.
17. Save/load — Phase 1 concern; pipeline rebuilds on load.
18. Streaming / virtual textures — not needed today.
```

- [ ] **Step 5: Update sub-project status index**

In `docs/architecture/sub_project_status.md`, change the asset pipeline row:

```diff
-| 2 | Asset pipeline | Approved, pending implementation | ... |
+| 2 | Asset pipeline | Implemented (v1 ship gate met YYYY-MM-DD) | ... |
```

- [ ] **Step 6: Final commit**

```bash
git add native/tests/assets/gpu/model_smoke_test.cc native/tests/assets/CMakeLists.txt \
        native/src/assets/docs/deferred_work.md docs/architecture/sub_project_status.md
git commit -m "test(assets): end-to-end Galaxy.nif smoke test + status update"
```

---

## Self-review checklist

Before declaring the plan complete, run through:

1. **Spec coverage** — every section of the spec has at least one task:
   - § Goal / non-goals: covered by Task 18 + Task 19.
   - § Success criteria #1 (cache.load returns Model): Task 19, Task 20.
   - § Success criteria #2 (Mesh/Texture/Material/Skeleton/AnimationClip populated): Tasks 11–14, 16, 17, 18, 20.
   - § Success criteria #3 (refcount + same handle): Task 19.
   - § Success criteria #4 (ctest passes on macOS + Linux): every task ends in `ctest`.
   - § Architecture / Directory layout: Tasks 1–7.
   - § Public API: Task 6 (headers), expanded in tasks that own each header.
   - § Data flow: Task 18.
   - § Path resolution: Task 8.
   - § Cache mechanics: Task 19.
   - § GL handle lifetime ordering: Task 19's `~AssetCache` calls `entries.clear()`.
   - § Error handling: covered by exceptions thrown in Tasks 8, 9, 10, 18.
   - § Test plan: Tasks 8–20 produce the named test files.

2. **No placeholders** — search confirms no "TBD" / "TODO" / "fill in details" in steps. (`(TBD search dir)` only appears in the spec, not in the plan, and is resolved by Task 19's smoke test using the FedShips/High path empirically determined from BC.)

3. **Type consistency** — across tasks:
   - `assets::Texture(GLuint, w, h, mipmaps)` constructor used consistently in Tasks 16, 17, 18, 19.
   - `assets::Mesh(GLuint vao, vbo, ebo, idx_count, mat, node)` used consistently in Tasks 17, 18, 19.
   - `MeshCpu`'s `bone_indices` is `glm::u8vec4`; mesh_upload Task 17 uses `GL_UNSIGNED_BYTE` consistently.
   - `assets::detail::MaterialInputs::image_to_texture` used in Tasks 12 + 18.
   - `assets::AssetCache::Config::texture_uploader` and `mesh_uploader` typed consistently in Task 19's `cache.h` and Task 18's `model_build.h`.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-05-09-asset-pipeline.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
