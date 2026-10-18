from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from .constants import (
    PropertyType,
    HOSTEL_PROPERTY_TYPES,
    UnitStatus,
    BedStatus,
    OccupantType,
    Gender,
    AllocationStatus,
    AmenityLevel,
    AmenityValueType,
)


class TimeStampedModel(models.Model):
    """Abstract base model providing self-updating creation and modification timestamps."""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Building(TimeStampedModel):
    name = models.CharField(max_length=150)
    property_type = models.CharField(max_length=20, choices=PropertyType.choices)
    location = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='buildings_created'
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_property_type_display()})"


class Block(TimeStampedModel):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='blocks')
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='blocks_created'
    )

    class Meta:
        unique_together = ('building', 'name')
        ordering = ['building', 'name']

    def __str__(self):
        return f"{self.building.name} - {self.name}"


class Unit(TimeStampedModel):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='units')
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='units', null=True, blank=True)
    number = models.CharField(max_length=50)  # Room No / Shop No
    capacity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=UnitStatus.choices, default=UnitStatus.VACANT)
    floor = models.CharField(max_length=20, blank=True)
    area_sqft = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='units_created'
    )

    class Meta:
        unique_together = ('building', 'number')
        ordering = ['building', 'block', 'number']
        constraints = [
            models.CheckConstraint(
                condition=Q(capacity__gte=1),
                name='unit_capacity_at_least_one',
            ),
        ]

    def clean(self):
        super().clean()
        if self.block_id and self.block.building_id != self.building_id:
            raise ValidationError("Block must belong to the same Building as the Unit.")
        if (
            self.capacity
            and self.capacity > 1
            and self.building_id
            and self.building.property_type not in HOSTEL_PROPERTY_TYPES
        ):
            raise ValidationError("Only hostel units can have a capacity greater than 1.")

    def __str__(self):
        return f"{self.building.name} - Unit {self.number}"


class Bed(TimeStampedModel):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='beds')
    bed_number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=BedStatus.choices, default=BedStatus.VACANT)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('unit', 'bed_number')
        ordering = ['unit', 'bed_number']

    def __str__(self):
        return f"{self.unit} - Bed {self.bed_number}"


class Occupant(TimeStampedModel):
    occupant_type = models.CharField(max_length=20, choices=OccupantType.choices)
    full_name = models.CharField(max_length=150)
    # Needed to enforce boys/girls hostel rules. Required for students (enforced in services).
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    external_ref_id = models.CharField(max_length=100, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='occupants_created'
    )

    class Meta:
        ordering = ['full_name']

    def __str__(self):
        return f"{self.full_name} ({self.get_occupant_type_display()})"


class Allocation(TimeStampedModel):
    occupant = models.ForeignKey(Occupant, on_delete=models.CASCADE, related_name='allocations')
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='allocations')
    bed = models.ForeignKey(Bed, on_delete=models.CASCADE, related_name='allocations', null=True, blank=True)
    allocated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='allocations_made'
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=AllocationStatus.choices, default=AllocationStatus.ACTIVE)

    class Meta:
        ordering = ['-start_date']
        constraints = [
            models.UniqueConstraint(
                fields=['bed'],
                condition=Q(status='ACTIVE'),
                name='unique_active_allocation_per_bed',
            ),
            models.UniqueConstraint(
                fields=['unit'],
                condition=Q(status='ACTIVE', bed__isnull=True),
                name='unique_active_allocation_per_unit_when_no_bed',
            ),
            models.CheckConstraint(
                condition=Q(end_date__isnull=True) | Q(end_date__gte=F('start_date')),
                name='allocation_end_not_before_start',
            ),
        ]

    def clean(self):
        super().clean()
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("End date cannot be before start date.")
        if not self.unit_id:
            return
        if self.unit.capacity > 1 and self.bed_id is None:
            raise ValidationError("Bed is required for multi-capacity units (e.g. hostel rooms).")
        if self.unit.capacity == 1 and self.bed_id is not None:
            raise ValidationError("Bed must not be set for single-capacity units (e.g. shops/quarters).")
        if self.bed_id and self.bed.unit_id != self.unit_id:
            raise ValidationError("Bed must belong to the selected Unit.")

    def __str__(self):
        return f"{self.occupant} -> {self.unit}"


