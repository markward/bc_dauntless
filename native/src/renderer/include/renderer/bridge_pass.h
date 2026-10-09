// native/src/renderer/include/renderer/bridge_pass.h
#pragma once

#include <renderer/bridge_ao_pass.h>
#include <renderer/frame.h>

#include <scenegraph/instance.h>  // scenegraph::Pass

#include <assets/texture.h>

#include <cstdint>
#include <functional>
#include <string>

namespace scenegraph { class World; struct Camera; }

namespace renderer {

class Pipeline;

/// Developer-only bridge debug views (Developer Options -> Lighting tab).
/// Off is production: byte-identical to no debug support existing at all.
/// Selected via BridgePass::set_debug_view; see bridge.frag for how each is
/// drawn. The viewscreen feed (u_unlit) ignores every value here.
enum class BridgeDebugView : int {
    Off        = 0,
    Normals    = 1,
    LightOnly  = 2,
    AoOnly     = 3,
    TriangleId = 4,
    MeshId     = 5,
};

/// Renders the bridge interior in two sub-passes, both through bridge.frag:
///   A. Base geometry — opaque, alpha-test, base x the ceiling downlight
///      (the bridge ambient shaped by the surface normal; tuning in
///      renderer/bridge_lighting_tuning.h). BC's baked lightmaps are not drawn.
///   B. Characters — skinned officers, lit by the same downlight.
/// In the main bridge view (Pass::Bridge, comm_set_id == 0) both sub-passes
/// multiply their RECEIVED light by screen-space AO (BridgeAoPass), computed
/// from a normal + depth pre-pass of the same draw. The comm-set RTT and the
/// unlit viewscreen feed never get AO.
///
/// Caller is responsible for clearing color + depth before calling
/// render() (the bridge interior overlays the space scene; see
/// host_bindings.cc::frame). Renders nothing if the world has no
/// scenegraph::Pass::Bridge-tagged instances.
class BridgePass {
public:
    using ModelLookup = std::function<const assets::Model*(unsigned long long)>;

    BridgePass() = default;
    ~BridgePass();
    BridgePass(const BridgePass&) = delete;
    BridgePass& operator=(const BridgePass&) = delete;

    /// Render every visible instance tagged `pass` from `camera`. Defaults
    /// (Pass::Bridge, comm_set_id == 0) preserve the original bridge behaviour
    /// exactly. When `comm_set_id != 0`, only instances whose
    /// Instance::comm_set_id matches are drawn (used to render one comm set into
    /// the viewscreen RTT); comm_set_id == 0 means "no set filter".
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                const Lighting& lighting,
                scenegraph::Pass pass = scenegraph::Pass::Bridge,
                std::uint32_t comm_set_id = 0);

    /// Set the wall time used to advance NiFlipController-driven
    /// texture animations on bridge materials. Host loop calls this
    /// once per tick with time.monotonic().
    void set_wall_time(double t) { wall_time_ = t; }

    /// Identify the viewscreen instance by its model handle and supply the
    /// render-to-texture color texture to draw on it. When a Pass::Bridge
    /// instance's model_handle matches the registered viewscreen handle and
    /// the texture is non-zero, the base sub-pass binds `tex` as u_base_color
    /// and draws it unlit (u_unlit, so the feed isn't dimmed by bridge ambient).
    /// tex==0 (the default) falls back to set_viewscreen_off_texture, and to the
    /// instance's authored NIF texture if no off texture is set.
    void set_viewscreen_model(unsigned long long model_handle) {
        viewscreen_model_handle_ = model_handle;
    }
    void set_viewscreen_texture(unsigned int tex) { viewscreen_tex_ = tex; }

    /// Texture drawn on the viewscreen while the RTT feed is off (BC's
    /// ViewScreenObject::SetOffTexture — MissionLib.ShowLoadingText points it at
    /// data/Icons/ViewscreenLoading.tga during a mission load). Absolute path;
    /// "" clears it. Decoded lazily on the next render (the setter is called
    /// from the host loop, which may run before the GL objects exist), and only
    /// when the path changes. Without one the screen falls back to the NIF's own
    /// material, which the viewscreen mesh does not have — a flat grey panel.
    void set_viewscreen_off_texture(const std::string& path) {
        off_tex_path_ = path;
    }
    /// Set the feed brightness for ViewOn/ViewOff fade: 1.0 = full, 0.0 = black.
    /// Applies only to the viewscreen override path; all other bridge geometry
    /// receives u_viewscreen_brightness=1.0 (byte-identical output).
    void set_viewscreen_brightness(float b) { viewscreen_brightness_ = b; }

