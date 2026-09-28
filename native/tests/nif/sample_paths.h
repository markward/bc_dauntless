// native/tests/nif/sample_paths.h
#pragma once

#include <filesystem>
#include <ostream>
#include <string>
#include <vector>
#include "support/content_root.h"

#ifndef OPEN_STBC_PROJECT_ROOT
#error "OPEN_STBC_PROJECT_ROOT must be defined by CMake"
#endif

struct SampleFile {
    std::filesystem::path path;
    std::string nickname;
};

// gtest_discover_tests names each parameterised ctest case by the PRINTED
// value. Without this a SampleFile prints as a raw byte dump that includes
// pointer bytes, so the ctest name changed run to run and could never be
// baselined in tests/known_failures.txt.
inline void PrintTo(const SampleFile& s, std::ostream* os) { *os << s.nickname; }

inline const std::vector<SampleFile>& kSampleFiles() {
    static const std::filesystem::path root{test_support::game_root()};
    static const std::vector<SampleFile> v = {
        // v3.1 archetypes — the four files the spec ship gate covers.
        { root / "data/Models/Ships/Galaxy/Galaxy.nif",                              "Galaxy" },
        { root / "data/Models/Bases/CardStarbase/CardStarbase.nif",                  "CardStarbase" },
        { root / "data/Models/Characters/Bodies/BodyKlingon/BodyKlingon.nif",        "BodyKlingon" },
        { root / "data/Models/Sets/EBridge/EBridge.nif",                             "EBridge" },
        // v3.0 regression: BC's planet/environment NIFs use the older
        // version. Exercises v3.0-only fields (NiTextureProperty.unknown_ints_2)
        // and the absent v3.1-only fields (NiImage.unknown_float,
        // NiTextureModeProperty PS2 L/K, NiTriShapeData match groups).
        { root / "data/Models/Environment/earth.NIF",                                "earth_v30" },
    };
    return v;
}
