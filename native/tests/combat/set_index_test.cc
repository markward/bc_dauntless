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
    ix.add(set, id, o, ship, tgt);
    ix.set_bucket_membership(set, CLS, o, true);
}
}  // namespace

TEST(SetIndex, BucketFollowsDictOrder) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    put(ix, S, "b", B);
    put(ix, S, "c", C);
    auto r = ix.add(S, "b", D, false, kNoTarget);
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
    ix.add(S, "x", B, false, kNoTarget);
    ix.set_bucket_membership(S, CLS, B, true);
    EXPECT_EQ(ix.distinct_live(S, CLS), (Keys{B}));
}

TEST(SetIndex, CountsFollowTargetsAndMembership) {
    SetIndex ix;
    ix.add(S, "a", A, true, T);
    ix.add(S, "b", B, true, T);
    ix.add(S, "c", C, true, kNoTarget);
    EXPECT_EQ(ix.targeted_by(S, T), 2);
    ix.set_target(C, T);
    EXPECT_EQ(ix.targeted_by(S, T), 3);
    ix.set_target(A, D);
    EXPECT_EQ(ix.targeted_by(S, T), 2);
    EXPECT_EQ(ix.targeted_by(S, D), 1);
    ix.remove(S, "a");
    ix.add(S2, "a", A, true, D);
    EXPECT_EQ(ix.targeted_by(S, D), 0);
    EXPECT_EQ(ix.targeted_by(S2, D), 1);
    ix.set_target(A, T);
    EXPECT_EQ(ix.targeted_by(S2, T), 1);
    EXPECT_EQ(ix.targeted_by(S, T), 3 - 1 + 0);  // b, c
}

TEST(SetIndex, PopularitySubtractsTheRaterByMultiplicity) {
    SetIndex ix;
    ix.add(S, "r1", A, true, C);
    ix.add(S, "r2", A, true, C);
    ix.add(S, "o", B, true, C);
    EXPECT_EQ(ix.targeted_by(S, C), 3);
    EXPECT_EQ(ix.multiplicity(S, A), 2);
    EXPECT_EQ(ix.popularity(S, A, C), 1);
    EXPECT_EQ(ix.popularity(S, A, D), 0);
}

TEST(SetIndex, TargetSetOutsideAnySetIsPickedUpOnAdd) {
    // No record outside a set: set_target on an unheld ship does nothing, and
    // add's target_id (the ship's current target, from Python) is what counts.
    SetIndex ix;
    ix.set_target(A, T);
    EXPECT_EQ(ix.object_records(), 0u);
    ix.add(S, "a", A, true, D);
    EXPECT_EQ(ix.targeted_by(S, D), 1);
    EXPECT_EQ(ix.targeted_by(S, T), 0);
    ix.remove(S, "a");
    ix.set_target(A, T);
    ix.add(S, "a", A, true, kNoTarget);
    EXPECT_EQ(ix.targeted_by(S, T), 0);
    EXPECT_EQ(ix.targeted_by(S, D), 0);
}

TEST(SetIndex, AnObjectRemovedFromItsLastSetLeavesNoRecord) {
    SetIndex ix;
    ix.add(S, "a", A, true, T);
    ix.add(S, "a2", A, true, T);
    ix.add(S2, "a", A, true, T);
    EXPECT_EQ(ix.object_records(), 1u);
    ix.remove(S, "a");
    ix.remove(S, "a2");
    EXPECT_EQ(ix.object_records(), 1u);
    ix.remove(S2, "a");
    EXPECT_EQ(ix.object_records(), 0u);
    ix.add(S, "b", B);
    ix.add(S, "b", C);  // overwrite: B is held nowhere now
    EXPECT_EQ(ix.object_records(), 1u);
    ix.forget_set(S);
    EXPECT_EQ(ix.object_records(), 0u);
}

TEST(SetIndex, OverwriteChangesCounts) {
    SetIndex ix;
    ix.add(S, "x", A, true, T);
    EXPECT_EQ(ix.targeted_by(S, T), 1);
    ix.add(S, "x", B, true, D);
    EXPECT_EQ(ix.targeted_by(S, T), 0);
    EXPECT_EQ(ix.targeted_by(S, D), 1);
    ix.add(S, "x", C, false, kNoTarget);
    EXPECT_EQ(ix.targeted_by(S, D), 0);
}