    /// Warp boom flash mixed into the viewscreen feed only (confines the
    /// lightspeed flash to the viewscreen when viewing the bridge). 0 = none.
    void set_viewscreen_flash(float f) { viewscreen_flash_ = f; }

    /// AO quality (samples, resolution). Read at the next render().
    void set_ao_settings(const BridgeAoSettings& s) { ao_settings_ = s; }

    /// Test seam: false skips the AO entirely (u_ao_on = 0). Default true;
    /// production never turns it off.
    void set_ao_enabled(bool on) { ao_enabled_ = on; }

    /// Developer-only debug view (see BridgeDebugView). Default Off is
    /// byte-identical to the production lit path.
    void set_debug_view(BridgeDebugView v) { debug_view_ = v; }
    BridgeDebugView debug_view() const { return debug_view_; }

    /// Developer-only bridge editor selection tint (spec
    /// 2026-10-08-bridge-emitters §4): mesh `selected_mesh` of the model
    /// `model_handle` pulses cyan, `hover_mesh` gets a faint tint. -1 = none.
    /// Mesh indices are into Model::meshes. Default (none) is byte-identical.
    void set_highlight(unsigned long long model_handle, int selected_mesh,
                       int hover_mesh) {
        highlight_model_ = model_handle;
        highlight_selected_ = selected_mesh;
        highlight_hover_ = hover_mesh;
    }
    void clear_highlight() { set_highlight(0, -1, -1); }
    unsigned long long highlight_model() const { return highlight_model_; }
    int highlight_selected() const { return highlight_selected_; }
    int highlight_hover() const { return highlight_hover_; }

    /// Test seam for the selection pulse's phase, in seconds. By default the
    /// pulse runs on BridgePass's own std::chrono::steady_clock, NOT the game
    /// time fed to set_wall_time: the editor always runs with the sim frozen,
    /// so a game-time pulse would never move. A negative value (the default)
    /// restores the real clock.
    void set_highlight_time(double t) { highlight_time_override_ = t; }

private:
    /// Lazily-allocated 1x1 white texture, used as a fallback for any
    /// bridge mesh whose Base-stage texture failed to load. Same role
    /// as FrameSubmitter::white_texture_ but owned by this pass so the
    /// GL handle lifetime tracks BridgePass.
    std::uint32_t white_texture_ = 0;
    std::uint32_t ensure_white_texture();
    double wall_time_ = 0.0;
    unsigned long long viewscreen_model_handle_ = 0;
    unsigned int       viewscreen_tex_ = 0;
    float              viewscreen_brightness_ = 1.0f;
    float              viewscreen_flash_ = 0.0f;

    /// Off-screen texture: requested path, the path currently decoded into
    /// `off_tex_`, and the texture itself. Reloaded only when the two differ.
    std::string     off_tex_path_;
    std::string     off_tex_loaded_;
    assets::Texture off_tex_;
    void ensure_off_texture();

    /// Screen-space AO for the main bridge view. `normal_pass_` is true while
    /// render() re-enters itself to draw the AO's normal + depth pre-pass.
    BridgeAoPass     ao_;
    BridgeAoSettings ao_settings_;
    bool             ao_enabled_ = true;
    bool             normal_pass_ = false;

    /// Developer Options -> Lighting tab "Bridge Debug View" row.
    BridgeDebugView  debug_view_ = BridgeDebugView::Off;

    /// Developer-only bridge editor selection tint. 0 model handle = none.
    unsigned long long highlight_model_ = 0;
    int                highlight_selected_ = -1;
    int                highlight_hover_ = -1;
    double             highlight_time_override_ = -1.0;
    /// Pulse phase in [0, 1): the override when set, else the real clock.
    float highlight_phase() const;
};

}  // namespace renderer
