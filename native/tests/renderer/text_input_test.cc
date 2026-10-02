#include <gtest/gtest.h>
#include <renderer/text_input.h>
#include <GLFW/glfw3.h>

using renderer::TextEvent;
using renderer::TextEventQueue;

TEST(TextInput, MapsEditingKeysToWindowsVk) {
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_BACKSPACE), 0x08);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_TAB), 0x09);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_ENTER), 0x0D);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_ESCAPE), 0x1B);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_END), 0x23);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_HOME), 0x24);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_LEFT), 0x25);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_UP), 0x26);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_RIGHT), 0x27);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_DOWN), 0x28);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_DELETE), 0x2E);
}

TEST(TextInput, NonEditingKeysMapToZero) {
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_A), 0);
    EXPECT_EQ(renderer::glfw_key_to_windows_vk(GLFW_KEY_F1), 0);
}

TEST(TextInput, QueueDrainsInOrderAndEmpties) {
    TextEventQueue q;
    q.push({renderer::kTextEventChar, 'a', 0, 1, 0});
    q.push({renderer::kTextEventKey, GLFW_KEY_BACKSPACE, 51, 1, 0});
    auto out = q.drain();
    ASSERT_EQ(out.size(), 2u);
    EXPECT_EQ(out[0].code, 'a');
    EXPECT_EQ(out[1].kind, renderer::kTextEventKey);
    EXPECT_EQ(q.size(), 0u);
}

TEST(TextInput, QueueIsBoundedDroppingOldest) {
    TextEventQueue q;
    for (int i = 0; i < 300; ++i) q.push({renderer::kTextEventChar, i, 0, 1, 0});
    auto out = q.drain();
    ASSERT_EQ(out.size(), TextEventQueue::kCapacity);
    EXPECT_EQ(out.front().code, 300 - static_cast<int>(TextEventQueue::kCapacity));
    EXPECT_EQ(out.back().code, 299);
}

using renderer::EditCommand;
using renderer::edit_command_for;

#if defined(__APPLE__)
constexpr int kPrimary = GLFW_MOD_SUPER;
constexpr int kWrong = GLFW_MOD_CONTROL;
#else
constexpr int kPrimary = GLFW_MOD_CONTROL;
constexpr int kWrong = GLFW_MOD_SUPER;
#endif

TEST(EditCommand, PrimaryModifierLetters) {
    EXPECT_EQ(edit_command_for('a', kPrimary), EditCommand::SelectAll);
    EXPECT_EQ(edit_command_for('c', kPrimary), EditCommand::Copy);
    EXPECT_EQ(edit_command_for('v', kPrimary), EditCommand::Paste);
    EXPECT_EQ(edit_command_for('x', kPrimary), EditCommand::Cut);
    EXPECT_EQ(edit_command_for('z', kPrimary), EditCommand::Undo);
    EXPECT_EQ(edit_command_for('y', kPrimary), EditCommand::Redo);
    EXPECT_EQ(edit_command_for('V', kPrimary), EditCommand::Paste);  // case-insensitive
}

TEST(EditCommand, ShiftZIsRedoAndOtherShiftLettersAreNothing) {
    EXPECT_EQ(edit_command_for('z', kPrimary | GLFW_MOD_SHIFT), EditCommand::Redo);
    EXPECT_EQ(edit_command_for('v', kPrimary | GLFW_MOD_SHIFT), EditCommand::None);
}

TEST(EditCommand, NoOrWrongOrExtraModifierIsNothing) {
    EXPECT_EQ(edit_command_for('v', 0), EditCommand::None);
    EXPECT_EQ(edit_command_for('v', GLFW_MOD_SHIFT), EditCommand::None);
    EXPECT_EQ(edit_command_for('v', kWrong), EditCommand::None);
    EXPECT_EQ(edit_command_for('v', kPrimary | GLFW_MOD_ALT), EditCommand::None);
    EXPECT_EQ(edit_command_for('v', kPrimary | kWrong), EditCommand::None);
    EXPECT_EQ(edit_command_for('q', kPrimary), EditCommand::None);
}

TEST(EditCommand, KindIsDistinctFromCharAndKey) {
    EXPECT_EQ(renderer::kTextEventEdit, 2);
    EXPECT_NE(renderer::kTextEventEdit, renderer::kTextEventChar);
    EXPECT_NE(renderer::kTextEventEdit, renderer::kTextEventKey);
}

// ── TextEventTranslator ──────────────────────────────────────────────────
//
// Pairs the raw per-frame queue into CEF's KEYDOWN+CHAR / KEYUP sequence.
// Root cause this exists to fix: CEF macOS's TranslateWebKeyEvent treats
// character == 0 && unmodified_character == 0 as NSEventTypeFlagsChanged
// and ignores the KEYEVENT type we asked for -- so a bare press/release with
// character 0 both land in Blink as key-downs (arrows moving twice).

using renderer::CefKeyType;
using renderer::TextEventTranslator;

#if defined(__APPLE__)

TEST(TextEventTranslator, ArrowTapAcrossTwoCallsNoCharNoKeyupZero) {
    TextEventTranslator t;
    auto down = t.translate({{renderer::kTextEventKey, GLFW_KEY_RIGHT, 124, GLFW_PRESS, 0}});
    ASSERT_EQ(down.size(), 2u);
    EXPECT_EQ(down[0].type, CefKeyType::KeyDown);
    EXPECT_EQ(down[0].character, 0xF703);
    EXPECT_EQ(down[0].unmodified_character, 0xF703);
    EXPECT_EQ(down[0].native_key_code, 124);
    EXPECT_EQ(down[1].type, CefKeyType::Char);
    EXPECT_EQ(down[1].character, 0xF703);

    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_RIGHT, 124, GLFW_RELEASE, 0}});
    ASSERT_EQ(up.size(), 1u);
    EXPECT_EQ(up[0].type, CefKeyType::KeyUp);
    EXPECT_EQ(up[0].character, 0xF703);
    EXPECT_NE(up[0].character, 0);
}

