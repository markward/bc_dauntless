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
