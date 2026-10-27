#include "normal_gen.h"

#include <glm/glm.hpp>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <limits>
#include <map>
#include <unordered_map>
#include <utility>
#include <vector>

namespace assets::detail {

namespace {

using PosKey = std::array<std::uint32_t, 3>;

PosKey pos_key(const glm::vec3& p) {
    PosKey k;
    std::memcpy(k.data(), &p.x, sizeof(float) * 3);
    return k;
}

// Where a vertex of the joint pass's combined mesh came from: the shape that
// owns it and its position in that shape's own frame.
struct VertexOrigin {
    std::uint32_t shape;
    glm::vec3     local_pos;
};

// Every per-vertex channel the joint pass carries, grown in lockstep.
struct VertexChannels {
    MeshCpu&                   mesh;
    std::vector<glm::vec4>&    source_colours;  // may be empty: stays empty
    std::vector<VertexOrigin>* origins;         // nullptr outside the joint pass

    // Copy vertex v.
    std::uint32_t duplicate(std::uint32_t v) {
        mesh.vertices.push_back(mesh.vertices[v]);
        for (auto& set : mesh.extra_uvs)
            if (v < set.size()) set.push_back(set[v]);
        if (!source_colours.empty()) source_colours.push_back(source_colours[v]);
        if (origins) origins->push_back((*origins)[v]);
        return static_cast<std::uint32_t>(mesh.vertices.size() - 1);
    }

