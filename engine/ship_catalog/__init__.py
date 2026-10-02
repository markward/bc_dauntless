"""The ship catalog: every Quick Battle ship definition, with Dauntless metadata.

The ONE place the engine reads ship metadata from. Consumers (the setup
screen, the mod metadata gate) never read a ShipDef or a metadata file.

Spec: docs/superpowers/specs/2026-10-01-ship-metadata-catalog-design.md
"""
from engine.ship_catalog.tables import (  # noqa: F401
    ALL_ERAS, DEFAULT_ERAS, ERA_IDS, ERAS, MANDATORY, ROLE_IDS, ROLES,
    STOCK_SPECIES, Era, Role, Species)
from engine.ship_catalog.schema import Variant  # noqa: F401
from engine.ship_catalog.catalog import (  # noqa: F401
    RACE_TO_SPECIES, CatalogEntry, ShipRecord, combine_class, describe,
    entries, entry, incomplete, incomplete_ships, insignia_path, invalidate,
    reset_session, resolve_class_default, ships, skip_for_session, skipped,
    species, suggestions)
