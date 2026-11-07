// SetIndex (set_index.h): dict slot order, multiplicity, LEAVING, counts.
#include <gtest/gtest.h>

#include <algorithm>
#include <vector>

#include "dauntless/combat/set_index.h"

using namespace dauntless::combat;
using Keys = std::vector<IndexKey>;

namespace {
constexpr IndexKey S = 1000, S2 = 1001, CLS = 2000;
constexpr IndexKey A = 1, B = 2, C = 3, D = 4, T = 5;

SetIndex with_bucket() {
    SetIndex ix;
    ix.create_bucket(S, CLS, [](IndexKey) { return true; });
    return ix;
}
void put(SetIndex& ix, IndexKey set, const char* id, IndexKey o, bool ship = false,
         int64_t tgt = kNoTarget) {
    ix.add(set, id, o, static_cast<int64_t>(o), ship, tgt);
    ix.set_bucket_membership(set, CLS, o, true);
}
}  // namespace

TEST(SetIndex, BucketFollowsDictOrder) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    put(ix, S, "b", B);
    put(ix, S, "c", C);
    auto r = ix.add(S, "b", D, D, false, kNoTarget);
    ix.set_bucket_membership(S, CLS, D, true);
    ASSERT_TRUE(r.has_value());
    EXPECT_EQ(*r, B);
    EXPECT_EQ(ix.bucket(S, CLS), (Keys{A, D, C}));
    EXPECT_EQ(ix.remove(S, "a"), A);
    put(ix, S, "a", A);
    EXPECT_EQ(ix.bucket(S, CLS), (Keys{D, C, A}));
}

TEST(SetIndex, LeavingEntryStaysInBucketsAndCountsButNotTheContactView) {
    SetIndex ix = with_bucket();
    put(ix, S, "s", A, true, T);
    ix.mark_leaving(S, "s");
    EXPECT_EQ(ix.bucket(S, CLS), (Keys{A}));
    EXPECT_EQ(ix.targeted_by(S, T), 1);
    EXPECT_TRUE(ix.distinct_live(S, CLS).empty());
    EXPECT_TRUE(ix.sets_holding(A).empty());
    ix.mark_leaving(S, "nope");
    ix.remove(S, "s");
    EXPECT_TRUE(ix.bucket(S, CLS).empty());
    EXPECT_EQ(ix.targeted_by(S, T), 0);
    EXPECT_TRUE(ix.distinct_live(S, CLS).empty());
}

TEST(SetIndex, OverwriteOfALeavingEntryClearsLeaving) {
    SetIndex ix = with_bucket();
    put(ix, S, "x", A);
    ix.mark_leaving(S, "x");
    ix.add(S, "x", B, B, false, kNoTarget);
    ix.set_bucket_membership(S, CLS, B, true);
    EXPECT_EQ(ix.distinct_live(S, CLS), (Keys{B}));
}

TEST(SetIndex, CountsFollowTargetsAndMembership) {
    SetIndex ix;
    ix.add(S, "a", A, A, true, T);
    ix.add(S, "b", B, B, true, T);
    ix.add(S, "c", C, C, true, kNoTarget);
    EXPECT_EQ(ix.targeted_by(S, T), 2);
    ix.set_target(C, T);
    EXPECT_EQ(ix.targeted_by(S, T), 3);
    ix.set_target(A, D);
    EXPECT_EQ(ix.targeted_by(S, T), 2);
    EXPECT_EQ(ix.targeted_by(S, D), 1);
    ix.remove(S, "a");
    ix.add(S2, "a", A, A, true, D);
    EXPECT_EQ(ix.targeted_by(S, D), 0);
    EXPECT_EQ(ix.targeted_by(S2, D), 1);
    ix.set_target(A, T);
    EXPECT_EQ(ix.targeted_by(S2, T), 1);
    EXPECT_EQ(ix.targeted_by(S, T), 3 - 1 + 0);  // b, c
}

TEST(SetIndex, PopularitySubtractsTheRaterByMultiplicity) {
    SetIndex ix;
    ix.add(S, "r1", A, A, true, C);
    ix.add(S, "r2", A, A, true, C);
    ix.add(S, "o", B, B, true, C);
    EXPECT_EQ(ix.targeted_by(S, C), 3);
    EXPECT_EQ(ix.multiplicity(S, A), 2);
    EXPECT_EQ(ix.popularity(S, A, C), 1);
    EXPECT_EQ(ix.popularity(S, A, D), 0);
}

TEST(SetIndex, TargetSetOutsideAnySetIsPickedUpOnAdd) {
    SetIndex ix;
    ix.set_target(A, T);  // unknown ship: only recorded
    EXPECT_EQ(ix.targeted_by(S, T), 0);
    ix.add(S, "a", A, A, true, T);
    EXPECT_EQ(ix.targeted_by(S, T), 1);
    ix.remove(S, "a");
    ix.set_target(A, D);
    ix.add(S, "a", A, A, true, D);
    EXPECT_EQ(ix.targeted_by(S, D), 1);
    EXPECT_EQ(ix.targeted_by(S, T), 0);
}

TEST(SetIndex, TargetingListsRatersInSequenceOrder) {
    SetIndex ix;
    ix.add(S, "c", C, C, true, T);
    ix.add(S, "a", A, A, true, T);
    ix.add(S, "b", B, B, true, D);
    ix.add(S, "a2", A, A, true, T);
    EXPECT_EQ(ix.targeting(S, T), (Keys{C, A, A}));
}

TEST(SetIndex, ForgetSetAndResetReturnEveryReference) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    put(ix, S, "a2", A);
    put(ix, S, "b", B);
    ix.add(S2, "c", C, C, true, T);
    auto sorted = [](Keys k) { std::sort(k.begin(), k.end()); return k; };
    EXPECT_EQ(sorted(ix.forget_set(S)), (Keys{A, A, B, S}));
    EXPECT_FALSE(ix.has_set(S));
    EXPECT_TRUE(ix.sets_holding(A).empty());
    EXPECT_EQ(ix.sets(), (Keys{S2}));
    put(ix, S, "d", D);
    EXPECT_EQ(sorted(ix.reset()), (Keys{C, D, S, S2}));
    EXPECT_TRUE(ix.sets().empty());
    EXPECT_TRUE(ix.reset().empty());
}

TEST(SetIndex, DistinctLiveDropsDuplicates) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    put(ix, S, "b", B);
    put(ix, S, "a2", A);
    EXPECT_EQ(ix.bucket(S, CLS), (Keys{A, B, A}));
    EXPECT_EQ(ix.distinct_live(S, CLS), (Keys{A, B}));
    ix.mark_leaving(S, "a");
    EXPECT_EQ(ix.distinct_live(S, CLS), (Keys{B, A}));
    EXPECT_EQ(ix.sets_holding(A), (Keys{S}));
}