    // New vertex on a->b at parameter t, carrying a's attributes interpolated
    // towards b's. The owner shape is a's.
    std::uint32_t interpolate(std::uint32_t a, std::uint32_t b, float t) {
        MeshCpu::Vertex v = mesh.vertices[a];
        const auto& vb = mesh.vertices[b];
        v.position = glm::mix(v.position, vb.position, t);
        v.uv = glm::mix(v.uv, vb.uv, t);
        v.uv1 = glm::mix(v.uv1, vb.uv1, t);
        v.color = glm::u8vec4(glm::round(glm::mix(glm::vec4(v.color), glm::vec4(vb.color), t)));
        mesh.vertices.push_back(v);
        for (auto& set : mesh.extra_uvs)
            if (a < set.size() && b < set.size()) set.push_back(glm::mix(set[a], set[b], t));
        if (!source_colours.empty())
            source_colours.push_back(glm::mix(source_colours[a], source_colours[b], t));
        if (origins) {
            const VertexOrigin& oa = (*origins)[a];
            const VertexOrigin& ob = (*origins)[b];
            origins->push_back({oa.shape, glm::mix(oa.local_pos, ob.local_pos, t)});
        }
        return static_cast<std::uint32_t>(mesh.vertices.size() - 1);
    }
};

// Distinct vertices at one position with identical attributes: the only
// reason an exporter splits those is a hard edge. Vertices from different
// shapes (or different local positions) are never twins.
bool is_twin(const VertexChannels& ch, std::uint32_t a, std::uint32_t b) {
    const MeshCpu& m = ch.mesh;
    const auto& src_col = ch.source_colours;
    const auto& va = m.vertices[a];
    const auto& vb = m.vertices[b];
    if (va.uv != vb.uv || va.uv1 != vb.uv1) return false;
    if (a < src_col.size() && b < src_col.size()) {
        if (src_col[a] != src_col[b]) return false;
    } else if (va.color != vb.color) {
        return false;
    }
    for (const auto& set : m.extra_uvs)
        if (a < set.size() && b < set.size() && set[a] != set[b]) return false;
    if (ch.origins) {
        const VertexOrigin& oa = (*ch.origins)[a];
        const VertexOrigin& ob = (*ch.origins)[b];
        if (oa.shape != ob.shape || oa.local_pos != ob.local_pos) return false;
    }
    return true;
}

// One authored edge of a recorded shape, its ends in the joint pass's shared
// space as they were BEFORE the T-junction repair. Indexed like the report.
struct AuthoredSegment {
    std::uint32_t shape;
    glm::vec3     a, b;
    bool          hard;
    bool          usable;  // both indices in range and the ends distinct
};

// The joint pass's authored smoothing, handed to smooth_normals_impl.
struct AuthoredSmoothing {
    std::vector<AuthoredSegment>            segments;
    std::vector<std::vector<std::uint32_t>> by_shape;  // usable segment ids per shape
    std::vector<bool>                       recorded;  // per shape: has a record
    std::uint32_t                           original_vertices = 0;  // before the repair; later ones it inserted
    bool                                    joins_hard = false;
    SmoothingReport*                        report = nullptr;  // rows parallel to `segments`
};

// A T-junction piece lies on its authored segment as closely as the repair
// requires a T point to lie on the edge it splits (repair_t_junctions_impl),
// so every piece the repair can cut from a segment matches it.
bool on_segment(const AuthoredSegment& s, const glm::vec3& p) {
    const glm::vec3 ab = s.b - s.a;
    const float len2 = glm::dot(ab, ab);
    const float u = glm::dot(p - s.a, ab) / len2;
    if (u < 0.0f || u > 1.0f) return false;
    return glm::length(p - s.a - u * ab) <= 1e-3f * std::sqrt(len2);
}

void smooth_normals_impl(VertexChannels& ch, float crease_deg,
                         const AuthoredSmoothing* authored = nullptr) {
    MeshCpu& m = ch.mesh;
    const std::size_t tri_count = m.indices.size() / 3;
    if (tri_count == 0) return;
    const float cos_crease = std::cos(glm::radians(crease_deg));

    std::vector<glm::vec3> face_n(tri_count, glm::vec3(0.0f));
    std::vector<float> face_area(tri_count, 0.0f);
    for (std::size_t t = 0; t < tri_count; ++t) {
        const glm::vec3 p0 = m.vertices[m.indices[t * 3 + 0]].position;
        const glm::vec3 p1 = m.vertices[m.indices[t * 3 + 1]].position;
        const glm::vec3 p2 = m.vertices[m.indices[t * 3 + 2]].position;
        const glm::vec3 c = glm::cross(p1 - p0, p2 - p0);
        const float len = glm::length(c);
        if (len < 1e-12f) continue;  // degenerate: contributes nothing
        face_n[t] = c / len;
        face_area[t] = 0.5f * len;
    }

    // Weld corners by position (corner id = t*3 + k).
    std::map<PosKey, std::uint32_t> weld_id;
    std::vector<std::uint32_t> corner_w(tri_count * 3);
    for (std::uint32_t c = 0; c < tri_count * 3; ++c) {
        const auto key = pos_key(m.vertices[m.indices[c]].position);
        auto it = weld_id.try_emplace(key, static_cast<std::uint32_t>(weld_id.size())).first;
        corner_w[c] = it->second;
    }

    // Smoothing groups: corners around one welded position join when their
    // faces share an EDGE whose fold is under the crease, chained around the
    // fan. Union-find with parity: parity = this corner's orientation relative
    // to its parent (+1 same, -1 flipped), because BC winding is mixed and the
    // shared edge tells us exactly when a neighbour is wound the other way.
    std::vector<std::uint32_t> parent(tri_count * 3);
    std::vector<int> parity(tri_count * 3, 1);
    for (std::uint32_t c = 0; c < parent.size(); ++c) parent[c] = c;
    auto find = [&](std::uint32_t x) {
        int sign = 1;
        while (parent[x] != x) { sign *= parity[x]; x = parent[x]; }
        return std::pair<std::uint32_t, int>{x, sign};
    };
    // Cannot-link sets (authored hard edges only): forbid[r] lists corners
    // whose group may never merge with root r's. Kept symmetric and moved
    // onto the surviving root on every union, so a list entry is checked
    // through find() -- it may no longer be a root itself.
    std::unordered_map<std::uint32_t, std::vector<std::uint32_t>> forbid;
    auto unite = [&](std::uint32_t a, std::uint32_t b, int s) {
        const auto [ra, pa] = find(a);
        const auto [rb, pb] = find(b);
        if (ra == rb) return;
        if (!forbid.empty()) {
            const auto fa = forbid.find(ra);
            const auto fb = forbid.find(rb);
            if (fa != forbid.end() && fb != forbid.end()) {
                const bool a_smaller = fa->second.size() <= fb->second.size();
                const auto& list = a_smaller ? fa->second : fb->second;
                const std::uint32_t other = a_smaller ? rb : ra;
                for (std::uint32_t f : list)
                    if (find(f).first == other) return;
            }
            if (fb != forbid.end()) {
                std::vector<std::uint32_t> moved = std::move(fb->second);
                forbid.erase(fb);
                auto& into = forbid[ra];
                if (into.size() < moved.size()) std::swap(into, moved);  // append the shorter
                into.insert(into.end(), moved.begin(), moved.end());
            }
        }
        parent[rb] = ra;
        parity[rb] = pa * s * pb;
    };

    struct EdgeUse { std::uint32_t tri; std::uint32_t ca, cb; bool forward; };
    std::map<std::pair<std::uint32_t, std::uint32_t>, std::vector<EdgeUse>> edges;
    for (std::uint32_t t = 0; t < tri_count; ++t) {
        if (glm::length(face_n[t]) < 0.5f) continue;  // degenerate
        for (std::uint32_t k = 0; k < 3; ++k) {
            const std::uint32_t ca = t * 3 + k, cb = t * 3 + (k + 1) % 3;
            const std::uint32_t wa = corner_w[ca], wb = corner_w[cb];
            if (wa == wb) continue;
            const bool fwd = wa < wb;
            edges[{std::min(wa, wb), std::max(wa, wb)}].push_back(
                {t, fwd ? ca : cb, fwd ? cb : ca, fwd});
        }
    }
    // Join two faces across their shared edge: under the crease and not a
    // twin split, or always when `forced` (an authored soft edge).
    auto join = [&](const EdgeUse& a, const EdgeUse& b, bool forced) {
        // Consistent winding walks a shared edge in opposite directions; the
        // same direction means b is flipped.
        const int s = (a.forward == b.forward) ? -1 : 1;
        if (!forced && s * glm::dot(face_n[a.tri], face_n[b.tri]) < cos_crease) return;
        const std::pair<std::uint32_t, std::uint32_t> ends[2] = {
            {a.ca, b.ca}, {a.cb, b.cb}};
        for (const auto& [c1, c2] : ends) {
            const std::uint32_t v1 = m.indices[c1], v2 = m.indices[c2];
            if (!forced && v1 != v2 && is_twin(ch, v1, v2)) continue;
            unite(c1, c2, s);
        }
    };
    if (!authored) {
        for (const auto& [key, uses] : edges)
            for (std::size_t i = 0; i < uses.size(); ++i)
                for (std::size_t j = i + 1; j < uses.size(); ++j) join(uses[i], uses[j], false);
    } else {
        // Authored smoothing (spec 2026-10-27-bridge-authored-smoothing-design.md
        // §3.3). A face's shape is its first corner's owner, as the split-back
        // uses.
        const AuthoredSmoothing& au = *authored;
        const std::vector<VertexOrigin>& origins = *ch.origins;
        auto tri_shape = [&](std::uint32_t t) { return origins[m.indices[t * 3]].shape; };
        std::vector<glm::vec3> weld_pos(weld_id.size());
        for (std::uint32_t c = 0; c < tri_count * 3; ++c)
            weld_pos[corner_w[c]] = m.vertices[m.indices[c]].position;
        auto weld_of = [&](const glm::vec3& p) -> std::int64_t {
            const auto it = weld_id.find(pos_key(p));
            return it == weld_id.end() ? -1 : static_cast<std::int64_t>(it->second);
        };

        // An edge matches a segment of its shape when its ends ARE the
        // segment's ends, else when it is a T-junction piece: both ends lie on
        // the segment and the faces' corners include a vertex the repair
        // inserted (every piece it cuts has one). An edge between original
        // vertices that misses the exact lookup is game-only: crease rule.
        std::map<std::array<std::uint32_t, 3>, std::uint32_t> exact;
        for (std::uint32_t k = 0; k < au.segments.size(); ++k) {
            const AuthoredSegment& seg = au.segments[k];
            if (!seg.usable) continue;
            const std::int64_t wa = weld_of(seg.a), wb = weld_of(seg.b);
            if (wa < 0 || wb < 0) continue;
            exact.try_emplace({seg.shape, static_cast<std::uint32_t>(std::min(wa, wb)),
                               static_cast<std::uint32_t>(std::max(wa, wb))}, k);
        }
        using EdgeKey = std::pair<std::uint32_t, std::uint32_t>;
        auto exact_match = [&](const EdgeKey& key, std::uint32_t shape) -> std::int64_t {
            const auto it = exact.find({shape, key.first, key.second});
            return it == exact.end() ? -1 : static_cast<std::int64_t>(it->second);
        };
        auto piece_match = [&](const EdgeKey& key, std::uint32_t shape) -> std::int64_t {
            for (std::uint32_t k : au.by_shape[shape]) {
                const AuthoredSegment& seg = au.segments[k];
                if (on_segment(seg, weld_pos[key.first]) && on_segment(seg, weld_pos[key.second]))
                    return k;
            }
            return -1;
        };

        // Phase 1: edges between two faces of one recorded shape. The record
        // decides; an unlisted edge keeps the crease rule.
        std::vector<std::vector<EdgeKey>> pieces(au.segments.size());  // matched edges per segment
        std::vector<std::pair<std::uint32_t, std::uint32_t>> hard_corners;
        auto inserted = [&](const EdgeUse& u) {
            return m.indices[u.ca] >= au.original_vertices || m.indices[u.cb] >= au.original_vertices;
        };
        // This edge's lookups per shape, each worked out once: the exact
        // segment, and (only if some pair needs it) the piece segment.
        struct Lookup { std::uint32_t shape; std::int64_t exact, piece; bool piece_done; };
        auto record_piece = [&](std::int64_t k, const EdgeKey& key) {
            if (k < 0) return;
            auto& list = pieces[k];
            if (std::find(list.begin(), list.end(), key) == list.end()) list.push_back(key);
        };
        for (const auto& [key, uses] : edges) {
            std::vector<Lookup> lookups;
            for (std::size_t i = 0; i < uses.size(); ++i) {
                for (std::size_t j = i + 1; j < uses.size(); ++j) {
                    const std::uint32_t shape = tri_shape(uses[i].tri);
                    if (shape != tri_shape(uses[j].tri) || !au.recorded[shape]) continue;
                    auto it = std::find_if(lookups.begin(), lookups.end(),
                                           [&](const Lookup& l) { return l.shape == shape; });
                    if (it == lookups.end()) {
                        it = lookups.insert(lookups.end(), {shape, exact_match(key, shape), -1, false});
                        record_piece(it->exact, key);
                    }
                    std::int64_t seg = it->exact;
                    if (seg < 0 && (inserted(uses[i]) || inserted(uses[j]))) {
                        if (!it->piece_done) {
                            it->piece = piece_match(key, shape);
                            it->piece_done = true;
                            record_piece(it->piece, key);
                        }
                        seg = it->piece;
                    }
                    if (seg < 0) {
                        join(uses[i], uses[j], false);
                    } else if (au.segments[seg].hard) {
                        hard_corners.push_back({uses[i].ca, uses[j].ca});
                        hard_corners.push_back({uses[i].cb, uses[j].cb});
                    } else {
                        join(uses[i], uses[j], true);
                    }
                }
            }
        }
        // Corners a hard edge separates after phase 1 must stay apart.
        for (const auto& [c1, c2] : hard_corners) {
            const std::uint32_t r1 = find(c1).first, r2 = find(c2).first;
            if (r1 == r2) continue;  // joined round the fan: Blender joins them too
            forbid[r1].push_back(r2);
            forbid[r2].push_back(r1);
        }
        // Phase 2: every other edge, crease rule, through the cannot-link sets.
        for (const auto& [key, uses] : edges) {
            for (std::size_t i = 0; i < uses.size(); ++i) {
                for (std::size_t j = i + 1; j < uses.size(); ++j) {
                    const std::uint32_t sa = tri_shape(uses[i].tri), sb = tri_shape(uses[j].tri);
                    if (sa == sb && au.recorded[sa]) continue;  // phase 1's
                    if (sa != sb && au.joins_hard && (au.recorded[sa] || au.recorded[sb])) continue;
                    join(uses[i], uses[j], false);
                }
            }
        }

        // Outcome per authored edge: at each end, the matched edge touching
        // it must have exactly two faces of the segment's shape; joined = their
        // corners there share a group.
        if (au.report) {
            for (std::uint32_t k = 0; k < au.segments.size(); ++k) {
                const AuthoredSegment& seg = au.segments[k];
                SmoothingReport::Edge& row = au.report->edges[k];
                if (!seg.usable) continue;
                bool found = true;
                bool joined[2] = {false, false};
                const glm::vec3* ends[2] = {&seg.a, &seg.b};
                for (int x = 0; x < 2 && found; ++x) {
                    const std::int64_t w = weld_of(*ends[x]);
                    const auto piece = std::find_if(pieces[k].begin(), pieces[k].end(),
                        [&](const EdgeKey& e) { return e.first == w || e.second == w; });
                    if (w < 0 || piece == pieces[k].end()) { found = false; break; }
                    std::vector<std::uint32_t> corners;
                    for (const EdgeUse& use : edges.at(*piece))
                        if (tri_shape(use.tri) == seg.shape)
                            corners.push_back(piece->first == w ? use.ca : use.cb);
                    if (corners.size() != 2) { found = false; break; }
                    joined[x] = find(corners[0]).first == find(corners[1]).first;
                }
                row.found = found;
                row.joined_a = found && joined[0];
                row.joined_b = found && joined[1];
            }
        }
    }

    std::vector<glm::vec3> group_sum(tri_count * 3, glm::vec3(0.0f));
    std::vector<int> corner_sign(tri_count * 3, 1);
    std::vector<std::uint32_t> corner_root(tri_count * 3);
    for (std::uint32_t c = 0; c < tri_count * 3; ++c) {
        const auto [r, sign] = find(c);
        corner_root[c] = r;
        corner_sign[c] = sign;
        group_sum[r] += static_cast<float>(sign) * face_n[c / 3] * face_area[c / 3];
    }
    std::vector<glm::vec3> corner_n(tri_count * 3, glm::vec3(0.0f));
    for (std::uint32_t c = 0; c < tri_count * 3; ++c) {
        const glm::vec3& sum = group_sum[corner_root[c]];
        const float len = glm::length(sum);
        const glm::vec3& own = face_n[c / 3];
        corner_n[c] = len > 1e-12f ? static_cast<float>(corner_sign[c]) * sum / len
                    : (glm::length(own) > 0.5f ? own : glm::vec3(0, 0, 1));
    }

    // One normal per vertex: corners of the same vertex that disagree get
    // their own copy of the vertex.
    std::vector<std::vector<std::uint32_t>> variants(m.vertices.size());
    std::vector<bool> assigned(m.vertices.size(), false);
    for (std::uint32_t c = 0; c < tri_count * 3; ++c) {
        const std::uint32_t v = m.indices[c];
        const glm::vec3& n = corner_n[c];
        if (!assigned[v]) {
            m.vertices[v].normal = n;
            assigned[v] = true;
            variants[v].push_back(v);
            continue;
        }
        std::uint32_t found = UINT32_MAX;
        for (std::uint32_t cand : variants[v])
            if (glm::dot(m.vertices[cand].normal, n) > 0.9999f) { found = cand; break; }
        if (found == UINT32_MAX) {
            found = ch.duplicate(v);
            m.vertices[found].normal = n;
            variants[v].push_back(found);
        }
        m.indices[c] = found;
    }
    for (std::size_t v = 0; v < assigned.size(); ++v)
        if (!assigned[v]) m.vertices[v].normal = glm::vec3(0, 0, 1);  // unreferenced
}

void repair_t_junctions_impl(VertexChannels& ch) {
    MeshCpu& m = ch.mesh;
    // Distinct positions: the candidates that may lie inside an edge.
    std::vector<glm::vec3> points;
    {
        std::map<PosKey, bool> seen;
        for (const auto& v : m.vertices)
            if (seen.try_emplace(pos_key(v.position), true).second)
                points.push_back(v.position);
    }

    // Uniform grid over the candidates (~4 per cell on average, at most 512
    // cells per axis) so an edge only tests the points in the cells its
    // tolerance-padded box covers. A brute-force scan is O(points x edges):
    // ~1.8 s of DBridge's interior load in Debug. The grid is purely a
    // candidate FILTER — the exact inside-edge test below is unchanged, and
    // the hits are returned in `points` order, as the scan returned them (the
    // split picks the middle pending point, so order is topology).
    // Non-finite points never pass the exact test, so they are not binned.
    glm::vec3 lo(std::numeric_limits<float>::max());
    glm::vec3 hi(-std::numeric_limits<float>::max());
    std::size_t finite = 0;
    for (const auto& p : points) {
        if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z)) continue;
        lo = glm::min(lo, p);
        hi = glm::max(hi, p);
        ++finite;
    }
    if (finite == 0) lo = hi = glm::vec3(0.0f);
    const glm::vec3 ext = glm::max(hi - lo, glm::vec3(1e-6f));
    const float vol_cell = ext.x * ext.y * ext.z * 4.0f
                           / static_cast<float>(std::max<std::size_t>(finite, 1));
    const float cell = std::max({std::cbrt(vol_cell), ext.x / 512.0f, ext.y / 512.0f,
                                 ext.z / 512.0f, 1e-4f});
    const glm::ivec3 dims = glm::ivec3(glm::floor(ext / cell)) + 1;
    auto cell_of = [&](const glm::vec3& p) {
        return glm::clamp(glm::ivec3(glm::floor((p - lo) / cell)), glm::ivec3(0), dims - 1);
    };
    auto bin_key = [&](const glm::ivec3& c) {
        return (static_cast<std::int64_t>(c.z) * dims.y + c.y) * dims.x + c.x;
    };
    std::unordered_map<std::int64_t, std::vector<std::uint32_t>> bins;
    for (std::uint32_t i = 0; i < points.size(); ++i) {
        const glm::vec3& p = points[i];
        if (!std::isfinite(p.x) || !std::isfinite(p.y) || !std::isfinite(p.z)) continue;
        bins[bin_key(cell_of(p))].push_back(i);
    }

