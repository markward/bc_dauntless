// native/src/renderer/include/renderer/bridge_pass.h
#pragma once

#include <renderer/bridge_ao_pass.h>
#include <renderer/bridge_lighting_tuning.h>   // kBridgeMaxSpots
#include <renderer/bridge_probe.h>         // BrdfLut (BridgeProbe is test-only)
#include <renderer/bridge_probe_array.h>
#include <renderer/bridge_probe_schedule.h>  // kBridgeStates, next_probe
#include <renderer/frame.h>

#include <scenegraph/instance.h>  // scenegraph::Pass

#include <assets/material.h>
#include <assets/texture.h>

#include <algorithm>
#include <array>
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
/// drawn. The viewscreen feed (u_unlit) ignores every value here. 6..11 are
/// the PBR views: they show only where the PBR path runs (u_pbr != 0); on a
/// comm set or with PBR off they fall through to the lit colour. 9 (probe
/// mirror) is the composed reflection -- every sampled base and layer, x its
/// weight, along the unprojected mirror ray at mip 0 -- and draws the lit
/// colour while nothing is sampled. 11 is the same with the layer entries
/// only (black when no layer is sampled).
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
    ReflectionLayers = 11,
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
    /// Spec 2026-10-08-bridge-emitters §11.4: the radiance each state's base
    /// probe capture sees (index = state), separate from the live `radiance`
    /// (set_spot_radiance), so a pulsing or fading light never recaptures.
    /// false = every state's capture uses the `radiance` the light was
    /// pushed with: set_spots / set_area_lights copy it into
    /// capture_radiance and set this, so a later live colour never reaches
    /// a probe.
    bool      has_capture = false;
    glm::vec3 capture_radiance[kBridgeStates] = {};
    /// Reflection layers (spec 2026-10-17 §4.5): per state, the layer this row
    /// belongs to there (-1 = none; a row is in at most one layer per state)
    /// and its at-peak radiance in that layer.
    int       layer[kBridgeStates] = {-1, -1, -1, -1, -1};
    glm::vec3 layer_radiance[kBridgeStates] = {};
};

/// One static bridge area light (spec 2026-10-08-bridge-emitters §16.3): a
/// rectangle, centre + perpendicular half-axes, emitting toward
/// cross(half_u, half_v) only -- a strip or panel cut from an object's front
/// rectangle (engine/bridge_editor/light_shapes.py). `radiance` is LINEAR
/// colour x intensity (surface brightness); the capture colours follow the
/// BridgeSpot rule (§11.4).
struct BridgeAreaLight {
    glm::vec3 center{0.0f};
    glm::vec3 half_u{1.0f, 0.0f, 0.0f};
    glm::vec3 half_v{0.0f, -1.0f, 0.0f};
    float     range = 1.0f;
    glm::vec3 radiance{0.0f};
    bool      has_capture = false;
    glm::vec3 capture_radiance[kBridgeStates] = {};
    int       layer[kBridgeStates] = {-1, -1, -1, -1, -1};
    glm::vec3 layer_radiance[kBridgeStates] = {};
    /// Spec §16.8: bit 0 / bit 1 = joined to a neighbour at the -u / +u end
    /// (pbr::area_join_weight). Highlight only: never recaptures.
    int       joins = 0;
};

/// One per-shape emitter glow (spec 2026-10-08-bridge-emitters §11.2),
/// pushed every frame. `src`: 0 the alert's emissive sibling map, 1 the
/// albedo (the current flipbook frame), 2 flat. `rgb` = profile tint x level
/// x wave x scale, DISPLAY space, added after the diffuse ceiling; `level` =
/// level x wave x scale, which dips the received light (1 - m x clamp(level)).
struct BridgeGlow {
    int       mesh = -1;
    int       src = 0;
    glm::vec3 rgb{0.0f};
    float     level = 0.0f;
};

/// `BridgeGlow`'s capture-side twin (spec 2026-10-17 §4.5): what a glow shape
/// contributes to each state's base probe and to the layers it belongs to.
/// Display-space values, as BridgeGlow::rgb. Never live: it feeds probe
/// signatures and captures (a capture adds decode(value), uncapped).
struct BridgeGlowCapture {
    int       mesh = -1;
    int       src = 0;
    glm::vec3 base[kBridgeStates] = {};
    int       layer[kBridgeStates] = {-1, -1, -1, -1, -1};
    glm::vec3 layer_rgb[kBridgeStates] = {};
};