class AmenityDefinition(TimeStampedModel):
    name = models.CharField(max_length=100)
    level = models.CharField(max_length=20, choices=AmenityLevel.choices)
    value_type = models.CharField(max_length=20, choices=AmenityValueType.choices)
    applicable_property_types = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='amenity_definitions_created'
    )

    class Meta:
        unique_together = ('name', 'level')
        ordering = ['level', 'name']

    def clean(self):
        super().clean()
        valid = set(PropertyType.values)
        if not isinstance(self.applicable_property_types, list) or any(
            p not in valid for p in self.applicable_property_types
        ):
            raise ValidationError(
                "applicable_property_types must be a list of valid property types."
            )

    def has_values(self):
        return self.values.exists()

    def __str__(self):
        return f"{self.name} ({self.get_level_display()})"


class AmenityValue(TimeStampedModel):
    definition = models.ForeignKey(AmenityDefinition, on_delete=models.CASCADE, related_name='values')
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='amenity_values', null=True, blank=True)
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='amenity_values', null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='amenity_values', null=True, blank=True)
    value_boolean = models.BooleanField(null=True, blank=True)
    value_number = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    value_text = models.TextField(blank=True)

    class Meta:
        # NOTE: unique_together on nullable columns does NOT work (NULLs are
        # distinct in SQL), so uniqueness is enforced per level instead.
        constraints = [
            models.UniqueConstraint(
                fields=['definition', 'building'],
                condition=Q(building__isnull=False),
                name='unique_amenity_value_per_building',
            ),
            models.UniqueConstraint(
                fields=['definition', 'block'],
                condition=Q(block__isnull=False),
                name='unique_amenity_value_per_block',
            ),
            models.UniqueConstraint(
                fields=['definition', 'unit'],
                condition=Q(unit__isnull=False),
                name='unique_amenity_value_per_unit',
            ),
            models.CheckConstraint(
                condition=(
                    Q(building__isnull=False, block__isnull=True, unit__isnull=True)
                    | Q(building__isnull=True, block__isnull=False, unit__isnull=True)
                    | Q(building__isnull=True, block__isnull=True, unit__isnull=False)
                ),
                name='amenity_value_exactly_one_target',
            ),
        ]

    def _target_building(self):
        if self.building_id:
            return self.building
        if self.block_id:
            return self.block.building
        if self.unit_id:
            return self.unit.building
        return None

    def clean(self):
        super().clean()
        targets = [self.building_id, self.block_id, self.unit_id]
        if sum(bool(t) for t in targets) != 1:
            raise ValidationError("Exactly one of building/block/unit must be set.")
        if not self.definition_id:
            return

        definition = self.definition

        level_map = {
            AmenityLevel.BUILDING: self.building_id,
            AmenityLevel.BLOCK: self.block_id,
            AmenityLevel.UNIT: self.unit_id,
        }
        if not level_map[definition.level]:
            raise ValidationError("Target level does not match the amenity definition's level.")

        allowed = definition.applicable_property_types
        building = self._target_building()
        if allowed and building and building.property_type not in allowed:
            raise ValidationError(
                "This amenity is not applicable to this building's property type."
            )

        filled = {
            AmenityValueType.BOOLEAN: self.value_boolean is not None,
            AmenityValueType.NUMBER: self.value_number is not None,
            AmenityValueType.TEXT: bool((self.value_text or "").strip()),
        }
        if not filled[definition.value_type]:
            raise ValidationError(
                f"A {definition.get_value_type_display()} value is required for this amenity."
            )
        if any(is_set for vtype, is_set in filled.items() if vtype != definition.value_type):
            raise ValidationError(
                "Only the value field matching the amenity's type may be set."
            )

    def __str__(self):
        return f"Value for {self.definition.name}"