    // Points strictly inside edge a->b: parameter u in (eps, 1-eps) and a
    // perpendicular distance under 1e-3 of the edge length.
    std::vector<std::uint32_t> hits;
    auto points_inside = [&](const glm::vec3& a, const glm::vec3& b) {
        std::vector<glm::vec3> found;
        const glm::vec3 ab = b - a;
        const float len2 = glm::dot(ab, ab);
        if (!(len2 >= 1e-12f) || !std::isfinite(len2)) return found;
        const float tol = 1e-3f * std::sqrt(len2);
        // Any hit lies within tol of the segment; pad by 2 tol so float
        // rounding in the exact test can never put a hit outside the box.
        const glm::vec3 pad(2.0f * tol);
        const glm::ivec3 c0 = cell_of(glm::min(a, b) - pad);
        const glm::ivec3 c1 = cell_of(glm::max(a, b) + pad);
        hits.clear();
        for (int z = c0.z; z <= c1.z; ++z)
            for (int y = c0.y; y <= c1.y; ++y)
                for (int x = c0.x; x <= c1.x; ++x) {
                    const auto it = bins.find(bin_key({x, y, z}));
                    if (it == bins.end()) continue;
                    for (std::uint32_t i : it->second) {
                        const glm::vec3& p = points[i];
                        const float u = glm::dot(p - a, ab) / len2;
                        if (u <= 1e-3f || u >= 1.0f - 1e-3f) continue;
                        if (glm::length(p - a - u * ab) < tol) hits.push_back(i);
                    }
                }
        std::sort(hits.begin(), hits.end());
        found.reserve(hits.size());
        for (std::uint32_t i : hits) found.push_back(points[i]);
        return found;
    };
    auto param = [](const glm::vec3& a, const glm::vec3& b, const glm::vec3& p) {
        const glm::vec3 ab = b - a;
        return glm::dot(p - a, ab) / glm::dot(ab, ab);
    };

