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
        { root / "game/data/Models/Ships/Galaxy/Galaxy.nif",                              "Galaxy" },
        { root / "game/data/Models/Bases/CardStarbase/CardStarbase.nif",                  "CardStarbase" },
        { root / "game/data/Models/Characters/Bodies/BodyKlingon/BodyKlingon.nif",        "BodyKlingon" },
        { root / "game/data/Models/Sets/EBridge/EBridge.nif",                             "EBridge" },
    };
    return v;
}