TEST(SetIndex, OverwriteOfAnObjectHeldUnderTwoIdentifiers) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A, true, T);
    put(ix, S, "a2", A, true, T);
    EXPECT_EQ(ix.targeted_by(S, T), 2);
    put(ix, S, "a", B, true, D);
    EXPECT_EQ(ix.bucket(S, CLS), (Keys{B, A}));
    EXPECT_EQ(ix.multiplicity(S, A), 1);
    EXPECT_EQ(ix.targeted_by(S, T), 1);
    EXPECT_EQ(ix.targeted_by(S, D), 1);
    EXPECT_EQ(ix.sets_holding(A), (Keys{S}));
}

TEST(SetIndex, SetIsShipFlipsCounts) {
    SetIndex ix;
    ix.add(S, "a", A, true, T);
    ix.add(S, "a2", A, true, T);
    ix.add(S2, "a", A, true, T);
    ix.set_is_ship(A, false);
    EXPECT_EQ(ix.targeted_by(S, T), 0);
    EXPECT_EQ(ix.targeted_by(S2, T), 0);
    ix.set_is_ship(A, true);
    EXPECT_EQ(ix.targeted_by(S, T), 2);
    EXPECT_EQ(ix.targeted_by(S2, T), 1);
    ix.set_is_ship(B, true);  // held by no set: nothing recorded
    EXPECT_EQ(ix.object_records(), 1u);
}

TEST(SetIndex, AddWithANewTargetRecountsTheOtherSets) {
    // The facade keeps add's target equal to the last set_target; if it ever
    // differs, add applies it as set_target would, so no set drifts.
    SetIndex ix;
    ix.add(S, "a", A, true, T);
    ix.add(S2, "a", A, true, D);
    EXPECT_EQ(ix.targeted_by(S, T), 0);
    EXPECT_EQ(ix.targeted_by(S, D), 1);
    EXPECT_EQ(ix.targeted_by(S2, D), 1);
    ix.remove(S, "a");
    EXPECT_EQ(ix.targeted_by(S, D), 0);
    EXPECT_EQ(ix.targeted_by(S, T), 0);
}

TEST(SetIndex, PopularityOfNoTargetIsZero) {
    SetIndex ix;
    ix.add(S, "a", A, true, kNoTarget);
    ix.add(S, "b", B, true, kNoTarget);
    EXPECT_EQ(ix.popularity(S, A, kNoTarget), 0);
    EXPECT_EQ(ix.popularity(S, C, kNoTarget), 0);
}

TEST(SetIndex, HeldSetsIncludeLeavingEntries) {
    SetIndex ix;
    ix.add(S, "a", A);
    ix.add(S2, "a", A);
    ix.mark_leaving(S, "a");
    EXPECT_EQ(ix.sets_holding(A), (Keys{S2}));
    EXPECT_EQ(ix.held_sets(A), (Keys{S, S2}));
    EXPECT_TRUE(ix.held_sets(B).empty());
}

TEST(SetIndex, TargetingListsRatersInSequenceOrder) {
    SetIndex ix;
    ix.add(S, "c", C, true, T);
    ix.add(S, "a", A, true, T);
    ix.add(S, "b", B, true, D);
    ix.add(S, "a2", A, true, T);
    EXPECT_EQ(ix.targeting(S, T), (Keys{C, A, A}));
}

TEST(SetIndex, ForgetSetAndResetReturnEveryReference) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    put(ix, S, "a2", A);
    put(ix, S, "b", B);
    ix.add(S2, "c", C, true, T);
    auto sorted = [](Keys k) { std::sort(k.begin(), k.end()); return k; };
    EXPECT_EQ(ix.entry_count(), 4u);
    EXPECT_EQ(ix.entry_count(S), 3u);
    EXPECT_EQ(ix.entry_count(S2), 1u);
    EXPECT_EQ(ix.entry_count(999), 0u);
    EXPECT_EQ(sorted(ix.forget_set(S)), (Keys{A, A, B, S}));
    EXPECT_EQ(ix.entry_count(), 1u);
    EXPECT_FALSE(ix.has_set(S));
    EXPECT_TRUE(ix.sets_holding(A).empty());
    EXPECT_EQ(ix.sets(), (Keys{S2}));
    put(ix, S, "d", D);
    EXPECT_EQ(sorted(ix.reset()), (Keys{C, D, S, S2}));
    EXPECT_TRUE(ix.sets().empty());
    EXPECT_EQ(ix.entry_count(), 0u);
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