/// Bridge states beyond the alert levels (spec 2026-10-08-bridge-emitters §13.1):
/// 0 green, 1 yellow, 2 red, 3 offline, 4 special.
inline constexpr int kBridgeStateOffline = 3;
inline constexpr int kBridgeStateSpecial = 4;

/// The Model::textures index of the emissive map a bridge material shows at
/// alert level `alert` (0 green, 1 yellow, 2 red; anything else is green):
/// yellow -> EmissiveYellow, red -> EmissiveRed then EmissiveYellow, each
/// falling back to Emissive; green -> Emissive; special -> EmissiveSpecial
/// else Emissive; offline -> Emissive (for a MATERIAL glow through the
/// emission map; the texture-level default is dark at offline -- draw_mesh).
/// -1 = no emissive map.
int bridge_emissive_texture(const assets::Material& mat, int alert);

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
    /// reads the metalness, so the set is a signature input of every probe
    /// (probe_signature): a set that DIFFERS from the one a probe was
    /// captured with queues it; an identical one (or none over none) does
    /// not. clear_material_overrides() is the session reset's half (beside
    /// reset_probes()).
    void set_material_overrides(unsigned long long model_handle,
                                std::vector<BridgeMaterialOverride> overrides);
    void clear_material_overrides();

    /// A/B switch for the bridge PBR path (default on = production). Off draws
    /// the legacy downlight shading, byte-identical to before PBR existed.
    /// Comm sets always draw legacy, whatever this says.
    void set_pbr_enabled(bool on) { pbr_enabled_ = on; }
    bool pbr_enabled() const { return pbr_enabled_; }

    /// Bridge reflection probes (spec 2026-10-08-bridge-emitters §9.3, spec
    /// 2026-10-17-bridge-reflection-layers §4): one capture of the room per
    /// state (its base) plus one per animation layer, all in one cube-map
    /// array, box-projected against the bridge model's AABB. The shader sums
    /// one weighted list of them (spec §4.2): every base by its cross-fade
    /// weight (set_probe_state) and every layer by its live value
    /// (set_layer_values) x its state's base weight. Production state; none
    /// of it is developer-gated.
    ///
    /// Capture point (world). Takes effect at the next capture.
    void set_probe_origin(glm::vec3 origin) { probe_origin_ = origin; }
    glm::vec3 probe_origin() const { return probe_origin_; }
    /// Ambient multipliers each probe is captured with (lighting.ambient x
    /// scale). Take effect at the next capture.
    void set_probe_scales(const std::array<float, kBridgeStates>& scales) {
        scales_ = scales;
    }
    /// 0 for a state outside [0, kBridgeStates).
    float probe_scale(int state) const {
        return (state >= 0 && state < kBridgeStates)
            ? scales_[static_cast<std::size_t>(state)] : 0.0f;
    }
    /// The state each animation layer k belongs to (probe id kBridgeStates+k)
    /// and its identity (spec §4.4: a stable hash of its state and wave key;
    /// a missing identity is the state itself). Entries whose state is
    /// outside [0, kBridgeStates) are dropped with their identity; returns
    /// how many. A layer whose identity at its index differs from the one
    /// there before (or that is new at its index) holds another layer's
    /// capture, or none: its slot is invalidated (BridgeProbeArray::
    /// invalidate) so it reads as absent -- never sampled -- until its own
    /// capture lands. An unchanged identity keeps the capture (a changed
    /// member then requeues it by signature, the old content showing).
    std::size_t set_probe_layers(std::vector<int> layer_states,
                                 std::vector<std::uint64_t> identities = {});
    /// kBridgeStates base probes + one per layer.
    int probe_count() const {
        return kBridgeStates + static_cast<int>(layer_states_.size());
    }
    /// FNV-1a over exactly the inputs probe `probe` reads (spec §4.5): the
    /// shared ones (overrides, origin, box, unscaled ambient, light geometry,
    /// glow-capture shapes) plus, for a base, its scale and per-state capture
    /// colours; for a layer, its state and its members' at-peak values. Live
    /// radiance and set_glow never enter. Out of range -> 0.
    std::uint64_t probe_signature(int probe) const;
    /// Per-shape glow contribution to the probes for ONE model; replaces the
    /// previous set. Signature input only.
    void set_glow_captures(unsigned long long model_handle,
                           std::vector<BridgeGlowCapture> captures);
    void clear_glow_captures() { glow_captures_.clear(); glow_capture_model_ = 0; }

    /// Alert-level ambient multiplier for the MAIN bridge view (green x1.5,
    /// yellow/red x1.0 -- engine/bridge_lighting.py). render() is handed the
    /// UNSCALED bridge lighting: only the normal main-bridge draw multiplies
    /// by this. Comm sets never do, and probe captures use ambient x probe
    /// scale alone (the probes ARE the per-alert captures). Default 1.
    void set_alert_ambient_scale(float s) { alert_ambient_scale_ = s; }
    float alert_ambient_scale() const { return alert_ambient_scale_; }
    /// Player alert level (0 green, 1 yellow, 2 red) choosing each material's
    /// emissive variant (bridge_emissive_texture) in the MAIN bridge view.
    /// Comm sets always show the default (green) emissive; a probe capture
    /// shows its own state's variant, whatever this says. Hard switch, no
    /// fade. Default 0.
    void set_alert_level(int level) { alert_level_ = level; }
    int alert_level() const { return alert_level_; }
    /// The shown bridge state and the paused-aware bridge dt, once per frame
    /// (spec §4.2): runs the base cross-fade (ProbeFade, 0.5 s, frozen at dt
    /// 0) toward `state`'s base, which starts rising only once it is valid
    /// (the old base keeps showing until then). `state` is also the shown
    /// state the capture queue serves first. Out of range = no state: every
    /// weight holds. Before the first call nothing is shown: no reflection.
    /// render() re-runs the fade at dt 0 after its capture steps, so a base
    /// that lands with nothing showing (a new bridge) snaps in that frame.
    void set_probe_state(int state, float dt);
    /// Base `state`'s weight in the reflection; 0 out of range.
    float base_weight(int state) const;
    /// Each layer's live value, by layer index: v_k = w(t)^2.2 (spec §4.2).
    /// A missing value is 0; a non-finite one becomes 0. Never dirties a probe.
    void set_layer_values(std::vector<float> values);
    /// The capture queue (spec 2026-10-17 §4.7). A probe needs a capture
    /// while it holds none, or while the signature it was captured with
    /// differs from probe_signature() now -- so a setter never requests one;
    /// changing an input a probe reads (spots, area lights, overrides,
    /// scales, glow captures, layers, the origin, the bridge model, the
    /// unscaled ambient render() is handed) queues exactly the probes that
    /// read it. Nothing is captured before the first request (the bridge
    /// load makes it). Each main-bridge render(), before its AO pre-pass,
    /// runs kBridgeProbeStepsPerFrame steps of the probe in flight, picked by
    /// next_probe with set_probe_state's state as the shown state. A probe in
    /// flight draws every face from the inputs snapshotted at its first step;
    /// a change meanwhile requeues it once it lands. A different bridge model
    /// frees every probe and zeroes every base weight, so the new room never
    /// reflects the old one: no reflection until its shown base lands.
    ///
    /// request_probe_capture(): forget every captured signature (each probe
    /// recaptures, its old content showing until then) and drop the probe in
    /// flight. Never per frame.
    void request_probe_capture();
    /// True once the shown state's base (set_probe_state's state; 0 when
    /// none) holds a capture.
    bool probes_valid() const;
    /// True once probe `probe` holds a completed capture (it keeps showing
    /// while a recapture of it is in flight). False out of range.
    bool probe_valid(int probe) const;
    /// Nothing queued and nothing in flight. Always true before the first
    /// request_probe_capture() (and after reset_probes()).
    bool probes_settled() const;
    /// Test accessor: completed captures of probe `probe` since construction
    /// (capture_probe_now's included). 0 out of range.
    int probe_captures_completed(int probe) const;
    /// Test seam: capture steps per main-bridge render(); 0 = unlimited (the
    /// whole queue drains inside one render()). Default
    /// kBridgeProbeStepsPerFrame -- production never changes it.
    void set_probe_steps_per_frame(int n) { steps_per_frame_ = n; }
    /// Steps one probe takes (BridgeProbeArray::steps_per_probe).
    int steps_per_probe() const { return probes_.steps_per_probe(); }
    /// Static spot lights for the main bridge view (PBR path only; comm sets
    /// and the legacy A/B path never see them). Replaces the previous set,
    /// keeping the first kBridgeMaxSpots; returns how many were dropped (the
    /// caller reports them -- never silently). The probe captures include the
    /// spots' diffuse: the stored (normalised, truncated) list is a signature
    /// input, so a list that differs queues the probes that read the change
    /// (clearing a non-empty list too). An identical list, or empty over
    /// empty, queues nothing: an alert change re-pushes the same list every
    /// time.
    ///
    /// Expects a unit `direction` and cos_inner >= cos_outer, and finite
    /// values (the set_bridge_spots binding drops non-finite lights and
    /// normalises). Defensively, this normalises the axis again (a zero axis
    /// becomes straight down, -Z) and lowers cos_outer to cos_inner if the
    /// two arrive swapped.
    std::size_t set_spots(std::vector<BridgeSpot> spots);
    /// Drop every spot (paired with reset_probes(), which drops the captures
    /// and the request, so nothing is queued by it). The host
    /// does not call it: a new session builds a fresh BridgePass.
    void clear_spots() { spots_.clear(); }
    /// Live radiance for the current spots in set_spots order (spec §11.4).
    /// Extra entries are ignored, missing ones keep their value, non-finite
    /// becomes 0. Never dirties the probes.
    void set_spot_radiance(const std::vector<glm::vec3>& radiance);
    /// Static area lights (spec §16.3), main bridge view + its probe
    /// captures only. Keeps the first kBridgeMaxAreaLights, returns how many
    /// were dropped; a signature input like the spots (geometry, range and
    /// capture colours; joins and live colours never).
    std::size_t set_area_lights(std::vector<BridgeAreaLight> lights);
    /// Live radiance in set_area_lights order; never dirties the probes.
    void set_area_radiance(const std::vector<glm::vec3>& radiance);
    std::size_t area_light_count() const { return area_lights_.size(); }
    /// Per-shape glow for ONE model (the bridge), replacing the previous set;
    /// a later entry for the same mesh wins. Main bridge view only. Never
    /// dirties the probes: live glow is not captured (§9.7) -- the probes
    /// hold set_glow_captures' values instead.
    void set_glow(unsigned long long model_handle, std::vector<BridgeGlow> glow);
    void clear_glow() { glow_.clear(); glow_model_ = 0; }
    std::size_t glow_count() const { return glow_.size(); }
    std::size_t spot_count() const { return spots_.size(); }

    /// Drop the captures (the probe array is freed: no specular until the
    /// next request), the request, the probe in flight, the base weights and the
    /// cached boxes (model handles die with the session). Origin and scales
    /// are configuration and are kept. Needs the GL context current to free
    /// the array. The host does not call it: a new session builds a fresh
    /// BridgePass.
    void reset_probes();

    /// Capture probe `probe` (a base: the state id; a layer: kBridgeStates +
    /// k) whole, in one call, into the probe array -- every step of the
    /// scheduler's path back to back (snapshot, steps, completion), each face
    /// drawn with that probe's content (spec 2026-10-17 §4.1). Takes
    /// `lighting.ambient` as the current unscaled ambient. Replaces any probe
    /// in flight. Test seam: production never captures a whole probe in one
    /// frame. Out-of-range probe, or no GL targets: nothing.
    void capture_probe_now(int probe, const scenegraph::World& world, Pipeline& pipeline,
                           const ModelLookup& lookup, const Lighting& lighting);
    /// Test seam: every texel of probe `probe`'s six faces at `mip` (face-
    /// major, GL face order +X -X +Y -Y +Z -Z, rows bottom-up), linear RGB,
    /// read back from the probe array. False (and `rgb` emptied) when that
    /// probe holds no completed capture or `mip` is out of range. Restores
    /// the read framebuffer and pack alignment.
    bool read_probe(int probe, int mip, std::vector<glm::vec3>& rgb) const;

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
    /// probe array's, needs this pass's GL context current.
    BrdfLut     brdf_lut_;
    glm::vec3   probe_origin_{0.0f};
    std::array<float, kBridgeStates> scales_{1.0f, 1.0f, 1.0f, 1.0f, 1.0f};
    std::vector<int> layer_states_;
    /// Each layer's identity, by layer index (set_probe_layers).
    std::vector<std::uint64_t> layer_ids_;
    unsigned long long glow_capture_model_ = 0;
    std::vector<BridgeGlowCapture> glow_captures_;
    /// Signature each probe's completed capture was taken with, by probe id;
    /// 0 = none (request_probe_capture() zeroes them all).
    std::vector<std::uint64_t> captured_sigs_;
    /// Completed captures by probe id since construction (test accessor).
    std::vector<int> captures_completed_;
    /// The base cross-fade, its target (-1 = none) and each layer's live
    /// value (spec §4.2).
    ProbeFade   fade_;
    int         probe_target_ = -1;
    std::vector<float> layer_values_;
    int         steps_per_frame_ = kBridgeProbeStepsPerFrame;
    float       alert_ambient_scale_ = 1.0f;
    int         alert_level_ = 0;
    /// Set by request_probe_capture(), cleared by reset_probes(): nothing is
    /// queued before the first request.
    bool        capture_requested_ = false;
    /// The probe array could not be allocated: one report per request, no
    /// retry every frame.
    bool        storage_failed_ = false;
    /// The (unscaled) bridge ambient the last main-bridge render() was handed
    /// -- the only Lighting field the pass reads. A signature input: a
    /// different one queues every probe.
    glm::vec3   capture_ambient_{0.0f};
    bool        capture_pass_ = false;
    /// Static spot lights, at most kBridgeMaxSpots (set_spots truncates).
    std::vector<BridgeSpot> spots_;
    /// Static area lights, at most kBridgeMaxAreaLights.
    std::vector<BridgeAreaLight> area_lights_;
    /// Per-shape emitter glow of the model `glow_model_` (0 = none).
    unsigned long long glow_model_ = 0;
    std::unordered_map<int, BridgeGlow> glow_;
    /// Every probe (bases and layers): slot = probe id.
    BridgeProbeArray probes_;
    /// Which probe a capture pass is drawing: a probe id (base s = s, layer
    /// k = kBridgeStates + k).
    int capture_probe_ = 0;

    /// Every input a probe capture reads, as snapshotted at a probe's first
    /// step (spec §4.7): the probe in flight draws all its faces from it.
    struct ProbeInputs {
        std::vector<BridgeSpot> spots;
        std::vector<BridgeAreaLight> areas;
        unsigned long long glow_capture_model = 0;
        std::vector<BridgeGlowCapture> glow_captures;
        unsigned long long overrides_model = 0;
        std::unordered_map<int, std::pair<float, float>> overrides;
        std::array<float, kBridgeStates> scales{};
        std::vector<int> layer_states;
        glm::vec3 origin{0.0f};
        glm::vec3 ambient{0.0f};
    };
    ProbeInputs   snapshot_;
    std::uint64_t snapshot_sig_ = 0;
    /// Exchange the live inputs with `in` (both ways: a step swaps the
    /// snapshot in, draws, and swaps it back out).
    void swap_inputs(ProbeInputs& in);
    /// The state whose probes go first: probe_target_ (0 when none).
    int shown_state() const;
    bool probe_needs_capture(int probe) const;
    /// Size the array (and the per-probe bookkeeping) to probe_count().
    bool sync_probe_storage();
    /// Snapshot the inputs and start probe `probe` in the array.
    void begin_probe(int probe);
    /// One step of the probe in flight, drawn from the snapshot; on its last
    /// step, record the snapshot's signature and count the completion.
    void step_probe(const scenegraph::World& world, Pipeline& pipeline,
                    const ModelLookup& lookup, const Lighting& lighting);
    /// The per-frame budget of steps (render()'s capture block).
    void run_capture_steps(const scenegraph::World& world, Pipeline& pipeline,
                           const ModelLookup& lookup, const Lighting& lighting);
    /// Draw one face of probe `probe` from `face_cam` into the bound target:
    /// render() re-entered with capture_pass_ set, sub-pass A only.
    void draw_probe_face(int probe, const scenegraph::Camera& face_cam,
                         const scenegraph::World& world, Pipeline& pipeline,
                         const ModelLookup& lookup, const Lighting& lighting);

    /// The box the reflections are projected against: the bridge model (the
    /// static main-bridge instance with the most meshes) through its
    /// instance world. Model-space AABBs are cached per model handle (CPU
    /// mesh data through the node rest worlds); `box_handle_` is the handle
    /// the current box came from (a signature input); a change frees every
    /// probe and zeroes the base weights.
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