    // New vertex on edge a->b at parameter u, carrying the triangle's own
    // attributes interpolated along the edge; position is the T vertex's.
    auto insert = [&](std::uint32_t a, std::uint32_t b, float u, const glm::vec3& p) {
        // Interpolate with the endpoints in a FIXED order (lexicographic by
        // position), recomputing u for that order. Both triangles sharing
        // this edge walk it in opposite directions; without a canonical order
        // their interpolated attributes (incl. the joint pass's local
        // positions) differ in the last bit and the shared edge cracks.
        const glm::vec3& pa = m.vertices[a].position;
        const glm::vec3& pb = m.vertices[b].position;
        if (std::lexicographical_compare(&pb.x, &pb.x + 3, &pa.x, &pa.x + 3)) {
            std::swap(a, b);
            u = param(m.vertices[a].position, m.vertices[b].position, p);
        }
        const std::uint32_t v = ch.interpolate(a, b, u);
        m.vertices[v].position = p;
        return v;
    };

    // Each work item carries, per edge, the T points still to insert on it.
    // Only the triangle's ORIGINAL edges are searched: a diagonal created by a
    // split starts empty, because a vertex on it lies inside the face
    // (overlapping geometry), not on a neighbour's edge.
    struct Work {
        std::array<std::uint32_t, 3> v;
        std::array<std::vector<glm::vec3>, 3> pts;
    };
    std::vector<std::uint32_t> out;
    out.reserve(m.indices.size());
    for (std::size_t t = 0; t < m.indices.size() / 3; ++t) {
        Work first;
        first.v = {m.indices[t * 3], m.indices[t * 3 + 1], m.indices[t * 3 + 2]};
        for (int e = 0; e < 3; ++e)
            first.pts[e] = points_inside(m.vertices[first.v[e]].position,
                                         m.vertices[first.v[(e + 1) % 3]].position);
        std::vector<Work> work = {std::move(first)};
        while (!work.empty()) {
            Work w = std::move(work.back());
            work.pop_back();
            int k = -1;
            for (int e = 0; e < 3; ++e) if (!w.pts[e].empty()) { k = e; break; }
            if (k < 0) {
                out.insert(out.end(), w.v.begin(), w.v.end());
                continue;
            }
            const std::uint32_t a = w.v[k], b = w.v[(k + 1) % 3], c = w.v[(k + 2) % 3];
            const glm::vec3 pa = m.vertices[a].position, pb = m.vertices[b].position;
            const glm::vec3 p = w.pts[k][w.pts[k].size() / 2];
            const float u = param(pa, pb, p);
            std::vector<glm::vec3> lo, hi;
            for (const auto& q : w.pts[k]) {
                if (q == p) continue;
                (param(pa, pb, q) < u ? lo : hi).push_back(q);
            }
            const std::uint32_t v = insert(a, b, u, p);
            // Same winding as (a, b, c).
            Work w1{{a, v, c}, {std::move(lo), {}, w.pts[(k + 2) % 3]}};
            Work w2{{v, b, c}, {std::move(hi), w.pts[(k + 1) % 3], {}}};
            work.push_back(std::move(w1));
            work.push_back(std::move(w2));
        }
    }
    m.indices = std::move(out);
}

