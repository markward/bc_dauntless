// native/tools/voxel_inspect/parts_view.cc
//
// SPIKE (damage redesign): `voxel_inspect --parts <hull.nif> <out.bmp>
// [cells] [orient_tol_deg] [merge_tol_deg] [min_fraction]` -- runs voxel::detect_structure_parts, prints the
// part table and writes top / side / front views coloured by part, with each
// part's centre (white) and main axis (black) drawn on.
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <fstream>
#include <vector>

#include <voxel/structure_parts.h>
#include <voxel/voxelize.h>

namespace {

struct Img {
    int w = 0, h = 0;
    std::vector<unsigned char> rgb;
    void init(int W, int H) { w = W; h = H; rgb.assign(static_cast<std::size_t>(W) * H * 3, 24); }
    void put(int x, int y, float r, float g, float b) {
        if (x < 0 || y < 0 || x >= w || y >= h) return;
        unsigned char* p = &rgb[(static_cast<std::size_t>(y) * w + x) * 3];
        p[0] = static_cast<unsigned char>(std::clamp(r, 0.0f, 1.0f) * 255.0f);
        p[1] = static_cast<unsigned char>(std::clamp(g, 0.0f, 1.0f) * 255.0f);
        p[2] = static_cast<unsigned char>(std::clamp(b, 0.0f, 1.0f) * 255.0f);
    }
    void line(float x0, float y0, float x1, float y1, float r, float g, float b) {
        const int n = static_cast<int>(std::max(std::fabs(x1 - x0), std::fabs(y1 - y0))) + 1;
        for (int i = 0; i <= n; ++i) {
            const float t = static_cast<float>(i) / static_cast<float>(n);
            const int x = static_cast<int>(x0 + (x1 - x0) * t), y = static_cast<int>(y0 + (y1 - y0) * t);
            put(x, y, r, g, b);
            put(x + 1, y, r, g, b);
            put(x, y + 1, r, g, b);
        }
    }
    bool write_bmp(const char* path) const {
        std::ofstream f(path, std::ios::binary);
        if (!f) return false;
        const int row = (w * 3 + 3) & ~3;
        const int size = 54 + row * h;
        unsigned char hdr[54] = {'B', 'M'};
        auto le32 = [&](int off, int v) { for (int i = 0; i < 4; ++i) hdr[off + i] = (v >> (8 * i)) & 255; };
        le32(2, size); le32(10, 54); le32(14, 40); le32(18, w); le32(22, h);
        hdr[26] = 1; hdr[28] = 24; le32(34, row * h);
        f.write(reinterpret_cast<const char*>(hdr), 54);
        std::vector<unsigned char> buf(row, 0);
        for (int y = h - 1; y >= 0; --y) {          // BMP rows bottom-up; our y=0 is top
            for (int x = 0; x < w; ++x) {
                const unsigned char* p = &rgb[(static_cast<std::size_t>(y) * w + x) * 3];
                buf[x * 3 + 0] = p[2]; buf[x * 3 + 1] = p[1]; buf[x * 3 + 2] = p[0];
            }
            f.write(reinterpret_cast<const char*>(buf.data()), row);
        }
        return true;
    }
};

const float kPal[12][3] = {
    {0.90f, 0.30f, 0.25f}, {0.25f, 0.65f, 0.95f}, {0.35f, 0.85f, 0.35f}, {0.95f, 0.80f, 0.20f},
    {0.75f, 0.40f, 0.90f}, {0.20f, 0.85f, 0.80f}, {0.95f, 0.55f, 0.15f}, {0.60f, 0.60f, 0.60f},
    {0.95f, 0.45f, 0.70f}, {0.50f, 0.75f, 0.30f}, {0.40f, 0.45f, 0.95f}, {0.80f, 0.70f, 0.55f},
};

const char* kind_name(voxel::PartKind k) {
    switch (k) {
        case voxel::PartKind::Disc: return "disc";
        case voxel::PartKind::Cylinder: return "cylinder";
        default: return "box";
    }
}

}  // namespace

