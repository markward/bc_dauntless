// native/src/renderer/include/renderer/bridge_pass.h
#pragma once

#include <renderer/bridge_ao_pass.h>
#include <renderer/bridge_lighting_tuning.h>   // kBridgeMaxSpots
#include <renderer/bridge_probe.h>
#include <renderer/frame.h>

#include <scenegraph/instance.h>  // scenegraph::Pass

#include <assets/texture.h>

#include <cstddef>
#include <cstdint>
#include <functional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace scenegraph { class World; struct Camera; }

namespace renderer {

class Pipeline;

/// Developer-only bridge debug views (Developer Options -> Lighting tab).
/// Off is production: byte-identical to no debug support existing at all.
/// Selected via BridgePass::set_debug_view; see bridge.frag for how each is
/// drawn. The viewscreen feed (u_unlit) ignores every value here. 6..10 are
/// the PBR views: they show only where the PBR path runs (u_pbr != 0); on a
/// comm set or with PBR off they fall through to the lit colour. 9 (probe
/// mirror) draws the lit colour until both probes have been captured.
enum class BridgeDebugView : int {
    Off          = 0,
    Normals      = 1,
    LightOnly    = 2,
    AoOnly       = 3,
    TriangleId   = 4,
    MeshId       = 5,
    Roughness    = 6,
    Metalness    = 7,
    SpecularOnly = 8,
    ProbeMirror  = 9,
    MapNormals   = 10,
};

/// One per-shape PBR material override (spec 2026-10-08-bridge-emitters
/// §9.2 source B). `mesh` indexes Model::meshes; a channel `< 0` means "no
/// override" for that channel. Per channel the first hit wins: map ->
/// override -> default (roughness 1, metalness 0).
struct BridgeMaterialOverride {
    int   mesh = -1;
    float roughness = -1.0f;
    float metalness = -1.0f;
};

/// One static bridge spot light (spec 2026-10-08-bridge-emitters §9.6, plan
/// 2026-10-09-bridge-pbr Task 7), bridge world space. `direction` is the unit
/// cone axis (where the light points); the cone runs full inside `cos_inner`
/// and fades to nothing at `cos_outer` (pbr::spot_cone); `range` is where the
/// windowed inverse-square falloff (pbr::spot_falloff) reaches 0; `radiance`
/// is the LINEAR colour x intensity. No shadows; never multiplied by AO.
struct BridgeSpot {
    glm::vec3 position{0.0f};
    glm::vec3 direction{0.0f, 0.0f, -1.0f};
    float     cos_inner = 1.0f;
    float     cos_outer = 1.0f;
    float     range = 1.0f;
    glm::vec3 radiance{0.0f};
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

    /// Per-shape roughness/metalness overrides for ONE model (the bridge).
    /// Replaces any previous set (including another model's). Production
    /// data: applied to the main bridge view only (never comm sets, never
    /// officers). A later entry for the same mesh wins. The probe capture
    /// reads the metalness, so a set that DIFFERS from the current one marks
    /// the probes dirty; an identical one (or none over none) does not.
    /// clear_material_overrides() never dirties (session reset).
    void set_material_overrides(unsigned long long model_handle,
                                std::vector<BridgeMaterialOverride> overrides);
    void clear_material_overrides();

    /// A/B switch for the bridge PBR path (default on = production). Off draws
    /// the legacy downlight shading, byte-identical to before PBR existed.
    /// Comm sets always draw legacy, whatever this says.
    void set_pbr_enabled(bool on) { pbr_enabled_ = on; }
    bool pbr_enabled() const { return pbr_enabled_; }

    /// Bridge reflection probes (spec 2026-10-08-bridge-emitters §9.3): two
    /// captures of the room -- green, and yellow/red -- box-projected against
    /// the bridge model's AABB and cross-faded by set_probe_mix. Production
    /// state; none of it is developer-gated.
    ///
    /// Capture point (world). Takes effect at the next capture.
    void set_probe_origin(glm::vec3 origin) { probe_origin_ = origin; }
    glm::vec3 probe_origin() const { return probe_origin_; }
    /// Ambient multipliers each probe is captured with (lighting.ambient x
    /// scale). Take effect at the next capture.
    void set_probe_scales(float green, float yellow_red) {
        scale_green_ = green;
        scale_yr_ = yellow_red;
    }
    float probe_scale_green() const { return scale_green_; }
    float probe_scale_yellow_red() const { return scale_yr_; }