// Shape-frame position -> shared model space, snapped (1/1024 unit) so
// coincident vertices from different node frames weld despite float
// round-off in the transform.
glm::vec3 to_shared(const glm::mat4& xf, const glm::vec3& p) {
    const glm::vec3 q = glm::vec3(xf * glm::vec4(p, 1.0f));
    return glm::round(q * 1024.0f) / 1024.0f;
}

}  // namespace

void generate_smooth_normals(MeshCpu& mesh, float crease_deg,
                             const std::vector<glm::vec4>& source_colours) {
    std::vector<glm::vec4> colours =
        source_colours.size() == mesh.vertices.size() ? source_colours
                                                      : std::vector<glm::vec4>{};
    VertexChannels ch{mesh, colours, nullptr};
    smooth_normals_impl(ch, crease_deg);
}

void repair_t_junctions(MeshCpu& mesh, std::vector<glm::vec4>& source_colours) {
    // Colours that are not parallel to the vertices are left as they are.
    std::vector<glm::vec4> none;
    auto& colours = source_colours.size() == mesh.vertices.size() ? source_colours : none;
    VertexChannels ch{mesh, colours, nullptr};
    repair_t_junctions_impl(ch);
}

void generate_normals_across_shapes(std::vector<NormalGenShape>& shapes, float crease_deg,
                                    SmoothingReport* report, bool authored_joins_hard) {
    std::size_t max_extra = 0;
    for (const auto& s : shapes)
        if (s.mesh) max_extra = std::max(max_extra, s.mesh->extra_uvs.size());

    // One combined mesh in the shared space. Each shape's real extra-UV sets
    // are padded to the common count; provenance (owner shape, own-frame
    // position) rides in `origins`, grown in lockstep with the vertices.
    MeshCpu all;
    all.extra_uvs.assign(max_extra, {});
    std::vector<glm::vec4> src;
    std::vector<VertexOrigin> origins;
    for (std::size_t s = 0; s < shapes.size(); ++s) {
        if (!shapes[s].mesh) continue;
        const MeshCpu& m = *shapes[s].mesh;
        const glm::mat4& xf = shapes[s].to_model;
        const auto& cols = shapes[s].source_colours;
        const auto base = static_cast<std::uint32_t>(all.vertices.size());
        for (std::size_t v = 0; v < m.vertices.size(); ++v) {
            MeshCpu::Vertex cv = m.vertices[v];
            cv.position = to_shared(xf, cv.position);
            all.vertices.push_back(cv);
            for (std::size_t c = 0; c < max_extra; ++c)
                all.extra_uvs[c].push_back(c < m.extra_uvs.size() && v < m.extra_uvs[c].size()
                                           ? m.extra_uvs[c][v] : glm::vec2(0.0f));
            src.push_back(v < cols.size() ? cols[v] : glm::vec4(m.vertices[v].color) / 255.0f);
            origins.push_back({static_cast<std::uint32_t>(s), m.vertices[v].position});
        }
        for (std::uint32_t idx : m.indices) all.indices.push_back(base + idx);
    }
    // Authored segments, taken to the shared space BEFORE the repair splits
    // any of them. One report row per authored edge, in the same order, even
    // for a shape with no mesh or a pass with no geometry (found = false).
    AuthoredSmoothing authored;
    authored.by_shape.resize(shapes.size());
    authored.recorded.assign(shapes.size(), false);
    authored.original_vertices = static_cast<std::uint32_t>(all.vertices.size());
    authored.joins_hard = authored_joins_hard;
    authored.report = report;
    if (report) report->edges.clear();
    for (std::size_t s = 0; s < shapes.size(); ++s) {
        if (!shapes[s].authored) continue;
        const MeshCpu* mesh = shapes[s].mesh;
        authored.recorded[s] = mesh != nullptr;
        const glm::mat4& xf = shapes[s].to_model;
        const auto shape = static_cast<std::uint32_t>(s);
        auto add = [&](const std::vector<std::array<std::uint16_t, 2>>& pairs, bool hard) {
            for (const auto& [a, b] : pairs) {
                AuthoredSegment seg{shape, {}, {}, hard,
                                    mesh && a < mesh->vertices.size() && b < mesh->vertices.size()};
                if (seg.usable) {
                    seg.a = to_shared(xf, mesh->vertices[a].position);
                    seg.b = to_shared(xf, mesh->vertices[b].position);
                    seg.usable = seg.a != seg.b;
                }
                if (seg.usable)
                    authored.by_shape[s].push_back(static_cast<std::uint32_t>(authored.segments.size()));
                authored.segments.push_back(seg);
                if (report) report->edges.push_back({shape, a, b, false, false, false});
            }
        };
        add(shapes[s].authored->hard, true);
        add(shapes[s].authored->soft, false);
    }
    if (all.vertices.empty()) return;
    const bool any_recorded =
        std::find(authored.recorded.begin(), authored.recorded.end(), true) != authored.recorded.end();

    VertexChannels ch{all, src, &origins};
    repair_t_junctions_impl(ch);
    smooth_normals_impl(ch, crease_deg, any_recorded ? &authored : nullptr);

    // Split back into the original shapes, in their own frames.
    for (std::size_t s = 0; s < shapes.size(); ++s) {
        if (!shapes[s].mesh) continue;
        MeshCpu& m = *shapes[s].mesh;
        const glm::mat4& xf = shapes[s].to_model;
        const glm::mat3 to_local = glm::transpose(glm::mat3(xf));
        const std::size_t own_extra = m.extra_uvs.size();
        // Exact local position of this shape's ORIGINAL vertices, keyed by
        // their snapped shared-space position. A vertex the repair inserted
        // at one of those points takes it verbatim, so it meets the T vertex
        // with no gap (interpolating along the split edge would land a hair
        // off it and crack).
        std::map<PosKey, glm::vec3> own_local;
        for (const auto& v : m.vertices)
            own_local.try_emplace(pos_key(to_shared(xf, v.position)), v.position);

        std::vector<std::int64_t> remap(all.vertices.size(), -1);
        MeshCpu out;
        out.extra_uvs.assign(own_extra, {});
        for (std::size_t c = 0; c + 2 < all.indices.size(); c += 3) {
            if (origins[all.indices[c]].shape != s) continue;
            for (int k = 0; k < 3; ++k) {
                const std::uint32_t cv = all.indices[c + k];
                if (remap[cv] < 0) {
                    remap[cv] = static_cast<std::int64_t>(out.vertices.size());
                    MeshCpu::Vertex v = all.vertices[cv];
                    auto own = own_local.find(pos_key(all.vertices[cv].position));
                    v.position = own != own_local.end() ? own->second
                                                        : origins[cv].local_pos;
                    v.normal = glm::normalize(to_local * v.normal);
                    out.vertices.push_back(v);
                    for (std::size_t e = 0; e < own_extra; ++e)
                        out.extra_uvs[e].push_back(all.extra_uvs[e][cv]);
                }
                out.indices.push_back(static_cast<std::uint32_t>(remap[cv]));
            }
        }
        m.vertices = std::move(out.vertices);
        m.indices = std::move(out.indices);
        m.extra_uvs = std::move(out.extra_uvs);
    }
}

}  // namespace assets::detail
