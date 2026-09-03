// native/src/renderer/include/renderer/starmap_pass.h
#pragma once

#include <memory>
#include <vector>

#include <glm/glm.hpp>

namespace scenegraph { struct Camera; }

namespace renderer {

class Pipeline;

/// A soft radial billboard — nebulae and star clouds. Drawn FIRST and
/// depth-test off, so star markers are never occluded by scenery.
struct StarMapDisc {
    glm::vec3 position{0.0f};
    glm::vec3 color{1.0f};
    float     radius  = 1.0f;   // world units
    float     opacity = 0.5f;   // flat interior fill
    float     border_opacity = 0.9f;  // crisp boundary stroke
};

/// A world-space line segment — grid, drop-lines, or the plotted course.
struct StarMapLine {
    glm::vec3 a{0.0f};
    glm::vec3 b{0.0f};
    glm::vec3 color{1.0f};
};

/// A star dot. `selected` is engine/ui/star_map.py's semantics and is carried
/// across for readers/tools only — this pass derives NOTHING from it. The
/// size a selection implies is resolved in Python and arrives as `size_px`.
struct StarMapPoint {
    glm::vec3 position{0.0f};
    glm::vec3 color{1.0f};       // halo
    float     size_px  = 4.0f;
    bool      selected = false;
    // Star centre. LAST, and defaulted to white, so the four-field aggregate
    // initialisations that predate it still compile and still mean what they
    // meant: white core is the living star.
    //
    // A burnt-out star swaps this with `color`, putting its own hue in the
    // opaque middle where it can actually be read. Python decides both
    // (engine/ui/star_map.build_scene) — this pass never picks either, for
    // the same reason it never derives a bracket's colour from `mark`.
    glm::vec3 core_color{1.0f};
};

/// A bracket reticle. `mark` mirrors engine/ui/star_map.py:
///   1 = you are here, 2 = course set, 3 = mission relevant.
///
/// Carried for semantics ONLY. This pass must never choose colour, size or
/// anything else from `mark`: star_map.py owns that enum, so a renumber there
/// would silently recolour every reticle if the mapping lived here too.
/// Presentation crosses the boundary as values — `color` and `size_px`.
struct StarMapBracket {
    glm::vec3 position{0.0f};
    int       mark = 0;
    glm::vec3 color{1.0f};
    float     size_px = 20.0f;
};

/// A dense-star region, drawn as a small fixed-SCREEN-size glyph. Not a
/// StarMapDisc: at their model `size` these became world-scaled volumes that
/// swallowed whole regions of the map. Decoration only — never selectable.
struct StarMapStarCloud {
    glm::vec3 position{0.0f};
    glm::vec3 color{1.0f};
    float     size_px = 18.0f;
    float     opacity = 0.85f;
};

struct StarMapScene {
    bool        enabled = false;
    glm::ivec4  viewport{0};   // x, y, w, h in FRAMEBUFFER pixels
    std::vector<StarMapDisc>    discs;
    std::vector<StarMapLine>    lines;
    std::vector<StarMapPoint>   points;
    std::vector<StarMapBracket> brackets;
    std::vector<StarMapStarCloud> starclouds;
};

/// Draws the sector map into a scissored sub-rect of the bound framebuffer.
///
/// Runs after the post chain resolves and BEFORE ui_cef::composite(), so CEF
/// chrome lands on top. Everything is drawn depth-test OFF in the order the
/// scene lists it — Python decides ordering (engine/ui/star_map.py), this
/// pass obeys it. Saves and restores viewport + scissor exactly as
/// letterbox_pass does; leaking either corrupts every later pass.
class StarMapPass {
public:
    StarMapPass();
    ~StarMapPass();
    StarMapPass(const StarMapPass&)            = delete;
    StarMapPass& operator=(const StarMapPass&) = delete;

    void render(const StarMapScene& scene,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                float device_scale_factor = 1.0f);

private:
    void ensure_buffers();

    unsigned int quad_vao_ = 0;
    unsigned int quad_vbo_ = 0;
    unsigned int line_vao_ = 0;
    unsigned int line_vbo_ = 0;
};

}  // namespace renderer