TEST(SetIndex, HideContactsHidesEveryEntryButKeepsListsAndCounts) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A, true, T);
    put(ix, S, "b", B);
    ix.hide_contacts(S);
    EXPECT_TRUE(ix.distinct_live(S, CLS).empty());
    EXPECT_TRUE(ix.sets_holding(A).empty());
    EXPECT_FALSE(ix.visible(S, A));
    EXPECT_EQ(ix.bucket(S, CLS), (Keys{A, B}));
    EXPECT_EQ(ix.targeted_by(S, T), 1);
    ix.hide_contacts(S2);  // an unknown set is a no-op
}

TEST(SetIndex, AHiddenEntryOverwrittenIsVisibleAgain) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    ix.hide_contacts(S);
    put(ix, S, "a", B);
    EXPECT_EQ(ix.distinct_live(S, CLS), (Keys{B}));
    EXPECT_TRUE(ix.visible(S, B));
    put(ix, S, "c", C);  // a new identifier after a hide is visible too
    EXPECT_EQ(ix.distinct_live(S, CLS), (Keys{B, C}));
}

TEST(SetIndex, AHiddenEntryRemovedChangesNoContactView) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    put(ix, S, "b", B);
    ix.hide_contacts(S);
    ix.remove(S, "a");
    EXPECT_TRUE(ix.distinct_live(S, CLS).empty());
    EXPECT_EQ(ix.bucket(S, CLS), (Keys{B}));
}

TEST(SetIndex, VisibleIsAnyEntryNotLeaving) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    put(ix, S, "a2", A);
    EXPECT_TRUE(ix.visible(S, A));
    ix.mark_leaving(S, "a");
    EXPECT_TRUE(ix.visible(S, A));
    ix.mark_leaving(S, "a2");
    EXPECT_FALSE(ix.visible(S, A));
    EXPECT_FALSE(ix.visible(S2, A));
}

TEST(SetIndex, AddRecordsTheObjectsOwnId) {
    SetIndex ix = with_bucket();
    ix.add(S, "a", A, true, kNoTarget, 41);
    ix.add(S, "b", B, false, kNoTarget);  // no id given
    EXPECT_EQ(ix.obj_id(A), 41);
    EXPECT_EQ(ix.obj_id(B), kNoId);
    EXPECT_EQ(ix.obj_id(C), kNoId);  // held by no set
    ix.add(S2, "a", A, true, kNoTarget, 41);
    ix.remove(S, "a");
    EXPECT_EQ(ix.obj_id(A), 41);  // still held by S2
    ix.remove(S2, "a");
    EXPECT_EQ(ix.obj_id(A), kNoId);  // the record went with the last hold
}

TEST(SetIndex, PopularityByKeyIsPopularityOfTheCandidatesId) {
    SetIndex ix = with_bucket();
    ix.add(S, "t", T, true, kNoTarget, 77);
    ix.add(S, "a", A, true, 77, 1);
    ix.add(S, "b", B, true, 77, 2);
    ix.add(S, "b2", B, true, 77, 2);
    ix.add(S, "c", C, true, kNoTarget, 3);
    EXPECT_EQ(ix.popularity_by_key(S, A, T), ix.popularity(S, A, 77));
    EXPECT_EQ(ix.popularity_by_key(S, A, T), 2);  // B twice, A skipped
    EXPECT_EQ(ix.popularity_by_key(S, B, T), 1);
    EXPECT_EQ(ix.popularity_by_key(S, C, T), 3);
    EXPECT_EQ(ix.popularity_by_key(S, A, D), 0);  // a candidate it does not hold
    EXPECT_EQ(ix.popularity_by_key(S, A, C), 0);  // nobody targets C
}

TEST(SetIndex, DropBucketForgetsOnlyThatBucket) {
    SetIndex ix = with_bucket();
    put(ix, S, "a", A);
    ix.create_bucket(S, CLS + 1, [](IndexKey) { return true; });
    EXPECT_TRUE(ix.drop_bucket(S, CLS));
    EXPECT_FALSE(ix.has_bucket(S, CLS));
    EXPECT_TRUE(ix.has_bucket(S, CLS + 1));
    EXPECT_TRUE(ix.bucket(S, CLS).empty());
    EXPECT_EQ(ix.bucket_classes(S), (Keys{CLS + 1}));
    EXPECT_FALSE(ix.drop_bucket(S, CLS));   // already gone
    EXPECT_FALSE(ix.drop_bucket(S2, CLS));  // an unknown set
    EXPECT_EQ(ix.entry_count(S), 1u);
}
