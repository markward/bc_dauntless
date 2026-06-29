// recover_lip_visemes — acoustic recovery of the BC .LIP code -> viseme table.
//
// BC's speaking model is OPENNESS-based (engine phoneme targets are
// MouthClosed / MouthOpenPartly / MouthOpen), not vowel-based. So each phoneme
// `code` is mapped along a closed->open axis from the one acoustic signal that
// survives cross-speaker pooling: loudness (open mouths are louder). For every
// game .LIP file we decode the paired MP3, measure each segment's RMS energy
// normalized to that line's loudest segment (per-file => per-speaker loudness
// normalization), and average per code. Per-code openness then maps to basis
// weights over {neutral, e, a}: closed->neutral, partly-open->e, wide-open->a.
// (No formant/vowel-color extraction — that axis does not survive pooling.)
//
// Output: engine/appc/lip_visemes.json.
// Build: cmake --build build --target recover_lip_visemes -j
// Run:   ./build/native/tools/recover_lip_visemes/recover_lip_visemes [out.json]

#include <audio/mp3.h>
#include <audio/wav.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using dauntless::audio::WavData;
using dauntless::audio::decode_mp3;

namespace {

struct Seg { int code; float start; float dur; };

std::vector<Seg> parse_lip(const fs::path& p) {
    std::vector<Seg> out;
    std::ifstream f(p, std::ios::binary);
    if (!f) return out;
    std::vector<char> b((std::istreambuf_iterator<char>(f)), {});
    if (b.size() % 12 != 0) return out;
    for (size_t off = 0; off + 12 <= b.size(); off += 12) {
        int32_t code; float start, dur;
        std::memcpy(&code, &b[off], 4);
        std::memcpy(&start, &b[off + 4], 4);
        std::memcpy(&dur, &b[off + 8], 4);
        out.push_back({code, start, dur});
    }
    return out;
}

// Decode an MP3 to mono float [-1,1]. Returns sample_rate (0 on failure).
uint32_t load_mono(const fs::path& mp3, std::vector<float>& out) {
    std::ifstream f(mp3, std::ios::binary);
    if (!f) return 0;
    std::vector<uint8_t> bytes((std::istreambuf_iterator<char>(f)), {});
    WavData w;
    if (!decode_mp3(bytes.data(), bytes.size(), w) || w.bits_per_sample != 16)
        return 0;
    const int16_t* s = reinterpret_cast<const int16_t*>(w.pcm.data());
    const size_t n = w.pcm.size() / 2;
    const int ch = w.channels ? w.channels : 1;
    out.clear();
    out.reserve(n / ch);
    for (size_t i = 0; i + ch <= n; i += ch) {
        int acc = 0;
        for (int c = 0; c < ch; ++c) acc += s[i + c];
        out.push_back(static_cast<float>(acc) / (ch * 32768.0f));
    }
    return w.sample_rate;
}

// RMS over [i0,i1).
double rms(const std::vector<float>& x, long i0, long i1) {
    if (i1 <= i0) return 0.0;
    double acc = 0.0;
    for (long i = i0; i < i1; ++i) acc += double(x[i]) * x[i];
    return std::sqrt(acc / (i1 - i0));
}

struct CodeStat { double sum_open = 0.0; long n = 0; long voiced = 0; };

}  // namespace

