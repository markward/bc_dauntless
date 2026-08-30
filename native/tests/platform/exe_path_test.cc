// Regression net for the defect that killed a launch through PATH.
//
// std::filesystem::canonical(argv[0]) resolves against the CURRENT DIRECTORY,
// so it throws whenever argv[0] is a bare name and the cwd is not the binary's
// directory. Uncaught, that aborted the process with no usable diagnostic:
// measured 0xC0000409 on Windows, exit 134 on macOS.
//
// This test binary is itself an executable, so it can ask for its own path and
// check the answer against a name the filesystem cannot resolve.

#include "platform/exe_path.h"

#include <gtest/gtest.h>

#include <filesystem>
#include <string>

namespace {

using dauntless::platform::canonical_or_error;
using dauntless::platform::executable_path;

// On Windows and macOS executable_path() asks the OS, so argv[0] is only a
// hint and a bare name is fine. Other POSIX still resolves argv[0] and cannot
// answer these; see the header.
#if defined(_WIN32) || defined(__APPLE__)
#define EXPECT_OS_IMAGE_PATH_QUERY 1
#endif

#ifdef EXPECT_OS_IMAGE_PATH_QUERY
TEST(ExePath, ResolvesThisTestBinary) {
    std::string error = "not cleared";
    const std::filesystem::path self = executable_path("", error);

    ASSERT_FALSE(self.empty()) << error;
    EXPECT_TRUE(error.empty()) << "error must be cleared on success: " << error;
    EXPECT_TRUE(self.is_absolute()) << self.string();
    EXPECT_TRUE(std::filesystem::exists(self)) << self.string();
    EXPECT_NE(self.filename().string().find("platform_tests"), std::string::npos)
        << "expected this test binary, got " << self.string();
}

// THE defect. Before the fix this input threw out of canonical() and took the
// process with it, so a failure here is not a wrong return value -- it is the
// test binary aborting.
TEST(ExePath, IgnoresAnUnresolvableArgv0) {
    std::string error;
    const std::filesystem::path from_bare_name =
        executable_path("platform_tests", error);
    ASSERT_FALSE(from_bare_name.empty()) << error;

    std::string other_error;
    const std::filesystem::path from_nonsense =
        executable_path("no/such/binary-cf3a1d", other_error);
    ASSERT_FALSE(from_nonsense.empty()) << other_error;

    // Same process, so every argv[0] must produce the same image path.
    EXPECT_EQ(from_bare_name, from_nonsense);
    std::string ignored;
    EXPECT_EQ(from_bare_name, executable_path("", ignored));
}

// The path is used to hang sibling paths off (Frameworks/, libcef.dll), so it
// has to point at the real file rather than a symlink to it.
TEST(ExePath, ResolvesSymlinksToTheRealBinary) {
    std::string error;
    const std::filesystem::path self = executable_path("", error);
    ASSERT_FALSE(self.empty()) << error;

    std::error_code ec;
    const std::filesystem::path real = std::filesystem::canonical(self, ec);
    ASSERT_FALSE(ec) << ec.message();
    EXPECT_EQ(self, real);
}
#else
// The argv[0]-resolving fallback cannot answer a PATH launch, but it must
// still report rather than throw -- that reporting is what the caller turns
// into a diagnostic instead of a silent abort.
TEST(ExePath, FallbackReportsAnUnresolvableArgv0) {
    std::string error;
    EXPECT_TRUE(executable_path("", error).empty());
    EXPECT_FALSE(error.empty());

    std::string other_error;
    EXPECT_TRUE(executable_path("no/such/binary-cf3a1d", other_error).empty());
    EXPECT_NE(other_error.find("no/such/binary-cf3a1d"), std::string::npos)
        << other_error;
}
#endif  // EXPECT_OS_IMAGE_PATH_QUERY

TEST(CanonicalOrError, ReportsAMissingPathInsteadOfThrowing) {
    std::string error;
    const std::filesystem::path resolved =
        canonical_or_error("no/such/file-9f2b7c.html", error);

    EXPECT_TRUE(resolved.empty());
    ASSERT_FALSE(error.empty());
    // The message has to name what was looked for; the whole point of the
    // helper is that the old behaviour said nothing at all.
    EXPECT_NE(error.find("no/such/file-9f2b7c.html"), std::string::npos)
        << error;
}

TEST(CanonicalOrError, ResolvesAnExistingPath) {
    std::string error = "not cleared";
    const std::filesystem::path root =
        canonical_or_error(OPEN_STBC_PROJECT_ROOT, error);

    ASSERT_FALSE(root.empty()) << error;
    EXPECT_TRUE(error.empty()) << error;
    EXPECT_TRUE(std::filesystem::exists(root / "CMakeLists.txt"))
        << root.string();
}

}  // namespace
