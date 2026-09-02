# Estate Management Module — Models Implementation Doc

## 1. Where this lives in the repo

New Django app, sibling to `config/`, inside `backend/`:

```
backend/
├── manage.py
├── db.sqlite3
├── pyproject.toml
├── config/                     # existing project settings
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
└── estate/                     # NEW APP
    ├── __init__.py
    ├── apps.py
    ├── models.py                # or models/ package — see note below
    ├── admin.py
    ├── serializers.py           # added in next phase
    ├── views.py                 # added in next phase
    ├── urls.py                  # added in next phase
    ├── permissions.py           # custom DRF permission classes (estate_admin / hall_assistant)
    ├── validators.py            # shared clean()/validation helpers
    ├── constants.py             # choice enums (PropertyType, OccupantType, etc.)
    ├── migrations/
    │   └── __init__.py
    └── tests/
        ├── __init__.py
        ├── test_models.py
        ├── test_validators.py
        └── ...
```

**Why a single app named `estate`:** it's one cohesive domain (buildings → blocks → units → beds → occupants → allocations → amenities). Splitting into multiple apps (`buildings`, `allocations`, `amenities`) would add cross-app FK/migration complexity for no real benefit at this scale. If it grows a lot later, you can still split — Django doesn't lock you in.

**Models file:** given 8 models with real logic, I'd split `models.py` into a package once it gets long:

```
estate/models/
    __init__.py      # re-exports everything, so `from estate.models import Building` still works
    building.py       # Building, Block
    unit.py            # Unit, Bed
    occupant.py        # Occupant, Allocation
    amenity.py          # AmenityDefinition, AmenityValue
    base.py              # shared TimeStampedModel abstract base
```

This is optional — a single `models.py` works fine too and is simpler for now. Recommend starting single-file, split only if it gets unwieldy (300+ lines).

### Integration into `config/settings.py` (when we get there)
```python
INSTALLED_APPS = [
    ...
    'rest_framework',
    'estate',
]
```
And in `config/urls.py`:
```python
path('api/estate/', include('estate.urls')),
```
This is the *only* touch point needed in the existing project files — confirms the "develop independently, plug in later" plan holds.

---

## 2. Shared abstract base

```python
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
```
Used by every model below (mentioned once here, not repeated per-model).

---

## 3. Enums / Choices (`constants.py`)

```python
class PropertyType(models.TextChoices):
    HOSTEL_BOYS = 'HOSTEL_BOYS', 'Boys Hostel'
    HOSTEL_GIRLS = 'HOSTEL_GIRLS', 'Girls Hostel'
    SHOP_COMPLEX = 'SHOP_COMPLEX', 'Shop Complex'
    TEACHER_QUARTERS = 'TEACHER_QUARTERS', 'Teacher Quarters'

class UnitStatus(models.TextChoices):
    VACANT = 'VACANT', 'Vacant'
    PARTIAL = 'PARTIAL', 'Partially Occupied'
    OCCUPIED = 'OCCUPIED', 'Fully Occupied'
    MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'

class BedStatus(models.TextChoices):
    VACANT = 'VACANT', 'Vacant'
    OCCUPIED = 'OCCUPIED', 'Occupied'
    MAINTENANCE = 'MAINTENANCE', 'Under Maintenance'

class OccupantType(models.TextChoices):
    STUDENT = 'STUDENT', 'Student'
    TEACHER = 'TEACHER', 'Teacher'
    SHOPKEEPER = 'SHOPKEEPER', 'Shopkeeper'

class AllocationStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    VACATED = 'VACATED', 'Vacated'
    CANCELLED = 'CANCELLED', 'Cancelled'

class AmenityLevel(models.TextChoices):
    BUILDING = 'BUILDING', 'Building'
    BLOCK = 'BLOCK', 'Block'
    UNIT = 'UNIT', 'Unit'

class AmenityValueType(models.TextChoices):
    BOOLEAN = 'BOOLEAN', 'Yes/No'
    NUMBER = 'NUMBER', 'Number'
    TEXT = 'TEXT', 'Text'
```

Keeping these centralized avoids magic strings scattered across models/serializers/views.

---

## 4. Model-by-model spec

