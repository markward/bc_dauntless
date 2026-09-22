// native/tests/renderer/hull_cut_decision_sync_test.cc
//
// Drift guard for hull_cut_at() -- the ONE function that answers "was the hull
// cut away at this body-frame point" -- shared, by COPY, between opaque.frag
// (which discards there, or stamps the carve stencil) and breach.frag (whose
// interior shell must keep exactly what the hull did NOT cut).
//
// THIS GUARD EXISTS BECAUSE ITS ABSENCE SHIPPED A BUG. The shell originally
// tested the RAW damage field, which is not what opaque.frag cuts on: that
// file suppresses the field inside a tracked carve's dilated region and raises
// its threshold with rim noise. Wherever the brush reached plating the oblate
// did not cut -- routine, since the dilation is driven by the FIELD CELL
// rather than the carve radius -- the shell threw away plating the hull keeps.
// The result was a ONE-WAY hole: stars from above, intact hull from below,
// live-reported on the Galaxy's forward saucer. "The cut and the interior are
// two different shapes" is also the root cause of the original see-through
// bug, which is why this is worth a machine-checked guard rather than a
// comment.
//
// embed_shader (native/src/renderer/CMakeLists.txt:5-11) reads one shader file
// at a time, so the two shaders cannot literally #include a common snippet
// without a build-system change. Until that lands the function is duplicated
// verbatim, delimited by matching HULL_CUT_DECISION BEGIN / END markers.
//
// A pure text test -- no GL context -- because its whole job is to catch the
// moment someone edits one copy and not the other, which a GL-level test could
// never distinguish from "both copies still happen to behave the same here".

#include <gtest/gtest.h>

#include <filesystem>
#include <fstream>
#include <optional>
#include <sstream>
#include <string>
#include <vector>

namespace {

namespace fs = std::filesystem;

constexpr const char* kBeginMarker = "=== HULL_CUT_DECISION BEGIN ===";
constexpr const char* kEndMarker = "=== HULL_CUT_DECISION END ===";

std::vector<std::string> read_lines(const fs::path& path) {
    std::ifstream in(path);
    std::vector<std::string> lines;
    std::string line;
    while (std::getline(in, line)) {
        lines.push_back(line);
    }
    return lines;
}

// Extracts the lines strictly between a line containing kBeginMarker and the
// next line containing kEndMarker. Returns std::nullopt (with `*why` set to
// a human-readable reason) when the markers cannot be found unambiguously --
// this is what makes the guard fail LOUDLY instead of silently comparing two
// empty strings when a file has no block at all.
std::optional<std::string> extract_marked_block(const fs::path& path, std::string* why) {
    std::ifstream probe(path);
    if (!probe.good()) {
        *why = path.string() + ": file could not be opened";
        return std::nullopt;
    }
    std::vector<std::string> lines = read_lines(path);

    int begin_line = -1;
    int end_line = -1;
    for (size_t i = 0; i < lines.size(); ++i) {
        const bool has_begin = lines[i].find(kBeginMarker) != std::string::npos;
        const bool has_end = lines[i].find(kEndMarker) != std::string::npos;
        if (has_begin) {
            if (begin_line != -1) {
                *why = path.string() + ": more than one BEGIN marker (lines " +
                       std::to_string(begin_line + 1) + " and " + std::to_string(i + 1) +
                       ") -- extraction would be ambiguous";
                return std::nullopt;
            }
            begin_line = static_cast<int>(i);
        }
        if (has_end) {
            if (begin_line == -1) {
                *why = path.string() + ": END marker at line " + std::to_string(i + 1) +
                       " with no preceding BEGIN marker";
                return std::nullopt;
            }
            if (end_line != -1) {
                *why = path.string() +
                       ": more than one END marker after the BEGIN marker -- "
                       "extraction would be ambiguous";
                return std::nullopt;
            }
            end_line = static_cast<int>(i);
        }
    }

    if (begin_line == -1) {
        *why = path.string() +
               ": no HULL_CUT_DECISION BEGIN marker found -- the drift-guard "
               "block has not been delimited in this file";
        return std::nullopt;
    }
    if (end_line == -1) {
        *why = path.string() + ": BEGIN marker found at line " + std::to_string(begin_line + 1) +
               " but no matching END marker -- the drift-guard block is unterminated";
        return std::nullopt;
    }

    std::ostringstream out;
    for (int i = begin_line + 1; i < end_line; ++i) {
        out << lines[static_cast<size_t>(i)] << "\n";
    }
    return out.str();
}

fs::path shader_path(const char* rel) {
    return fs::path(OPEN_STBC_PROJECT_ROOT) / "native" / "src" / "renderer" / "shaders" / rel;
}

}  // namespace

TEST(HullCutDecisionDriftGuard, MarkersArePresentAndUnambiguousInBothFiles) {
    std::string why;
    auto opaque_block = extract_marked_block(shader_path("opaque.frag"), &why);
    ASSERT_TRUE(opaque_block.has_value()) << "opaque.frag hull-cut decision: " << why;

    auto breach_block = extract_marked_block(shader_path("breach.frag"), &why);
    ASSERT_TRUE(breach_block.has_value())
        << "breach.frag hull-cut decision: " << why
        << " -- breach.frag must carry a byte-identical copy of opaque.frag's "
           "hull_cut_at() -- the ONE function that answers 'was the hull cut "
           "away here' -- delimited by the same "
        << kBeginMarker << " / " << kEndMarker << " markers.";
}

TEST(HullCutDecisionDriftGuard, BlocksAreByteIdenticalAcrossBothShaders) {
    std::string why;
    auto opaque_block = extract_marked_block(shader_path("opaque.frag"), &why);
    ASSERT_TRUE(opaque_block.has_value()) << "opaque.frag: " << why;
    auto breach_block = extract_marked_block(shader_path("breach.frag"), &why);
    ASSERT_TRUE(breach_block.has_value()) << "breach.frag: " << why;

    if (*opaque_block == *breach_block) {
        SUCCEED();
        return;
    }

    // Walk both blocks line-by-line to report exactly where they diverge,
    // rather than dumping two multi-KB strings at the test runner.
    std::istringstream oi(*opaque_block);
    std::istringstream bi(*breach_block);
    std::string ol, bl;
    int line_no = 1;
    for (;;) {
        const bool ohas = static_cast<bool>(std::getline(oi, ol));
        const bool bhas = static_cast<bool>(std::getline(bi, bl));
        if (!ohas && !bhas) {
            break;
        }
        if (!ohas) {
            ADD_FAILURE() << "hull_cut_at() has drifted: breach.frag has "
                             "an extra line "
                          << line_no << " not present in opaque.frag:\n  \"" << bl << "\"";
            return;
        }
        if (!bhas) {
            ADD_FAILURE() << "hull_cut_at() has drifted: opaque.frag has "
                             "an extra line "
                          << line_no << " not present in breach.frag:\n  \"" << ol << "\"";
            return;
        }
        if (ol != bl) {
            ADD_FAILURE() << "hull_cut_at() has drifted at block-relative "
                             "line "
                          << line_no << ":\n  opaque.frag: \"" << ol << "\"\n  breach.frag: \""
                          << bl
                          << "\"\n"
                             "opaque.frag and breach.frag must carry byte-identical "
                             "hull_cut_at() between their "
                          << kBeginMarker << " / " << kEndMarker
                          << " markers -- someone edited one copy and not the other.";
            return;
        }
        ++line_no;
    }
}
