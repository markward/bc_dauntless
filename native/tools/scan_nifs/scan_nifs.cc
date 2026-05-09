// native/tools/scan_nifs/scan_nifs.cc
//
// Walks a directory tree, runs nif::load on every .nif file, and reports
// per-file outcomes (EOF reached, blocks parsed, error or stopping block
// type). Used to gauge parser coverage across the BC asset corpus.
//
// Usage:
//   scan_nifs <root-directory>
//
// Output is grouped by outcome with a summary at the end.

#include <nif/file.h>

#include <algorithm>
#include <cstdio>
#include <exception>
#include <filesystem>
#include <map>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct Result {
    fs::path path;
    bool ok = false;          // nif::load returned without throwing
    bool eof = false;
    std::size_t blocks = 0;
    std::string stopped_at;   // populated when walker stopped on unknown type
    std::string error;        // populated when nif::load threw
};

bool is_nif(const fs::path& p) {
    auto ext = p.extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    return ext == ".nif";
}

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: %s <root-directory>\n", argv[0]);
        return 2;
    }
    fs::path root = argv[1];
    if (!fs::is_directory(root)) {
        std::fprintf(stderr, "not a directory: %s\n", root.string().c_str());
        return 2;
    }

    std::vector<Result> results;
    for (auto& entry : fs::recursive_directory_iterator(root)) {
        if (!entry.is_regular_file()) continue;
        if (!is_nif(entry.path())) continue;
        Result r;
        r.path = entry.path();
        try {
            auto f = nif::load(r.path);
            r.ok = true;
            r.eof = f.eof_reached;
            r.blocks = f.blocks.size();
            r.stopped_at = f.stopped_at_block_type;
        } catch (const std::exception& e) {
            r.error = e.what();
        }
        results.push_back(std::move(r));
    }

    std::sort(results.begin(), results.end(),
              [](auto const& a, auto const& b) { return a.path < b.path; });

    std::size_t total = results.size();
    std::size_t eof = 0, threw = 0, stuck = 0;
    std::map<std::string, std::vector<fs::path>> by_stop_type;
    std::map<std::string, std::size_t> error_count;

    for (auto& r : results) {
        if (r.eof) {
            ++eof;
        } else if (!r.ok) {
            ++threw;
            ++error_count[r.error];
        } else {
            ++stuck;
            by_stop_type[r.stopped_at].push_back(r.path);
        }
    }

    auto rel = [&](const fs::path& p) {
        std::error_code ec;
        auto r = fs::relative(p, root, ec);
        return ec ? p.string() : r.string();
    };

    std::printf("=== scanned %zu .nif files under %s ===\n", total, root.string().c_str());
    std::printf("  reached End Of File: %zu\n", eof);
    std::printf("  walker stuck on unknown block type: %zu\n", stuck);
    std::printf("  threw exception during load: %zu\n", threw);
    std::printf("\n");

    if (!by_stop_type.empty()) {
        std::printf("--- stops grouped by missing block type ---\n");
        std::vector<std::pair<std::string, std::size_t>> sorted_types;
        for (auto& kv : by_stop_type) {
            sorted_types.emplace_back(kv.first, kv.second.size());
        }
        std::sort(sorted_types.begin(), sorted_types.end(),
                  [](auto const& a, auto const& b) { return a.second > b.second; });
        for (auto& [type, count] : sorted_types) {
            std::printf("  %4zu files stop on %s\n", count, type.c_str());
        }
        std::printf("\n");
    }

    if (!error_count.empty()) {
        std::printf("--- exceptions grouped by message ---\n");
        for (auto& [msg, count] : error_count) {
            std::printf("  %zu: %s\n", count, msg.c_str());
        }
        std::printf("\n");
    }

    // Per-file detail for non-EOF outcomes (verbose). Keeps successes silent.
    if (stuck > 0 || threw > 0) {
        std::printf("--- per-file (non-EOF) ---\n");
        for (auto& r : results) {
            if (r.eof) continue;
            if (r.ok) {
                std::printf("  %s: stuck @ block %zu, type=%s\n",
                            rel(r.path).c_str(), r.blocks, r.stopped_at.c_str());
            } else {
                std::printf("  %s: ERROR: %s\n",
                            rel(r.path).c_str(), r.error.c_str());
            }
        }
    }

    return (eof == total) ? 0 : 1;
}