int main(int argc, char** argv) {
    const fs::path root = fs::path(__FILE__).parent_path().parent_path().parent_path().parent_path();
    const fs::path crew = root / "game" / "sfx" / "Bridge" / "Crew";
    const fs::path out_json = argc > 1 ? fs::path(argv[1])
                                       : root / "engine" / "appc" / "lip_visemes.json";
    if (!fs::is_directory(crew)) { std::fprintf(stderr, "no %s\n", crew.c_str()); return 1; }

    std::map<int, CodeStat> stats;
    long files = 0, missing = 0;
    for (auto& e : fs::recursive_directory_iterator(crew)) {
        if (!e.is_regular_file()) continue;
        std::string ext = e.path().extension().string();
        for (auto& c : ext) c = std::tolower(c);
        if (ext != ".lip") continue;
        fs::path mp3 = e.path(); mp3.replace_extension(".mp3");
        if (!fs::is_regular_file(mp3)) mp3.replace_extension(".MP3");
        if (!fs::is_regular_file(mp3)) { ++missing; continue; }
        std::vector<float> pcm;
        uint32_t fs_hz = load_mono(mp3, pcm);
        if (!fs_hz || pcm.empty()) continue;
        auto segs = parse_lip(e.path());
        if (segs.empty()) continue;
        ++files;

        // Per-segment RMS, then normalize by this line's loudest segment so
        // openness is relative WITHIN one speaker's line (removes per-speaker /
        // per-clip loudness offsets).
        std::vector<double> seg_rms(segs.size());
        double peak = 1e-9;
        for (size_t i = 0; i < segs.size(); ++i) {
            long i0 = std::max(0L, long(segs[i].start * fs_hz));
            long i1 = std::min<long>(pcm.size(), long((segs[i].start + segs[i].dur) * fs_hz));
            seg_rms[i] = rms(pcm, i0, i1);
            peak = std::max(peak, seg_rms[i]);
        }
        for (size_t i = 0; i < segs.size(); ++i) {
            double open = seg_rms[i] / peak;       // 0..1 relative loudness
            CodeStat& cs = stats[segs[i].code];
            cs.sum_open += open; cs.n += 1;
            if (seg_rms[i] > 0.01) cs.voiced += 1;
        }
    }
    std::fprintf(stderr, "decoded %ld files (%ld .LIP missing mp3), %zu codes\n",
                 files, missing, stats.size());

    // Per-code mean openness, then spread across codes to use the full [0,1].
    std::map<int, double> mean_open;
    double lo = 1e9, hi = -1e9;
    for (auto& [code, cs] : stats) {
        double m = cs.n ? cs.sum_open / cs.n : 0.0;
        mean_open[code] = m;
        if (cs.n > 0) { lo = std::min(lo, m); hi = std::max(hi, m); }  // skip empty codes
    }
    auto spread = [&](double m) {
        return hi > lo ? std::max(0.0, std::min(1.0, (m - lo) / (hi - lo))) : 0.0;
    };

    // openness o in [0,1] -> weights along neutral -> e -> a.
    auto weights = [](double o) {
        std::map<std::string, double> w;
        if (o < 0.5) { w["neutral"] = 1.0 - 2.0 * o; w["e"] = 2.0 * o; }
        else         { w["e"] = 2.0 - 2.0 * o;       w["a"] = 2.0 * o - 1.0; }
        for (auto it = w.begin(); it != w.end();) {
            if (it->second < 0.04) it = w.erase(it); else ++it;
        }
        double s = 0; for (auto& kv : w) s += kv.second;
        if (s <= 0) { w.clear(); w["neutral"] = 1.0; s = 1.0; }
        for (auto& kv : w) kv.second /= s;
        return w;
    };

    std::ofstream js(out_json);
    js << "{\n";
    js << "  \"_comment\": \"Acoustically-recovered code->viseme weights (tools/recover_lip_visemes). "
          "BC speaking is OPENNESS-based (MouthClosed/Partly/Open); each code's openness = mean per-file-"
          "normalized RMS loudness over all corpus segments, mapped neutral->e->a. code 0 = closed.\",\n";
    js << "  \"_basis\": [\"neutral\", \"a\", \"e\", \"u\"],\n";

    std::fprintf(stderr, "%-5s %8s %7s %8s   weights\n", "code", "meanOpen", "voiced%", "openness");
    bool first = true;
    for (auto& [code, cs] : stats) {
        // Gamma biases quiet pauses toward closure (per-file normalization
        // inflates low-energy room tone). code 0 is definitionally the engine's
        // closed/silence state -> force neutral.
        double o = std::pow(spread(mean_open[code]), 1.4);
        auto w = (code == 0) ? std::map<std::string, double>{{"neutral", 1.0}} : weights(o);
        std::fprintf(stderr, "%-5d %8.3f %6ld%% %8.2f   ", code, mean_open[code],
                     cs.n ? cs.voiced * 100 / cs.n : 0, o);
        for (auto& kv : w) std::fprintf(stderr, "%s=%.2f ", kv.first.c_str(), kv.second);
        std::fprintf(stderr, "\n");

        if (!first) js << ",\n";
        first = false;
        js << "  \"" << code << "\": {";
        bool fw = true;
        for (auto& kv : w) {
            if (!fw) js << ", ";
            fw = false;
            char buf[32]; std::snprintf(buf, sizeof buf, "%.3f", kv.second);
            js << "\"" << kv.first << "\": " << buf;
        }
        js << "}";
    }
    js << "\n}\n";
    std::fprintf(stderr, "wrote %s\n", out_json.c_str());
    return 0;
}