int run_parts(int argc, char** argv) {
    if (argc < 4) {
        std::fprintf(stderr, "--parts needs <hull.nif> <out.bmp> [cells] [orient_tol_deg] [merge_tol_deg] [min_fraction]\n");
        return 2;
    }
    voxel::StructureParams prm;
    if (argc > 4) prm.long_axis_cells = std::atoi(argv[4]);
    if (argc > 5) prm.orient_tol_deg = static_cast<float>(std::atof(argv[5]));
    if (argc > 6) prm.merge_axis_tol_deg = static_cast<float>(std::atof(argv[6]));
    if (argc > 7) prm.min_fraction = static_cast<float>(std::atof(argv[7]));
    const auto tris = voxel::collect_hull_triangles_from_source(argv[2]);
    if (tris.empty()) { std::fprintf(stderr, "no triangles in %s\n", argv[2]); return 1; }
    const voxel::StructureSegmentation seg = voxel::detect_structure_parts(tris, prm);
    const voxel::VoxelVolume& v = seg.vol;

    std::printf("hull %s\n  grid %dx%dx%d cell %.2f  solid %zu  parts %zu\n", argv[2],
                v.dims.x, v.dims.y, v.dims.z, v.cell.x, v.solid_count(), seg.parts.size());
    for (std::size_t i = 0; i < seg.parts.size(); ++i) {
        const auto& p = seg.parts[i];
        std::printf("  [%zu] %-8s vox %6d  centre (%7.1f %7.1f %7.1f)  axis0 (%5.2f %5.2f %5.2f)"
                    "  half (%6.1f %6.1f %6.1f)  peak %5.1f  s2/s1 %.2f s3/s2 %.2f\n",
                    i, kind_name(p.kind), p.voxels, p.centre.x, p.centre.y, p.centre.z,
                    p.axis[0].x, p.axis[0].y, p.axis[0].z,
                    p.half_extent.x, p.half_extent.y, p.half_extent.z, p.peak_depth,
                    p.spread.y / std::max(p.spread.x, 1e-6f), p.spread.z / std::max(p.spread.y, 1e-6f));
    }

    // Three orthographic views: top (look -Z; x right, y up), side (look -X;
    // y right, z up), front (look -Y from ahead; x right, z up).
    const int S = 4, gap = 12;
    struct View { int u, w, vax, nax; bool flip_u; };   // image u axis, image v axis, depth axis
    const View views[3] = {{0, 0, 1, 2, false}, {1, 0, 2, 0, false}, {0, 0, 2, 1, false}};
    int W = gap, H = 0;
    for (const View& vw : views) { W += v.dims[vw.u] * S + gap; H = std::max(H, v.dims[vw.vax] * S); }
    Img img;
    img.init(W, H + 2 * gap);
    int x0 = gap;
    for (const View& vw : views) {
        const int nu = v.dims[vw.u], nv = v.dims[vw.vax], nd = v.dims[vw.nax];
        for (int a = 0; a < nu; ++a) {
            for (int b = 0; b < nv; ++b) {
                for (int k = nd - 1; k >= 0; --k) {   // from the + side, nearest first
                    int c[3];
                    c[vw.u] = a; c[vw.vax] = b; c[vw.nax] = k;
                    const std::size_t idx = v.index(c[0], c[1], c[2]);
                    if (!v.occ[idx]) continue;
                    const int l = seg.label[idx];
                    const float shade = 0.45f + 0.55f * static_cast<float>(k) / std::max(nd - 1, 1);
                    const float* col = kPal[std::max(l, 0) % 12];
                    for (int py = 0; py < S; ++py)
                        for (int px = 0; px < S; ++px)
                            img.put(x0 + a * S + px, gap + (nv - 1 - b) * S + py,
                                    col[0] * shade, col[1] * shade, col[2] * shade);
                    break;
                }
            }
        }
        auto to_img = [&](glm::vec3 q, float& ix, float& iy) {
            const glm::vec3 g = (q - v.origin) / v.cell;
            ix = x0 + g[vw.u] * S;
            iy = gap + (nv - g[vw.vax]) * S;
        };
        for (const auto& p : seg.parts) {
            float cx, cy, ax, ay, bx, by;
            to_img(p.centre, cx, cy);
            to_img(p.centre + p.axis[0] * p.half_extent.x, ax, ay);
            to_img(p.centre - p.axis[0] * p.half_extent.x, bx, by);
            img.line(bx, by, ax, ay, 0.0f, 0.0f, 0.0f);
            for (int dy = -3; dy <= 3; ++dy)
                for (int dx = -3; dx <= 3; ++dx)
                    img.put(static_cast<int>(cx) + dx, static_cast<int>(cy) + dy, 1.0f, 1.0f, 1.0f);
        }
        x0 += nu * S + gap;
    }
    if (!img.write_bmp(argv[3])) { std::fprintf(stderr, "cannot write %s\n", argv[3]); return 1; }
    std::printf("  wrote %s (top | side | front)\n", argv[3]);
    return 0;
}