### 4.1 `Building`
```python
class Building(TimeStampedModel):
    name = models.CharField(max_length=150)
    property_type = models.CharField(max_length=20, choices=PropertyType.choices)
    location = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='buildings_created')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.get_property_type_display()})"
```
- `on_delete=PROTECT` on `created_by` — don't let a user deletion cascade-delete buildings.

### 4.2 `Block`
```python
class Block(TimeStampedModel):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='blocks')
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='blocks_created')

    class Meta:
        unique_together = ('building', 'name')
        ordering = ['building', 'name']
```
- `CASCADE` on `building` is intentional: deleting a Building should remove its Blocks (soft-delete via `is_active` is recommended operationally — see §6).

### 4.3 `Unit`
```python
class Unit(TimeStampedModel):
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='units')
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='units', null=True, blank=True)
    number = models.CharField(max_length=50)   # "Room No" / "Shop No" — label resolved in serializer by property_type
    capacity = models.PositiveIntegerField(default=1)
    status = models.CharField(max_length=20, choices=UnitStatus.choices, default=UnitStatus.VACANT)
    floor = models.CharField(max_length=20, blank=True)
    area_sqft = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    monthly_rent = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='units_created')

    class Meta:
        unique_together = ('building', 'number')
        ordering = ['building', 'block', 'number']

    def clean(self):
        if self.block_id and self.block.building_id != self.building_id:
            raise ValidationError("Block must belong to the same Building as the Unit.")
```
- `status` is **stored, not computed live**, and kept in sync by signals/service functions whenever an `Allocation`/`Bed` status changes (see §7). Storing it avoids recalculating on every read for list views (e.g. "show all vacant rooms").

### 4.4 `Bed`
```python
class Bed(TimeStampedModel):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='beds')
    bed_number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=BedStatus.choices, default=BedStatus.VACANT)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ('unit', 'bed_number')
        ordering = ['unit', 'bed_number']
```
- Only created for units where `capacity > 1` — enforced in the service/view layer that creates beds (e.g. "generate N beds for this unit"), not a hard DB constraint, since capacity could theoretically be edited later.

### 4.5 `Occupant`
```python
class Occupant(TimeStampedModel):
    occupant_type = models.CharField(max_length=20, choices=OccupantType.choices)
    full_name = models.CharField(max_length=150)
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    external_ref_id = models.CharField(max_length=100, blank=True, null=True)  # generic placeholder, students only, unused for now
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='occupants_created')

    class Meta:
        ordering = ['full_name']
```

### 4.6 `Allocation`
```python
class Allocation(TimeStampedModel):
    occupant = models.ForeignKey(Occupant, on_delete=models.CASCADE, related_name='allocations')
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='allocations')
    bed = models.ForeignKey(Bed, on_delete=models.CASCADE, related_name='allocations', null=True, blank=True)
    allocated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='allocations_made')
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
        ]

    def clean(self):
        if self.unit.capacity > 1 and self.bed_id is None:
            raise ValidationError("Bed is required for multi-capacity units (e.g. hostel rooms).")
        if self.unit.capacity == 1 and self.bed_id is not None:
            raise ValidationError("Bed must not be set for single-capacity units (e.g. shops/quarters).")
        if self.bed_id and self.bed.unit_id != self.unit_id:
            raise ValidationError("Bed must belong to the selected Unit.")
```
- The two partial `UniqueConstraint`s are the DB-level guarantee against double-booking — this is the most important integrity rule in the whole schema, so it's enforced at the database, not just in serializer validation.

