"""services.py

All structural writes live here so every invariant has ONE code path.
Views/serializers call these; they never mutate Unit/Bed/Allocation state directly.

Conventions
* Every public function runs in ``transaction.atomic()``.
* Failures raise ``django.core.exceptions.ValidationError`` (views turn these into HTTP 400).
* ``Unit.status`` / ``Bed.status`` are only ever changed here (no signals).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .constants import (
    HOSTEL_PROPERTY_TYPES,
    AllocationStatus,
    AmenityValueType,
    BedStatus,
    OccupantType,
    PropertyType,
    UnitStatus,
)
from .models import (
    Allocation,
    AmenityDefinition,
    AmenityValue,
    Bed,
    Block,
    Building,
    Occupant,
    Unit,
)

ACTIVE = AllocationStatus.ACTIVE

# Which building types each kind of occupant may be placed in.
OCCUPANT_PROPERTY_TYPES = {
    OccupantType.STUDENT: HOSTEL_PROPERTY_TYPES,
    OccupantType.TEACHER: (PropertyType.TEACHER_QUARTERS,),
    OccupantType.SHOPKEEPER: (PropertyType.SHOP_COMPLEX,),
}
# Boys hostel -> M, girls hostel -> F.
HOSTEL_GENDER = {PropertyType.HOSTEL_BOYS: 'M', PropertyType.HOSTEL_GIRLS: 'F'}

MAX_BULK_UNITS = 500


def _fail(message: str, field: str | None = None):
    raise ValidationError({field: message} if field else message)


# ---------------------------------------------------------------------------
# Status sync
# ---------------------------------------------------------------------------

def recompute_bed_status(bed: Bed) -> Bed:
    """ACTIVE allocation -> OCCUPIED, else VACANT. MAINTENANCE is left alone."""
    if bed.status == BedStatus.MAINTENANCE:
        return bed
    new = BedStatus.OCCUPIED if bed.allocations.filter(status=ACTIVE).exists() else BedStatus.VACANT
    if bed.status != new:
        bed.status = new
        bed.save(update_fields=['status', 'updated_at'])
    return bed


def recompute_unit_status(unit: Unit) -> Unit:
    """VACANT / PARTIAL / OCCUPIED from live allocations. MAINTENANCE is left alone.

    Hostel units: compared against bookable beds (active and not in maintenance).
    Single-capacity units: occupied iff there is an ACTIVE allocation.
    """
    if unit.status == UnitStatus.MAINTENANCE:
        return unit
    if unit.capacity > 1:
        bookable = unit.beds.filter(is_active=True).exclude(status=BedStatus.MAINTENANCE).count()
        taken = unit.allocations.filter(status=ACTIVE, bed__is_active=True).count()
        if taken == 0:
            new = UnitStatus.VACANT
        elif taken >= bookable:
            new = UnitStatus.OCCUPIED
        else:
            new = UnitStatus.PARTIAL
    else:
        new = UnitStatus.OCCUPIED if unit.allocations.filter(status=ACTIVE).exists() else UnitStatus.VACANT
    if unit.status != new:
        unit.status = new
        unit.save(update_fields=['status', 'updated_at'])
    return unit


def sync_status() -> int:
    """Recompute every bed and unit status (repair tool). Returns number of rows changed."""
    changed = 0
    with transaction.atomic():
        for bed in Bed.objects.select_related('unit'):
            before = bed.status
            recompute_bed_status(bed)
            changed += before != bed.status
        for unit in Unit.objects.all():
            before = unit.status
            recompute_unit_status(unit)
            changed += before != unit.status
    return changed


# ---------------------------------------------------------------------------
# Amenities
# ---------------------------------------------------------------------------

def _coerce_amenity_value(definition: AmenityDefinition, value: Any):
    vt = definition.value_type
    if vt == AmenityValueType.BOOLEAN:
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in ('true', 'yes', 'false', 'no'):
            return value.strip().lower() in ('true', 'yes')
        _fail(f"'{definition.name}' expects true/false.", 'value')
    if vt == AmenityValueType.NUMBER:
        if isinstance(value, bool) or value is None or value == '':
            _fail(f"'{definition.name}' expects a number.", 'value')
        try:
            return Decimal(str(value))
        except InvalidOperation:
            _fail(f"'{definition.name}' expects a number.", 'value')
    if value is None or isinstance(value, (dict, list)):
        _fail(f"'{definition.name}' expects text.", 'value')
    return str(value)


def set_amenity_value(
    definition: AmenityDefinition,
    value: Any,
    *,
    building: Building | None = None,
    block: Block | None = None,
    unit: Unit | None = None,
) -> AmenityValue:
    """Upsert the value of ``definition`` on exactly one target (overwrites, no history)."""
    if sum(t is not None for t in (building, block, unit)) != 1:
        _fail("Exactly one of building/block/unit must be given.")
    if not definition.is_active:
        _fail(f"Amenity '{definition.name}' is inactive.", 'definition')
    coerced = _coerce_amenity_value(definition, value)
    vt = definition.value_type
    with transaction.atomic():
        lookup = dict(definition=definition, building=building, block=block, unit=unit)
        obj = AmenityValue.objects.filter(**lookup).first() or AmenityValue(**lookup)
        obj.value_boolean = coerced if vt == AmenityValueType.BOOLEAN else None
        obj.value_number = coerced if vt == AmenityValueType.NUMBER else None
        obj.value_text = coerced if vt == AmenityValueType.TEXT else ''
        obj.full_clean()
        obj.save()
    return obj


def apply_amenities(specs: Iterable[dict] | None, **target) -> None:
    """``specs`` = [{"definition": <AmenityDefinition|id>, "value": ...}, ...]"""
    for spec in specs or []:
        definition = spec['definition']
        if not isinstance(definition, AmenityDefinition):
            try:
                definition = AmenityDefinition.objects.get(pk=definition)
            except AmenityDefinition.DoesNotExist:
                _fail(f"Amenity definition {definition} does not exist.", 'amenities')
        set_amenity_value(definition, spec.get('value'), **target)


# ---------------------------------------------------------------------------
# Beds / capacity
# ---------------------------------------------------------------------------

def _bed_key(bed: Bed):
    n = bed.bed_number
    return (0, int(n), n) if n.isdigit() else (1, 0, n)


def _next_bed_number(unit: Unit) -> int:
    nums = [int(n) for n in unit.beds.values_list('bed_number', flat=True) if n.isdigit()]
    return max(nums, default=0) + 1


def _activate_or_create_beds(unit: Unit, count: int) -> list[Bed]:
    """Bring ``count`` more beds online: reactivate soft-deleted ones first, then create new."""
    out: list[Bed] = []
    inactive = sorted(unit.beds.filter(is_active=False), key=_bed_key)
    for bed in inactive[:count]:
        bed.is_active = True
        bed.status = BedStatus.VACANT
        bed.save(update_fields=['is_active', 'status', 'updated_at'])
        out.append(bed)
    nxt = _next_bed_number(unit)
    for i in range(count - len(out)):
        out.append(Bed.objects.create(unit=unit, bed_number=str(nxt + i)))
    return out


def _lock_unit(unit: Unit) -> Unit:
    return Unit.objects.select_for_update().select_related('building', 'block').get(pk=unit.pk)


def _apply_capacity(unit: Unit, new: int) -> None:
    """Change capacity + beds in memory/DB. Caller must full_clean()/save() the unit."""
    old = unit.capacity
    if new < 1:
        _fail("Capacity must be at least 1.", 'capacity')
    if new == old:
        return
    if new > 1 and unit.building.property_type not in HOSTEL_PROPERTY_TYPES:
        _fail("Only hostel units can have a capacity greater than 1.", 'capacity')
    crossing = (old == 1) != (new == 1)
    if crossing and unit.allocations.filter(status=ACTIVE).exists():
        _fail("Cannot switch between single and multi-bed while the unit has active allocations.", 'capacity')

    active_beds = list(unit.beds.filter(is_active=True))
    if new == 1:
        for bed in active_beds:
            bed.is_active = False
            bed.save(update_fields=['is_active', 'updated_at'])
    elif new > len(active_beds):
        _activate_or_create_beds(unit, new - len(active_beds))
    else:
        to_remove = len(active_beds) - new
        free = [
            b for b in active_beds
            if b.status != BedStatus.OCCUPIED and not b.allocations.filter(status=ACTIVE).exists()
        ]
        if len(free) < to_remove:
            _fail(f"Need {to_remove} vacant bed(s) to remove but only {len(free)} are free.", 'capacity')
        for bed in sorted(free, key=_bed_key, reverse=True)[:to_remove]:
            bed.is_active = False
            bed.save(update_fields=['is_active', 'updated_at'])
    unit.capacity = new


def add_bed(unit: Unit, bed_number: str | None = None) -> Bed:
    """Add one bed to a multi-bed hostel unit (capacity += 1)."""
    with transaction.atomic():
        unit = _lock_unit(unit)
        if unit.capacity < 2:
            _fail("Single-capacity unit has no beds. Change the unit's capacity to 2 or more instead.", 'unit')
        number = str(bed_number).strip() if bed_number not in (None, '') else None
        if number is None:
            bed = _activate_or_create_beds(unit, 1)[0]  # reuse a removed bed's number first
        else:
            existing = unit.beds.filter(bed_number=number).first()
            if existing and existing.is_active:
                _fail(f"Bed '{number}' already exists in this unit.", 'bed_number')
            if existing:
                existing.is_active = True
                existing.status = BedStatus.VACANT
                existing.save(update_fields=['is_active', 'status', 'updated_at'])
                bed = existing
            else:
                bed = Bed(unit=unit, bed_number=number)
                bed.full_clean()
                bed.save()
        unit.capacity += 1
        unit.save(update_fields=['capacity', 'updated_at'])
        recompute_unit_status(unit)
    return bed


def remove_bed(bed: Bed) -> Bed:
    """Soft-delete a bed (only if free) and capacity -= 1. A bedded unit keeps >= 2 beds."""
    with transaction.atomic():
        bed = Bed.objects.select_for_update().get(pk=bed.pk)
        unit = _lock_unit(bed.unit)
        if not bed.is_active:
            _fail("Bed is already removed.")
        if bed.allocations.filter(status=ACTIVE).exists():
            _fail("Cannot remove a bed with an active allocation. Vacate it first.")
        if unit.capacity <= 2:
            _fail("A multi-bed unit needs at least 2 beds. Change the unit's capacity instead.")
        bed.is_active = False
        bed.save(update_fields=['is_active', 'updated_at'])
        unit.capacity -= 1
        unit.save(update_fields=['capacity', 'updated_at'])
        recompute_unit_status(unit)
    return bed


def rename_bed(bed: Bed, new_number: str) -> Bed:
    new_number = (new_number or '').strip()
    if not new_number:
        _fail("Bed number is required.", 'bed_number')
    with transaction.atomic():
        bed = Bed.objects.select_for_update().get(pk=bed.pk)
        if bed.unit.beds.filter(bed_number=new_number).exclude(pk=bed.pk).exists():
            _fail(f"Bed '{new_number}' already exists in this unit.", 'bed_number')
        bed.bed_number = new_number
        bed.full_clean()
        bed.save(update_fields=['bed_number', 'updated_at'])
    return bed


def set_bed_maintenance(bed: Bed, on: bool) -> Bed:
    with transaction.atomic():
        bed = Bed.objects.select_for_update().get(pk=bed.pk)
        unit = _lock_unit(bed.unit)
        if on:
            if bed.allocations.filter(status=ACTIVE).exists():
                _fail("Cannot put an occupied bed under maintenance. Vacate it first.")
            bed.status = BedStatus.MAINTENANCE
        else:
            bed.status = BedStatus.VACANT
        bed.save(update_fields=['status', 'updated_at'])
        recompute_bed_status(bed)
        recompute_unit_status(unit)
    return bed


def set_unit_maintenance(unit: Unit, on: bool) -> Unit:
    with transaction.atomic():
        unit = _lock_unit(unit)
        if on:
            if unit.allocations.filter(status=ACTIVE).exists():
                _fail("Cannot put an occupied unit under maintenance. Vacate it first.")
            unit.status = UnitStatus.MAINTENANCE
        else:
            unit.status = UnitStatus.VACANT
        unit.save(update_fields=['status', 'updated_at'])
        recompute_unit_status(unit)
    return unit


# ---------------------------------------------------------------------------
# Structure: building / block / unit
# ---------------------------------------------------------------------------

def create_unit(
    *,
    building: Building,
    number: str,
    created_by,
    block: Block | None = None,
    capacity: int = 1,
    floor: str = '',
    area_sqft=None,
    monthly_rent=None,
    amenities: list[dict] | None = None,
) -> Unit:
    """Create a unit; capacity > 1 auto-generates beds "1".."N" in the same transaction."""
    with transaction.atomic():
        unit = Unit(
            building=building, block=block, number=number, capacity=capacity, floor=floor or '',
            area_sqft=area_sqft, monthly_rent=monthly_rent, created_by=created_by,
        )
        unit.full_clean()
        unit.save()
        if capacity > 1:
            _activate_or_create_beds(unit, capacity)
        apply_amenities(amenities, unit=unit)
    return unit


def update_unit(unit: Unit, **fields) -> Unit:
    """Update a unit. Capacity changes also add/remove beds (see _apply_capacity)."""
    fields.pop('building', None)  # a unit never moves between buildings
    fields.pop('status', None)    # status is service-managed
    capacity = fields.pop('capacity', None)
    with transaction.atomic():
        unit = _lock_unit(unit)
        for k, v in fields.items():
            setattr(unit, k, v)
        if capacity is not None:
            _apply_capacity(unit, capacity)
        unit.full_clean()
        unit.save()
        recompute_unit_status(unit)
    return unit


def bulk_create_units(
    *,
    building: Building,
    start: int,
    end: int,
    created_by,
    block: Block | None = None,
    prefix: str = '',
    capacity: int = 1,
    floor: str = '',
    area_sqft=None,
    monthly_rent=None,
) -> list[Unit]:
    """Bulk helper: units ``prefix+start`` .. ``prefix+end`` (e.g. rooms 101-120, capacity 4)."""
    if end < start:
        _fail("'end' must be >= 'start'.", 'end')
    if end - start + 1 > MAX_BULK_UNITS:
        _fail(f"At most {MAX_BULK_UNITS} units per request.", 'end')
    numbers = [f"{prefix}{n}" for n in range(start, end + 1)]
    with transaction.atomic():
        clash = list(Unit.objects.filter(building=building, number__in=numbers).values_list('number', flat=True))
        if clash:
            _fail(f"Units already exist: {', '.join(clash[:10])}", 'start')
        return [
            create_unit(
                building=building, block=block, number=n, capacity=capacity, floor=floor,
                area_sqft=area_sqft, monthly_rent=monthly_rent, created_by=created_by,
            )
            for n in numbers
        ]


def create_building_with_structure(
    *,
    name: str,
    property_type: str,
    created_by,
    location: str = '',
    amenities: list[dict] | None = None,
    blocks: list[dict] | None = None,
    units: list[dict] | None = None,
) -> Building:
    """One atomic transaction for the whole wizard payload.

    blocks: [{"name", "amenities": [...], "units": [unit_spec, ...]}]
    units:  [unit_spec, ...]  (attached straight to the building, no block)
    unit_spec: {"number", "capacity", "floor", "area_sqft", "monthly_rent", "amenities": [...]}
    amenity spec: {"definition": <id|AmenityDefinition>, "value": ...}
    """
    with transaction.atomic():
        building = Building(name=name, property_type=property_type, location=location or '', created_by=created_by)
        building.full_clean()
        building.save()
        apply_amenities(amenities, building=building)

        for spec in blocks or []:
            block = Block(building=building, name=spec['name'], created_by=created_by)
            block.full_clean()
            block.save()
            apply_amenities(spec.get('amenities'), block=block)
            for u in spec.get('units') or []:
                create_unit(building=building, block=block, created_by=created_by, **u)

        for u in units or []:
            create_unit(building=building, block=None, created_by=created_by, **u)
    return building


# ---------------------------------------------------------------------------
# Soft delete
# ---------------------------------------------------------------------------

def _active_allocations_for(obj):
    qs = Allocation.objects.filter(status=ACTIVE)
    if isinstance(obj, Building):
        return qs.filter(unit__building=obj)
    if isinstance(obj, Block):
        return qs.filter(unit__block=obj)
    if isinstance(obj, Unit):
        return qs.filter(unit=obj)
    if isinstance(obj, Occupant):
        return qs.filter(occupant=obj)
    return qs.none()


def deactivate(obj):
    """Soft delete. Blocked while anything underneath still has an ACTIVE allocation."""
    with transaction.atomic():
        if _active_allocations_for(obj).exists():
            _fail("Cannot deactivate: there are active allocations. Vacate them first.")
        obj.is_active = False
        obj.save(update_fields=['is_active', 'updated_at'])
    return obj


def activate(obj):
    if isinstance(obj, Block) and not obj.building.is_active:
        _fail("Activate the building first.")
    if isinstance(obj, Unit):
        if not obj.building.is_active or (obj.block_id and not obj.block.is_active):
            _fail("Activate the building/block first.")
    obj.is_active = True
    obj.save(update_fields=['is_active', 'updated_at'])
    return obj


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

def allocate_unit(
    *,
    occupant: Occupant,
    unit: Unit,
    allocated_by,
    bed: Bed | None = None,
    start_date=None,
    end_date=None,
) -> Allocation:
    """Place an occupant in a unit (single-capacity) or a bed (hostel), enforcing every rule."""
    with transaction.atomic():
        unit = _lock_unit(unit)
        occupant = Occupant.objects.select_for_update().get(pk=occupant.pk)
        if bed is not None:
            bed = Bed.objects.select_for_update().get(pk=bed.pk)
        building = unit.building

        if not occupant.is_active:
            _fail("Occupant is inactive.", 'occupant')
        if not (unit.is_active and building.is_active):
            _fail("Unit (or its building) is inactive.", 'unit')
        if unit.status == UnitStatus.MAINTENANCE:
            _fail("Unit is under maintenance.", 'unit')

        # occupant type <-> building type
        allowed_types = OCCUPANT_PROPERTY_TYPES[occupant.occupant_type]
        if building.property_type not in allowed_types:
            _fail(
                f"A {occupant.get_occupant_type_display().lower()} cannot be placed in a "
                f"{building.get_property_type_display().lower()}.",
                'unit',
            )
        # boys/girls hostel
        if building.property_type in HOSTEL_GENDER:
            if not occupant.gender:
                _fail("Student gender is required for hostel allocation.", 'occupant')
            if occupant.gender != HOSTEL_GENDER[building.property_type]:
                _fail(f"This student cannot be placed in a {building.get_property_type_display().lower()}.", 'unit')

        # one active allocation per student/teacher (shopkeepers may hold several shops)
        if occupant.occupant_type != OccupantType.SHOPKEEPER and occupant.allocations.filter(status=ACTIVE).exists():
            _fail("Occupant already has an active allocation. Vacate it first.", 'occupant')

        # bed rules
        if unit.capacity > 1 and bed is None:
            _fail("Bed is required for multi-bed units.", 'bed')
        if unit.capacity == 1 and bed is not None:
            _fail("Bed must not be set for single-capacity units.", 'bed')
        if bed is not None:
            if bed.unit_id != unit.id:
                _fail("Bed does not belong to this unit.", 'bed')
            if not bed.is_active:
                _fail("Bed is removed.", 'bed')
            if bed.status == BedStatus.MAINTENANCE:
                _fail("Bed is under maintenance.", 'bed')
            if bed.allocations.filter(status=ACTIVE).exists():
                _fail("Bed is already occupied.", 'bed')
        elif unit.allocations.filter(status=ACTIVE, bed__isnull=True).exists():
            _fail("Unit is already occupied.", 'unit')

        allocation = Allocation(
            occupant=occupant, unit=unit, bed=bed, allocated_by=allocated_by,
            start_date=start_date or timezone.localdate(), end_date=end_date, status=ACTIVE,
        )
        allocation.full_clean()
        try:
            with transaction.atomic():
                allocation.save()
        except IntegrityError:
            _fail("This bed/unit was just taken by someone else.")

        if bed is not None:
            recompute_bed_status(bed)
        recompute_unit_status(unit)
    return allocation


def _close_allocation(allocation: Allocation, new_status: str, end_date=None) -> Allocation:
    with transaction.atomic():
        alloc = Allocation.objects.select_for_update().select_related('unit', 'bed').get(pk=allocation.pk)
        if alloc.status != ACTIVE:
            _fail(f"Allocation is already {alloc.get_status_display().lower()}.")
        if new_status == AllocationStatus.VACATED:
            end = end_date or timezone.localdate()
            if end < alloc.start_date:
                _fail("End date cannot be before the start date.", 'end_date')
            alloc.end_date = end
        alloc.status = new_status
        alloc.save(update_fields=['status', 'end_date', 'updated_at'])
        if alloc.bed_id:
            recompute_bed_status(alloc.bed)
        recompute_unit_status(Unit.objects.get(pk=alloc.unit_id))
    return alloc


def vacate_allocation(allocation: Allocation, end_date=None) -> Allocation:
    """Normal move-out: status -> VACATED, end_date set (default today). History is kept."""
    return _close_allocation(allocation, AllocationStatus.VACATED, end_date)


def cancel_allocation(allocation: Allocation) -> Allocation:
    """Entered by mistake / never took effect: status -> CANCELLED."""
    return _close_allocation(allocation, AllocationStatus.CANCELLED)