    /// Alert-level ambient multiplier for the MAIN bridge view (green x1.5,
    /// yellow/red x1.0 -- engine/bridge_lighting.py). render() is handed the
    /// UNSCALED bridge lighting: only the normal main-bridge draw multiplies
    /// by this. Comm sets never do, and probe captures use ambient x probe
    /// scale alone (the probes ARE the per-alert captures). Default 1.
    void set_alert_ambient_scale(float s) { alert_ambient_scale_ = s; }
    float alert_ambient_scale() const { return alert_ambient_scale_; }
    /// 0 = the green probe, 1 = the yellow/red probe; clamped to [0, 1].
    void set_probe_mix(float t);
    float probe_mix() const { return probe_mix_; }
    /// Mark the probes dirty: both are recaptured inside the next main-bridge
    /// render(), before its AO pre-pass. Never per frame otherwise -- except
    /// that, once they have been captured, two changes re-dirty them by
    /// themselves: a different bridge model (the static bridge instance with
    /// the most meshes), and a different bridge lighting (the unscaled
    /// ambient render() is handed; the alert scale never counts).
    void request_probe_capture() { probe_dirty_ = true; }
    bool probe_capture_pending() const { return probe_dirty_; }
    /// True once both probes hold a capture the shader may sample.
    bool probes_valid() const;
    /// Static spot lights for the main bridge view (PBR path only; comm sets
    /// and the legacy A/B path never see them). Replaces the previous set,
    /// keeping the first kBridgeMaxSpots; returns how many were dropped (the
    /// caller reports them -- never silently). The probe captures include the
    /// spots' diffuse, so a list that DIFFERS from the current one (compared
    /// after the normalisation and truncation below) marks the probes dirty
    /// -- here in the pass, not in the binding, so every caller gets it
    /// (clearing a non-empty list too). An identical list, or empty over
    /// empty, does not: an alert change re-pushes the same list every time.
    ///
    /// Expects a unit `direction` and cos_inner >= cos_outer, and finite
    /// values (the set_bridge_spots binding drops non-finite lights and
    /// normalises). Defensively, this normalises the axis again (a zero axis
    /// becomes straight down, -Z) and lowers cos_outer to cos_inner if the
    /// two arrive swapped.
    std::size_t set_spots(std::vector<BridgeSpot> spots);
    /// Session reset: drop every spot WITHOUT marking the probes dirty
    /// (reset_probes() beside it drops the captures and the request).
    void clear_spots() { spots_.clear(); }
    std::size_t spot_count() const { return spots_.size(); }

    /// Mission swap: drop the captures (no specular until the next request),
    /// the pending request, the mix and the cached boxes (model handles die
    /// with the session). Origin and scales are configuration and are kept.
    void reset_probes();

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

    /// Bridge PBR: the A/B switch and the per-shape overrides of the model
    /// `overrides_model_` (0 = none), keyed by mesh index -> (rough, metal).
    bool pbr_enabled_ = true;
    unsigned long long overrides_model_ = 0;
    std::unordered_map<int, std::pair<float, float>> overrides_;

    /// Bridge reflection probes. `capture_pass_` is true while render()
    /// re-enters itself to draw one probe face (sub-pass A, u_capture = 1).
    /// The LUT is owned here (not process-wide): its destructor, like the
    /// probes', needs this pass's GL context current.
    BridgeProbe probe_green_;
    BridgeProbe probe_yr_;
    BrdfLut     brdf_lut_;
    glm::vec3   probe_origin_{0.0f};
    float       scale_green_ = 1.0f;
    float       scale_yr_ = 1.0f;
    float       probe_mix_ = 0.0f;
    float       alert_ambient_scale_ = 1.0f;
    bool        probe_dirty_ = false;
    bool        probes_captured_ = false;   // cleared by reset_probes()
    /// The (unscaled) bridge ambient the current captures were taken with --
    /// the only Lighting field the pass reads. A main-bridge render handed a
    /// different one re-dirties captured probes.
    glm::vec3   capture_ambient_{0.0f};
    bool        capture_pass_ = false;
    /// Static spot lights, at most kBridgeMaxSpots (set_spots truncates).
    std::vector<BridgeSpot> spots_;
    void capture_probes(const scenegraph::World& world, Pipeline& pipeline,
                        const ModelLookup& lookup, const Lighting& lighting);

    /// The box the reflections are projected against: the bridge model (the
    /// static main-bridge instance with the largest AABB) through its
    /// instance world. Model-space AABBs are cached per model handle (CPU
    /// mesh data through the node rest worlds); `box_handle_` is the handle
    /// the current box came from, and a change re-dirties captured probes.
    struct Aabb { glm::vec3 min{0.0f}; glm::vec3 max{0.0f}; bool valid = false; };
    std::unordered_map<unsigned long long, Aabb> model_boxes_;
    unsigned long long box_handle_ = 0;
    glm::vec3 box_min_{-1.0f};
    glm::vec3 box_max_{1.0f};
    const Aabb& model_box(unsigned long long handle, const assets::Model& m);
    /// False when no static main-bridge instance is drawn (box unchanged).
    bool update_box(const scenegraph::World& world, const ModelLookup& lookup);
};

}  // namespace renderer
