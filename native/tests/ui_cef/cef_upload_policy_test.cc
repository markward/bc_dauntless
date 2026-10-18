// native/tests/ui_cef/cef_upload_policy_test.cc
//
// The CEF overlay upload decision, without GL or CEF. The policy exists for
// perf-register A-1: the CPU appears to stall on the GPU inside the per-frame
// full-surface glTexSubImage2D. `on_paint` skips frames CEF did not repaint;
// `never` freezes the overlay after its first upload (diagnostic only).
#include "cef_upload_policy.h"

#include <gtest/gtest.h>

using dauntless::ui_cef::UploadMode;
using dauntless::ui_cef::parse_upload_mode;
using dauntless::ui_cef::should_upload;

TEST(CefUploadPolicy, UnsetOrUnknownEnvIsAlways) {
    EXPECT_EQ(parse_upload_mode(nullptr), UploadMode::Always);
    EXPECT_EQ(parse_upload_mode(""), UploadMode::Always);
    EXPECT_EQ(parse_upload_mode("sometimes"), UploadMode::Always);
}

TEST(CefUploadPolicy, ParsesEachNamedMode) {
    EXPECT_EQ(parse_upload_mode("always"), UploadMode::Always);
    EXPECT_EQ(parse_upload_mode("on_paint"), UploadMode::OnPaint);
    EXPECT_EQ(parse_upload_mode("never"), UploadMode::Never);
}

TEST(CefUploadPolicy, AlwaysUploadsEvenWithNoNewPaint) {
    EXPECT_TRUE(should_upload(UploadMode::Always, /*allocated=*/true,
                              /*size_changed=*/false,
                              /*paint_gen=*/7, /*uploaded_gen=*/7));
}

TEST(CefUploadPolicy, OnPaintUploadsOnlyANewPaint) {
    EXPECT_FALSE(should_upload(UploadMode::OnPaint, true, false, 7, 7));
    EXPECT_TRUE(should_upload(UploadMode::OnPaint, true, false, 8, 7));
}

TEST(CefUploadPolicy, NeverSkipsOnceTheTextureExists) {
    EXPECT_FALSE(should_upload(UploadMode::Never, true, false, 8, 7));
}

TEST(CefUploadPolicy, EveryModeUploadsWhenTheTextureMustBeAllocated) {
    for (UploadMode m : {UploadMode::Always, UploadMode::OnPaint,
                         UploadMode::Never}) {
        EXPECT_TRUE(should_upload(m, /*allocated=*/false, false, 1, 1));
        EXPECT_TRUE(should_upload(m, true, /*size_changed=*/true, 1, 1));
    }
}
