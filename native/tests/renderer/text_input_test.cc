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

TEST(TextEventTranslator, PressCharReleaseAllInOneCall) {
    TextEventTranslator t;
    auto out = t.translate({
        {renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_PRESS, 0},
        {renderer::kTextEventChar, static_cast<int>('.'), 0, GLFW_PRESS, 0},
        {renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_RELEASE, 0},
    });
    ASSERT_EQ(out.size(), 3u);
    EXPECT_EQ(out[0].type, CefKeyType::KeyDown);
    EXPECT_EQ(out[0].character, u'.');
    EXPECT_EQ(out[1].type, CefKeyType::Char);
    EXPECT_EQ(out[1].character, u'.');
    EXPECT_EQ(out[2].type, CefKeyType::KeyUp);
    EXPECT_EQ(out[2].character, u'.');
}

TEST(TextEventTranslator, ShiftModifiedLetterOnlyEmitsTheLetter) {
    TextEventTranslator t;
    auto shift_down = t.translate(
        {{renderer::kTextEventKey, GLFW_KEY_LEFT_SHIFT, 56, GLFW_PRESS, GLFW_MOD_SHIFT}});
    EXPECT_TRUE(shift_down.empty());

    auto a_down = t.translate({
        {renderer::kTextEventKey, GLFW_KEY_A, 0, GLFW_PRESS, GLFW_MOD_SHIFT},
        {renderer::kTextEventChar, static_cast<int>('A'), 0, GLFW_PRESS, GLFW_MOD_SHIFT},
    });
    ASSERT_EQ(a_down.size(), 2u);
    EXPECT_EQ(a_down[0].type, CefKeyType::KeyDown);
    EXPECT_EQ(a_down[0].character, u'A');
    EXPECT_EQ(a_down[1].type, CefKeyType::Char);

    auto a_up = t.translate(
        {{renderer::kTextEventKey, GLFW_KEY_A, 0, GLFW_RELEASE, GLFW_MOD_SHIFT}});
    ASSERT_EQ(a_up.size(), 1u);
    EXPECT_EQ(a_up[0].type, CefKeyType::KeyUp);
    EXPECT_EQ(a_up[0].character, u'A');

    auto shift_up =
        t.translate({{renderer::kTextEventKey, GLFW_KEY_LEFT_SHIFT, 56, GLFW_RELEASE, 0}});
    EXPECT_TRUE(shift_up.empty());
}

TEST(TextEventTranslator, PrintableKeyWithNoCharThenReleaseEmitsNothing) {
    TextEventTranslator t;
    auto down = t.translate({{renderer::kTextEventKey, GLFW_KEY_A, 0, GLFW_PRESS, 0}});
    EXPECT_TRUE(down.empty());
    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_A, 0, GLFW_RELEASE, 0}});
    EXPECT_TRUE(up.empty());
}

// A codepoint above the BMP (U+1F600, outside char16_t's range): CEF's
// character/unmodified_character fields are char16_t, so a naive
// static_cast<char16_t> truncates U+1F600 to 0 -- which on macOS is
// exactly the character==0 flags-changed trap this translator exists to
// dodge (see the class doc comment). Drop it instead.
TEST(TextEventTranslator, NonBmpPairedCharDropsBothKeyAndChar) {
    TextEventTranslator t;
    auto down = t.translate({
        {renderer::kTextEventKey, GLFW_KEY_A, 0, GLFW_PRESS, 0},
        {renderer::kTextEventChar, 0x1F600, 0, GLFW_PRESS, 0},
    });
    EXPECT_TRUE(down.empty());
    // Not remembered: the key's later release is a no-op too.
    auto up = t.translate({{renderer::kTextEventKey, GLFW_KEY_A, 0, GLFW_RELEASE, 0}});
    EXPECT_TRUE(up.empty());
}

