// native/src/renderer/include/renderer/cubemap_target.h
#pragma once
#include <cstdint>

namespace renderer {

/// One render-to-cubemap target: a 6-face RGBA16F color cubemap (mip-mapped),
/// a shared depth renderbuffer, and an FBO whose color attachment is rebound
/// per face. Fixed-size and window-independent — used to bake the static
/// procedural sky once per system. Modeled on HdrTarget.
class CubemapTarget {
public:
    CubemapTarget() = default;
    ~CubemapTarget();
    CubemapTarget(const CubemapTarget&) = delete;
    CubemapTarget& operator=(const CubemapTarget&) = delete;

    /// (Re)allocate to face_size x face_size per face. No-op if already that
    /// size. Returns true on a complete FBO; false on failure (caller falls
    /// back to per-frame rendering). Requires a current GL context.
    /// Same as allocate(face_size, 1).
    bool allocate(int face_size) { return allocate(face_size, 1); }

    /// (Re)allocate with `mip_levels` explicitly allocated levels (each face,
    /// each level, via glTexImage2D). For mip_levels > 1 GL_TEXTURE_MAX_LEVEL
    /// is set to mip_levels - 1 so the texture is complete with exactly those
    /// levels. mip_levels == 1 leaves MAX_LEVEL at GL's default -- the
    /// backdrop bake relies on that, since its generate_mips() builds the
    /// chain afterwards (so allocate(n) stays byte-identical to before).
    /// No-op if already that size and level count.
    bool allocate(int face_size, int mip_levels);

    /// Bind the FBO with color attachment = face `i` (0..5, matching
    /// GL_TEXTURE_CUBE_MAP_POSITIVE_X + i) at level `mip`, and set the
    /// viewport to that level's size (max(1, face_size >> mip)).
    void bind_face(int i, int mip = 0) const;

    /// Build the mip chain (call once after all 6 faces are rendered).
    void generate_mips() const;

    std::uint32_t texture() const { return cube_tex_; }
    int  face_size() const { return face_size_; }
    int  mip_levels() const { return mip_levels_; }
    bool valid() const { return fbo_ != 0; }

private:
    void destroy();
    std::uint32_t fbo_ = 0;
    std::uint32_t cube_tex_ = 0;
    std::uint32_t depth_rbo_ = 0;
    int face_size_ = 0;
    int mip_levels_ = 0;
};

}  // namespace renderer
