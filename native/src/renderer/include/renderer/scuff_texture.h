// native/src/renderer/include/renderer/scuff_texture.h
#pragma once

namespace renderer {

/// The collision-scuff normal map: a tiling crumpled-sheet-metal tangent-space
/// normal map (OpenGL +Y green) at <project assets>/textures/scuff_normal.tga
/// (uncompressed 24-bit; the decoder is TGA-only). opaque.frag's apply_scuffs samples it in each scuff's own slip
/// frame on texture unit 7, so every scuff is a differently placed, rotated
/// patch of the same sheet.
///
/// Lazily loaded once per GL session on first use; returns the GL texture id,
/// or 0 when the file is absent or undecodable (logged once) -- the shader
/// then draws the scuff's albedo terms with no relief rather than nothing.
unsigned int ensure_scuff_normal_texture();

/// Release the texture while its GL context is still current (host shutdown)
/// and forget the load attempt, so the next session reloads. Same contract as
/// reset_damage_decal_texture(): a stale id leaking into a fresh context binds
/// something else entirely.
void reset_scuff_normal_texture();

/// Test seam: serve `id` from ensure_scuff_normal_texture() instead of the
/// file (0 clears). The caller keeps ownership of `id`.
void set_scuff_normal_texture_override(unsigned int id);

}  // namespace renderer