TEST(TextEventTranslator, NonBmpLoneCharEmitsNothing) {
    TextEventTranslator t;
    auto out = t.translate({{renderer::kTextEventChar, 0x1F600, 0, GLFW_PRESS, 0}});
    EXPECT_TRUE(out.empty());
}

// ── build_text_event_steps ───────────────────────────────────────────────
//
// The live-bug regression this guards: cef_send_text_events used to run
// ALL edit commands in a batch first and send ALL translated key intents
// after, in a naive two-pass split -- so a frame holding ['-' press, '-'
// char, Cmd+V] pasted BEFORE the '-' was inserted, and a frame holding a
// typed character immediately followed by Cmd+Z undid the wrong thing.

using renderer::build_text_event_steps;
using renderer::TextEventStep;

TEST(BuildTextEventSteps, PreservesOrderAroundAnEditCommand) {
    TextEventTranslator t;
    const std::vector<TextEvent> events = {
        {renderer::kTextEventKey, GLFW_KEY_MINUS, 27, GLFW_PRESS, 0},
        {renderer::kTextEventChar, static_cast<int>('-'), 0, GLFW_PRESS, 0},
        {renderer::kTextEventEdit, static_cast<int>(EditCommand::Paste), 9, GLFW_PRESS, 8},
        {renderer::kTextEventKey, GLFW_KEY_1, 18, GLFW_PRESS, 0},
        {renderer::kTextEventChar, static_cast<int>('1'), 0, GLFW_PRESS, 0},
    };
    auto steps = build_text_event_steps(events, t);

    ASSERT_EQ(steps.size(), 3u);

    EXPECT_FALSE(steps[0].is_edit_command);
    ASSERT_EQ(steps[0].intents.size(), 2u);
    EXPECT_EQ(steps[0].intents[0].type, CefKeyType::KeyDown);
    EXPECT_EQ(steps[0].intents[0].character, u'-');
    EXPECT_EQ(steps[0].intents[1].type, CefKeyType::Char);

    EXPECT_TRUE(steps[1].is_edit_command);
    EXPECT_EQ(steps[1].command, EditCommand::Paste);

    EXPECT_FALSE(steps[2].is_edit_command);
    ASSERT_EQ(steps[2].intents.size(), 2u);
    EXPECT_EQ(steps[2].intents[0].type, CefKeyType::KeyDown);
    EXPECT_EQ(steps[2].intents[0].character, u'1');
    EXPECT_EQ(steps[2].intents[1].type, CefKeyType::Char);
}

TEST(BuildTextEventSteps, NoEditCommandsYieldsOneKeyStep) {
    TextEventTranslator t;
    const std::vector<TextEvent> events = {
        {renderer::kTextEventKey, GLFW_KEY_PERIOD, 47, GLFW_PRESS, 0},
        {renderer::kTextEventChar, static_cast<int>('.'), 0, GLFW_PRESS, 0},
    };
    auto steps = build_text_event_steps(events, t);
    ASSERT_EQ(steps.size(), 1u);
    EXPECT_FALSE(steps[0].is_edit_command);
    EXPECT_EQ(steps[0].intents.size(), 2u);
}

TEST(BuildTextEventSteps, ConsecutiveEditCommandsEachGetTheirOwnStep) {
    TextEventTranslator t;
    const std::vector<TextEvent> events = {
        {renderer::kTextEventEdit, static_cast<int>(EditCommand::Copy), 8, GLFW_PRESS, 8},
        {renderer::kTextEventEdit, static_cast<int>(EditCommand::Paste), 9, GLFW_PRESS, 8},
    };
    auto steps = build_text_event_steps(events, t);
    ASSERT_EQ(steps.size(), 2u);
    EXPECT_TRUE(steps[0].is_edit_command);
    EXPECT_EQ(steps[0].command, EditCommand::Copy);
    EXPECT_TRUE(steps[1].is_edit_command);
    EXPECT_EQ(steps[1].command, EditCommand::Paste);
}