TEST(TextEventTranslator, DotPressCharThenRelease) {
    TextEventTranslator t;
    auto down = t.translate({
        {renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_PRESS, 0},
        {renderer::kTextEventChar, static_cast<int>('.'), 0, GLFW_PRESS, 0},
    });
    ASSERT_EQ(down.size(), 2u);
    EXPECT_EQ(down[0].type, CefKeyType::KeyDown);
    EXPECT_EQ(down[0].character, u'.');
    EXPECT_EQ(down[0].native_key_code, 47);
    EXPECT_EQ(down[1].type, CefKeyType::Char);
    EXPECT_EQ(down[1].character, u'.');

    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_RELEASE, 0}});
    ASSERT_EQ(up.size(), 1u);
    EXPECT_EQ(up[0].type, CefKeyType::KeyUp);
    EXPECT_EQ(up[0].character, u'.');
    EXPECT_NE(up[0].native_key_code, 0);
}

TEST(TextEventTranslator, ThreeDotsEachPressCharRelease) {
    TextEventTranslator t;
    for (int i = 0; i < 3; ++i) {
        auto d = t.translate({
            {renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_PRESS, 0},
            {renderer::kTextEventChar, static_cast<int>('.'), 0, GLFW_PRESS, 0},
        });
        ASSERT_EQ(d.size(), 2u) << "iteration " << i;
        auto u = t.translate({{renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_RELEASE, 0}});
        ASSERT_EQ(u.size(), 1u) << "iteration " << i;
    }
}

TEST(TextEventTranslator, RepeatOfLeftEmitsAnotherPairOneKeyupAtRelease) {
    TextEventTranslator t;
    auto first = t.translate({{renderer::kTextEventKey, GLFW_KEY_LEFT, 123, GLFW_PRESS, 0}});
    ASSERT_EQ(first.size(), 2u);
    auto repeat = t.translate({{renderer::kTextEventKey, GLFW_KEY_LEFT, 123, GLFW_REPEAT, 0}});
    ASSERT_EQ(repeat.size(), 2u);
    EXPECT_EQ(repeat[0].type, CefKeyType::KeyDown);
    EXPECT_EQ(repeat[0].character, 0xF702);
    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_LEFT, 123, GLFW_RELEASE, 0}});
    ASSERT_EQ(up.size(), 1u);
}

TEST(TextEventTranslator, ShiftAlonePressAndReleaseEmitsNothing) {
    TextEventTranslator t;
    auto down = t.translate({{renderer::kTextEventKey, GLFW_KEY_LEFT_SHIFT, 56, GLFW_PRESS, 0}});
    EXPECT_TRUE(down.empty());
    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_LEFT_SHIFT, 56, GLFW_RELEASE, 0}});
    EXPECT_TRUE(up.empty());
}

TEST(TextEventTranslator, LoneCharWithNoPrecedingKeyEmitsKeyDownCharNoKeyup) {
    TextEventTranslator t;
    auto out = t.translate({{renderer::kTextEventChar, static_cast<int>('q'), 0, GLFW_PRESS, 0}});
    ASSERT_EQ(out.size(), 2u);
    EXPECT_EQ(out[0].type, CefKeyType::KeyDown);
    EXPECT_EQ(out[0].native_key_code, 0);
    EXPECT_EQ(out[0].character, u'q');
    EXPECT_EQ(out[1].type, CefKeyType::Char);
    EXPECT_EQ(out[1].character, u'q');
    // No key was ever held for 'q', so a later release of its key is a no-op.
    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_Q, 0, GLFW_RELEASE, 0}});
    EXPECT_TRUE(up.empty());
}

TEST(TextEventTranslator, ReleaseWithNothingHeldEmitsNothing) {
    TextEventTranslator t;
    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_A, 0, GLFW_RELEASE, 0}});
    EXPECT_TRUE(up.empty());
}

TEST(TextEventTranslator, ResetForgetsHeldKeys) {
    TextEventTranslator t;
    auto down = t.translate({
        {renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_PRESS, 0},
        {renderer::kTextEventChar, static_cast<int>('.'), 0, GLFW_PRESS, 0},
    });
    ASSERT_EQ(down.size(), 2u);
    t.reset();
    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_RELEASE, 0}});
    EXPECT_TRUE(up.empty());
}

TEST(TextEventTranslator, BackspaceEnterEscapeProduceControlChars) {
    TextEventTranslator t;
    auto bs = t.translate({{renderer::kTextEventKey, GLFW_KEY_BACKSPACE, 51, GLFW_PRESS, 0}});
    ASSERT_EQ(bs.size(), 2u);
    EXPECT_EQ(bs[0].character, 0x7F);

    auto enter = t.translate({{renderer::kTextEventKey, GLFW_KEY_ENTER, 36, GLFW_PRESS, 0}});
    ASSERT_EQ(enter.size(), 2u);
    EXPECT_EQ(enter[0].character, 0x0D);

    auto esc = t.translate({{renderer::kTextEventKey, GLFW_KEY_ESCAPE, 53, GLFW_PRESS, 0}});
    ASSERT_EQ(esc.size(), 2u);
    EXPECT_EQ(esc[0].character, 0x1B);
}

#endif  // __APPLE__

TEST(TextEventTranslator, EditCommandEventsAreSkipped) {
    TextEventTranslator t;
    auto out = t.translate({{renderer::kTextEventEdit, 1, 0, GLFW_PRESS, 0}});
    EXPECT_TRUE(out.empty());
}
