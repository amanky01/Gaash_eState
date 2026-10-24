'''services.py

Business‑logic helpers for the estate application.
All functions are wrapped in atomic transactions where appropriate
so that the database stays consistent.
''' 

from __future__ import annotations

from typing import List, Dict, Any

from django.db import transaction
from django.utils import timezone

from .models import (
    Building,
    Block,
    Unit,
    Bed,
    Occupant,
    Allocation,
    AmenityDefinition,
    AmenityValue,
)
from django.contrib.auth import get_user_model

User = get_user_model()


def create_building_with_structure(
    name: str,
    property_type: str,
    blocks: List[Dict[str, Any]],
    created_by: User,
) -> Building:
    """Create a building together with its blocks, units and beds.

    * ``blocks`` is a list of dicts, each dict must contain ``name`` and
      ``units`` – a list of unit specifications.  Each unit spec must contain
      ``number`` and optionally ``beds`` – a list of bed numbers.
    * All objects are created inside a single transaction; if any part fails
      the whole operation is rolled back.
    """
    with transaction.atomic():
        building = Building.objects.create(
            name=name,
            property_type=property_type,
            created_by=created_by,
        )
        for blk in blocks:
            block = Block.objects.create(
                building=building,
                name=blk["name"],
                created_by=created_by,
            )
            for unit_spec in blk.get("units", []):
                unit = Unit.objects.create(
                    building=building,
                    block=block,
                    number=unit_spec["number"],
                    capacity=unit_spec.get("capacity", 1),
                    created_by=created_by,
                )
                for bed_number in unit_spec.get("beds", []):
                    Bed.objects.create(
                        unit=unit,
                        bed_number=bed_number,
                        created_by=created_by,
                    )
        return building


def add_bed(unit_id: int, bed_number: str, status: str = "VACANT", created_by: User | None = None) -> Bed:
    """Create a new bed for the given unit.
    ``status`` must be a valid BedStatus choice.
    """
    unit = Unit.objects.get(pk=unit_id)
    bed = Bed.objects.create(
        unit=unit,
        bed_number=bed_number,
        status=status,
        created_by=created_by or unit.created_by,
    )
    return bed


def remove_bed(bed_id: int) -> None:
    """Delete a bed.  The model's ``clean`` method ensures it can only be
    removed when it is not allocated.
    """
    Bed.objects.filter(pk=bed_id).delete()


def update_bed_status(bed_id: int, status: str) -> Bed:
    """Update the status of an existing bed (e.g., VACANT → OCCUPIED)."""
    bed = Bed.objects.get(pk=bed_id)
    bed.status = status
    bed.full_clean()
    bed.save(update_fields=["status"])
    return bed


def allocate_unit(
    occupant_id: int,
    unit_id: int,
    bed_id: int | None = None,
    start_date: Any = None,
    end_date: Any = None,
    allocated_by: User | None = None,
) -> Allocation:
    """Create an Allocation after performing the model‑level validation.
    ``start_date`` and ``end_date`` can be ``date`` objects or strings that
    ``django`` can coerce.
    """
    occupant = Occupant.objects.get(pk=occupant_id)
    unit = Unit.objects.get(pk=unit_id)
    bed = Bed.objects.get(pk=bed_id) if bed_id is not None else None

    allocation = Allocation(
        occupant=occupant,
        unit=unit,
        bed=bed,
        start_date=start_date,
        end_date=end_date,
        allocated_by=allocated_by,
        status="ACTIVE",
    )
    allocation.full_clean()
    allocation.save()
    # Update dependent statuses (unit and bed) – simple example
    unit.status = "OCCUPIED"
    unit.save(update_fields=["status"])
    if bed:
        bed.status = "OCCUPIED"
        bed.save(update_fields=["status"])
    return allocation


def vacate_allocation(allocation_id: int, vacated_by: User | None = None) -> Allocation:
    """Mark an allocation as vacated.  Sets ``status`` to ``VACATED`` and clears
    the end_date if not already set.  Also updates related unit/bed statuses.
    """
    allocation = Allocation.objects.select_related("unit", "bed").get(pk=allocation_id)
    allocation.status = "VACATED"
    allocation.end_date = allocation.end_date or timezone.now().date()
    allocation.save(update_fields=["status", "end_date"])
    # Re‑calculate occupancy status for the unit
    unit = allocation.unit
    unit.status = "VACANT"
    unit.save(update_fields=["status"])
    if allocation.bed:
        allocation.bed.status = "VACANT"
        allocation.bed.save(update_fields=["status"])
    return allocation


def sync_status() -> None:
    """Utility that synchronises derived status fields across the estate.
    It can be called as a management command or a periodic task.
    """
    # Example implementation – set unit status based on active allocations
    for unit in Unit.objects.all():
        active_allocs = unit.allocations.filter(status="ACTIVE")
        if not active_allocs.exists():
            unit.status = "VACANT"
        else:
            # If any bed is allocated, mark unit as OCCUPIED, otherwise PARTIAL
            if unit.beds.filter(status="OCCUPIED").exists():
                unit.status = "OCCUPIED"
            else:
                unit.status = "PARTIAL"
        unit.save(update_fields=["status"])

# Amenity helper examples (optional, but useful for the API layer)

def set_amenity_value(
    definition_id: int,
    target: Dict[str, int],
    value: Any,
    created_by: User,
) -> AmenityValue:
    """Create or update an ``AmenityValue`` for a specific target.
    ``target`` must contain exactly one key among ``building``, ``block`` or ``unit``.
    """
    definition = AmenityDefinition.objects.get(pk=definition_id)
    # Resolve the exclusive target
    if len([k for k, v in target.items() if v]) != 1:
        raise ValueError("Exactly one target (building/block/unit) must be specified")
    amenity, _ = AmenityValue.objects.update_or_create(
        definition=definition,
        building_id=target.get("building"),
        block_id=target.get("block"),
        unit_id=target.get("unit"),
        defaults={
            "value_boolean": value if definition.value_type == "BOOLEAN" else None,
            "value_number": value if definition.value_type == "NUMBER" else None,
            "value_text": value if definition.value_type == "TEXT" else "",
            "created_by": created_by,
        },
    )
    return amenity
