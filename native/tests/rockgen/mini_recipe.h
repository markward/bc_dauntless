// native/tests/rockgen/mini_recipe.h
#pragma once

// The shared small recipe every rockgen test runs against: one family, two
// majors (subdivisions 3,2) and one fragment (subdivisions 2,1), at the
// catalogue's 100 m bound radius.
inline constexpr const char* kMini = R"({"tool_version":1,"seed":7,"bound_radius_m":100,
 "impostor_view_size":32,"volume_dims":16,
 "major":{"lod_subdivisions":[3,2],"texture_size":64},
 "fragment":{"lod_subdivisions":[2,1],"texture_size":32,"cuts":[2,4]},
 "families":[{"name":"silicate","majors":2,"fragments":1,"palette":[[0.4,0.4,0.4],[0.5,0.5,0.5]],
   "gloss":0.12,"displace":0.35,"octaves":5,"noise_scale":2.3,"axis":[0.7,1.3],"craters":[2,4],
   "crater_radius":[0.1,0.25],"detail_octaves":3,"detail_scale":7,"normal_strength":2.5}]})";
