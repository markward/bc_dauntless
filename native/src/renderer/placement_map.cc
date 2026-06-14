#include "renderer/placement_map.h"

#include <unordered_map>

namespace renderer {

std::optional<Placement> placement_for_location(std::string_view loc) {
    // Transcribed in full from CommonAnimations.SetPosition (sdk lines 157-297).
    // hidden == true iff the SDK branch also calls pCharacter.SetHidden(1).
    static const std::unordered_map<std::string, Placement> kMap = {
        // D-Bridge Locations
        {"DBHelm",       {"data/animations/db_stand_h_m.nif", false}},
        {"DBTactical",   {"data/animations/db_stand_t_l.nif", false}},
        {"DBCommander",  {"data/animations/db_stand_c_m.nif", false}},
        {"DBCommander1", {"data/animations/DB_C1toC_M.nif",   false}},
        // Science/Engineer use "station-to-L1" MOVEMENT clips: the officer is
        // AT the station at t=0 (sample_at_start), then walks to L1.
        {"DBScience",    {"data/animations/db_StoL1_S.nif",   false, true}},
        {"DBEngineer",   {"data/animations/db_EtoL1_s.nif",   false, true}},
        {"DBGuest",      {"data/animations/Seated_P.nif",     false}},
        {"DBL1S",        {"data/animations/DB_L1toE_S.nif",   true}},
        {"DBL1M",        {"data/animations/DB_L1toG1_M.nif",  true}},
        {"DBL1L",        {"data/animations/DB_L1toT_L.nif",   true}},

        // E-Bridge Locations
        {"EBHelm",       {"data/animations/EB_stand_h_m.nif", false}},
        {"EBTactical",   {"data/animations/EB_stand_t_l.nif", false}},
        {"EBCommander",  {"data/animations/EB_stand_c_m.nif", false}},
        {"EBCommander1", {"data/animations/EB_C1toC_M.nif",   false}},
        {"EBScience",    {"data/animations/EB_stand_s_s.nif", false}},
        {"EBEngineer",   {"data/animations/EB_stand_e_s.nif", false}},
        {"EBGuest",      {"data/animations/EB_stand_X_m.nif", false}},
        {"EBL1S",        {"data/animations/EB_L1toE_S.nif",   true}},
        {"EBL1M",        {"data/animations/EB_L1toH_M.nif",   true}},
        {"EBL1L",        {"data/animations/EB_L1toT_L.nif",   true}},
        {"EBL2M",        {"data/animations/EB_L2toG2_M.nif",  true}},
        {"EBG1M",        {"data/animations/EB_G1toL2_M.nif",  false}},
        {"EBG2M",        {"data/animations/EB_G2toL2_M.nif",  false}},
        // NB: SDK key "EBG3M" loads EB_G3toL1_M.nif (anim NAME differs from
        // the file: file is EB_G32toL1_M.nif, registered under "EB_G3toL1_M").
        {"EBG3M",        {"data/animations/EB_G32toL1_M.nif", false}},

        // Partial Set Locations (cutscene / guest seating)
        {"CardassianSeated",        {"data/animations/CardassianSeated01.NIF",      false}},
        {"CardassianStationSeated", {"data/animations/CardStationSeated01.NIF",     false}},
        {"FederationOutpostSeated",  {"data/animations/FedOutpostSeated01.NIF",     false}},
        {"FederationOutpostSeated2", {"data/animations/FedOutpostSeated02.NIF",     false}},
        {"FederationOutpostSeated3", {"data/animations/FedOutpostSeated03.NIF",     false}},
        {"FerengiSeated",           {"data/animations/FerengiSeated01.NIF",         false}},
        {"GalaxyEngSeated",         {"data/animations/GalaxyEngSeated01.NIF",       false}},
        {"GalaxySeated",            {"data/animations/GalaxySeated01.NIF",          false}},
        {"KessokSeated",            {"data/animations/KessokSeated01.NIF",          false}},
        {"KlingonSeated",           {"data/animations/KlingonSeated01.NIF",         false}},
        {"MiscEngSeated",           {"data/animations/MiscEng01.NIF",               false}},
        {"MiscEngSeated2",          {"data/animations/MiscEng02.NIF",               false}},
        {"RomulanSeated",           {"data/animations/RomulanSeated01.NIF",         false}},
        {"ShuttleSeated",           {"data/animations/ShuttleSeated01.NIF",         false}},
        {"ShuttleSeated2",          {"data/animations/ShuttleSeated02.NIF",         false}},
        {"SovereignEngSeated",      {"data/animations/SovereignEngSeated01.NIF",    false}},
        {"SovereignSeated",         {"data/animations/SovereignSeated01.NIF",       false}},
        {"StarbaseSeated",          {"data/animations/StarbaseSeated01.NIF",        false}},
        {"StarbaseSeated2",         {"data/animations/StarbaseSeated02.NIF",        false}},
    };

    auto it = kMap.find(std::string(loc));
    if (it == kMap.end()) return std::nullopt;
    return it->second;
}

}  // namespace renderer
