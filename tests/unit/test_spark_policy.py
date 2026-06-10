"""Spark trigger + count policy — pure, no renderer."""
import pytest
from engine.appc.hit_feedback import (
    Severity, spark_params,
    SPARK_HULL_THRESHOLD, SPARK_KIND_PHASER, SPARK_KIND_TORPEDO,
)


def test_no_spark_below_threshold_non_critical():
    count, kind = spark_params(
        weapon_type="phaser", severity=Severity.HULL,
        absorbed_hull=SPARK_HULL_THRESHOLD - 1.0)
    assert count == 0


def test_spark_at_or_above_threshold():
    count, kind = spark_params(
        weapon_type="torpedo", severity=Severity.HULL,
        absorbed_hull=SPARK_HULL_THRESHOLD)
    assert count > 0
    assert kind == SPARK_KIND_TORPEDO


def test_critical_always_sparks_even_below_threshold():
    count, kind = spark_params(
        weapon_type="phaser", severity=Severity.CRITICAL,
        absorbed_hull=0.0)
    assert count > 0
    assert kind == SPARK_KIND_PHASER


def test_critical_count_exceeds_plain_hull_count():
    hull_count, _ = spark_params(
        weapon_type="torpedo", severity=Severity.HULL,
        absorbed_hull=SPARK_HULL_THRESHOLD * 4)
    crit_count, _ = spark_params(
        weapon_type="torpedo", severity=Severity.CRITICAL,
        absorbed_hull=SPARK_HULL_THRESHOLD * 4)
    assert crit_count > hull_count


def test_phaser_kind_for_phaser_weapon():
    _, kind = spark_params(
        weapon_type="phaser", severity=Severity.CRITICAL, absorbed_hull=0.0)
    assert kind == SPARK_KIND_PHASER


def test_torpedo_kind_for_unknown_weapon_defaults_torpedo():
    _, kind = spark_params(
        weapon_type=None, severity=Severity.CRITICAL, absorbed_hull=0.0)
    assert kind == SPARK_KIND_TORPEDO