### 4.7 `AmenityDefinition`
```python
class AmenityDefinition(TimeStampedModel):
    name = models.CharField(max_length=100)
    level = models.CharField(max_length=20, choices=AmenityLevel.choices)
    value_type = models.CharField(max_length=20, choices=AmenityValueType.choices)
    applicable_property_types = models.JSONField(default=list, blank=True)  # list[str] of PropertyType values; empty = all
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='amenity_definitions_created')

    class Meta:
        unique_together = ('name', 'level')
        ordering = ['level', 'name']
```
- `applicable_property_types` as a `JSONField` list is simpler than a M2M table for a small, rarely-queried list of strings. If you need to filter by it heavily in SQL later, swap to M2M — not a big migration.
- **Lock rule (your decision #1 — disallow changes once in use):** enforced in the serializer/view `update()`, not the model itself:
  ```python
  def has_values(self):
      return self.values.exists()
  ```
  On `PATCH`/`PUT`, if `has_values()` is True, reject changes to `level` and `value_type` (400 response), everything else (name, is_active, applicable_property_types) remains editable.

### 4.8 `AmenityValue`
```python
class AmenityValue(TimeStampedModel):
    definition = models.ForeignKey(AmenityDefinition, on_delete=models.CASCADE, related_name='values')
    building = models.ForeignKey(Building, on_delete=models.CASCADE, related_name='amenity_values', null=True, blank=True)
    block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name='amenity_values', null=True, blank=True)
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name='amenity_values', null=True, blank=True)
    value_boolean = models.BooleanField(null=True, blank=True)
    value_number = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    value_text = models.TextField(blank=True)

    class Meta:
        unique_together = ('definition', 'building', 'block', 'unit')

    def clean(self):
        targets = [self.building_id, self.block_id, self.unit_id]
        if sum(bool(t) for t in targets) != 1:
            raise ValidationError("Exactly one of building/block/unit must be set.")
        level_map = {
            AmenityLevel.BUILDING: self.building_id,
            AmenityLevel.BLOCK: self.block_id,
            AmenityLevel.UNIT: self.unit_id,
        }
        if not level_map[self.definition.level]:
            raise ValidationError("Target level does not match the amenity definition's level.")
```
- No `updated_at`-only history — this table is explicitly current-state, overwritten on edit (per your decision #4).

---

## 5. Admin registration (`admin.py`)

Register all 8 models with `list_display`, `list_filter` (esp. `property_type`, `status`, `occupant_type`), and inline editors:
- `BlockInline` / `UnitInline` on `BuildingAdmin`
- `BedInline` on `UnitAdmin`
- This gives estate_admin a working UI *immediately*, even before the custom frontend is built — useful as a fallback/testing tool.

---

## 6. Soft-delete convention

Every model has `is_active`. Convention: **never hard-delete** Buildings/Blocks/Units/Occupants/Amenity records via the API — only toggle `is_active=False`. Hard deletes stay available via Django admin/shell for genuine cleanup. This protects allocation history and avoids `CASCADE` surprises wiping out occupancy records.

---

## 7. Status sync (Unit/Bed `status` field)

Since `Unit.status` and `Bed.status` are stored fields (for fast filtering), they need to be kept in sync whenever an `Allocation` is created/vacated. Two options:
- **Django signals** (`post_save`/`post_delete` on `Allocation`) — automatic, but can be harder to trace/debug.
- **Service-layer functions** called explicitly from views (`allocate_unit()`, `vacate_allocation()`) — more explicit, easier to test and reason about.

**Recommendation:** service-layer functions, not signals. Keeps the logic visible in one place (`estate/services.py`, added in the next phase) rather than "magic" side effects. We'll finalize this when we design views.

---

## 8. Migration plan

1. `python manage.py makemigrations estate` → generates `0001_initial.py` with all 8 models.
2. Since this app is being built standalone first: its migration history is self-contained and won't conflict with the main ERP's migrations when merged later — Django tracks migrations per-app.
3. On integration into the main ERP: copy `estate/` folder in, add to `INSTALLED_APPS`, run `migrate` — the existing `0001_initial.py` just applies fresh against the ERP's DB (assuming the ERP doesn't already have an app named `estate`).

---

## 9. Summary table

| # | Model | Required parents | Optional |
|---|---|---|---|
| 1 | Building | — | — |
| 2 | Block | Building | entire model optional per building |
| 3 | Unit | Building | Block |
| 4 | Bed | Unit | only for capacity > 1 |
| 5 | Occupant | — | — |
| 6 | Allocation | Occupant, Unit | Bed (only if unit capacity > 1) |
| 7 | AmenityDefinition | — | — |
| 8 | AmenityValue | AmenityDefinition + exactly one of (Building/Block/Unit) | — |

This is the complete, locked model spec. Next phase: serializers + views + service-layer functions (`allocate_unit`, `vacate_allocation`, status-sync helpers) and the permission classes for `estate_admin` / `hall_assistant` / public read-only.
