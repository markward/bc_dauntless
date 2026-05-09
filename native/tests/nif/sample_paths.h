// native/tests/nif/sample_paths.h
#pragma once

#include <filesystem>
#include <string>
#include <vector>

#ifndef OPEN_STBC_PROJECT_ROOT
#error "OPEN_STBC_PROJECT_ROOT must be defined by CMake"
#endif

struct SampleFile {
    std::filesystem::path path;
    std::string nickname;
};

inline const std::vector<SampleFile>& kSampleFiles() {
    static const std::filesystem::path root{OPEN_STBC_PROJECT_ROOT};
    static const std::vector<SampleFile> v = {
        // v3.1 archetypes — the four files the spec ship gate covers.
        { root / "game/data/Models/Ships/Galaxy/Galaxy.nif",                              "Galaxy" },
        { root / "game/data/Models/Bases/CardStarbase/CardStarbase.nif",                  "CardStarbase" },
        { root / "game/data/Models/Characters/Bodies/BodyKlingon/BodyKlingon.nif",        "BodyKlingon" },
        { root / "game/data/Models/Sets/EBridge/EBridge.nif",                             "EBridge" },
        // v3.0 regression: BC's planet/environment NIFs use the older
        // version. Exercises v3.0-only fields (NiTextureProperty.unknown_ints_2)
        // and the absent v3.1-only fields (NiImage.unknown_float,
        // NiTextureModeProperty PS2 L/K, NiTriShapeData match groups).
        { root / "game/data/Models/Environment/earth.NIF",                                "earth_v30" },
    };
    return v;
}
