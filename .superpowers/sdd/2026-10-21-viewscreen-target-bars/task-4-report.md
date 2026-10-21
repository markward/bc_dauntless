# Task 4 report
Implemented bindings (set/clear_viewscreen_bars), renderer wrappers + _REQUIRED_BINDINGS, host_loop `_viewscreen_feed_target` / `drive_viewscreen_bars` + call site after `_select_viewscreen_source`, native global pass, CLAUDE.md row, spec status.
TDD: RED = 3 new tests failing (AttributeError missing wrappers/_viewscreen_feed_target/drive_viewscreen_bars); GREEN after implementation: 52 passed (7 listed files), gtest 11 passed (ViewscreenBarsPass*/ViewscreenStaticPass*), binding manifest tests 23 passed.
Native: load_font once next to g_viewscreen_static_pass creation (project_asset_root()/fonts/viewscreen_antonio.json); reset at shutdown. render() after static overlay inside `if (viewscreen_on)`, guarded `!g_comm_source.active && g_scene_source.active && bars.visible`; viewport ensured by `g_viewscreen_hdr->bind()` + `glViewport(0,0,640,360)`.
Concerns: not live-verified; bars are not cleared natively when bridge is off (render is gated by viewscreen_on anyway).

## Final-review fix wave

1. Lazy font load: removed the init-time `load_font` in host_bindings.cc; added `ViewscreenBarsPass::ensure_font(asset_root)` (one attempt per distinct root, no per-frame retry, log-once kept), called before `render` in the scene-feed bars block with `project_asset_root()`. Test: gtest `ViewscreenBarsPass.EnsureFontAttemptsOncePerDistinctRoot` (bad root fails and is not retried, new good root loads).
2. Game-loop call pinned: new tests/host/test_viewscreen_bars_game_loop_call.py (ast over `host_loop.run`: single drive call, after `_select_viewscreen_source`, third arg is `_viewscreen_feed_target(player) if _vs_src == "scene" else None`). Mutation proof: cp backup of engine/host_loop.py, deleted the drive call -> test FAILED (1 failed, assertion at line 27), restored by cp, diff byte-identical.
3. Radius clamp now `0.5f * band_h` in viewscreen_bars_pass.cc.

Commands: `cmake --build build -j` (ok); `uv run pytest tests/host/test_render_space_feeds.py tests/host/test_viewscreen_bars_game_loop_call.py tests/unit/test_host_loop_viewscreen_drive.py tests/host/test_viewscreen_scene_feed.py -q` -> 37 passed; `./build/native/tests/renderer/renderer_tests --gtest_filter='ViewscreenBarsPass*:ViewscreenStaticPass*'` -> 12 passed.
