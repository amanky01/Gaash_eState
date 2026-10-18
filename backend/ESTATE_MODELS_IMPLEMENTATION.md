# Estate Management Module — Models Implementation Doc

> Location: `backend/ESTATE_MODELS_IMPLEMENTATION.md` (next to `manage.py`).
> Status: models **locked** (rev 2 — constraint/validation patch applied). Next phase: services → permissions → serializers/views → tests.

---

## 1. Layout

```
backend/
├── manage.py
├── config/                    # project settings (touch points: INSTALLED_APPS, urls.py, REST_FRAMEWORK)
└── estate/
    ├── constants.py           # enums + HOSTEL_PROPERTY_TYPES
    ├── models.py              # 8 models (single file; split into a package past ~300 lines)
    ├── admin.py               # registered with inlines (next)
    ├── services.py            # all write logic: create tree, allocate, vacate, bed ops, status sync (next)
    ├── permissions.py         # IsEstateAdmin / IsHallAssistant (next)
    ├── serializers.py, views.py, urls.py   # next
    ├── migrations/
    └── tests/
```

**Rule:** views/serializers never write models directly for structural operations — they call `services.py`. One code path owns every invariant.

Integration into the ERP later: copy `estate/`, add `'estate'` to `INSTALLED_APPS`, `include('estate.urls')` under `api/estate/`, run `migrate`.

---

## 2. Hierarchy

```
Building ──┬── Block (optional) ──┬── Unit ── Bed (hostels only)
           └──────────────────────┘
           (Unit may attach straight to Building)

Occupant ── Allocation ── Unit / Bed
AmenityDefinition ── AmenityValue ── (Building | Block | Unit)
```

All models inherit `TimeStampedModel` (`created_at`, `updated_at`).

---

## 3. Enums (`constants.py`)

`PropertyType` (HOSTEL_BOYS, HOSTEL_GIRLS, SHOP_COMPLEX, TEACHER_QUARTERS) · `UnitStatus` · `BedStatus` · `OccupantType` (STUDENT, TEACHER, SHOPKEEPER) · `AllocationStatus` (ACTIVE, VACATED, CANCELLED) · `AmenityLevel` · `AmenityValueType` · `HOSTEL_PROPERTY_TYPES = (HOSTEL_BOYS, HOSTEL_GIRLS)`.

---

## 4. Models

### Building
`name`, `property_type`, `location`, `is_active`, `created_by` (PROTECT).

### Block (optional layer)
`building` (CASCADE), `name`, `is_active`, `created_by`. Unique `(building, name)`.

### Unit (room / shop / quarter)
`building` (always set), `block` (nullable), `number`, `capacity`, `status`, `floor`, `area_sqft`, `monthly_rent`, `is_active`, `created_by`.
- Unique `(building, number)`.
- **DB:** `CHECK capacity >= 1`.
- **clean():** block must belong to same building; `capacity > 1` only for hostel property types.
- "Room No" vs "Shop No" is a display label resolved from `building.property_type` in the serializer.
- `status` is stored and kept in sync by services (see §7).

### Bed
`unit`, `bed_number`, `status`, `is_active`. Unique `(unit, bed_number)`. Exists only when `unit.capacity > 1`.

### Occupant
`occupant_type`, `full_name`, `contact_number`, `email`, `external_ref_id` (generic, nullable; students only, unused for now), `is_active`, `created_by`.
Students are soft-linked to the ERP; teachers/shopkeepers are manual entries.

### Allocation
`occupant`, `unit`, `bed` (nullable), `allocated_by`, `start_date`, `end_date`, `status`.
- **DB:** one ACTIVE allocation per bed; one ACTIVE allocation per unit when `bed IS NULL`; `CHECK end_date IS NULL OR end_date >= start_date`.
- **clean():** bed required if `capacity > 1`; forbidden if `capacity == 1`; bed must belong to the unit; end ≥ start.
- Rows are never deleted — vacate flips status, so history is retained for free.

### AmenityDefinition
`name`, `level`, `value_type`, `applicable_property_types` (JSON list; empty = all), `is_active`, `created_by`. Unique `(name, level)`.
- **clean():** `applicable_property_types` must be a list of valid `PropertyType` values.
- **Lock rule:** `level` and `value_type` cannot change once `has_values()` is true. Enforced in serializer/service (400). Create a new definition instead.

### AmenityValue
`definition`, `building` / `block` / `unit` (exactly one), `value_boolean`, `value_number`, `value_text`.
- **DB:** `CHECK` exactly one target is set; **three partial unique constraints** — `(definition, building)`, `(definition, block)`, `(definition, unit)`.
  *(Rev 1 used `unique_together` across nullable columns, which never fires because SQL treats NULLs as distinct. Fixed.)*
- **clean():** target level matches `definition.level`; amenity's `applicable_property_types` includes the target's building type; only the value field matching `value_type` is set, and it must be non-empty.
- Current-state only; overwritten on edit, no history.

---

## 5. Validation rules — where each is enforced

| Rule | DB | `clean()` | Service |
|---|:-:|:-:|:-:|
| No double-booking of a bed / single-unit | ✅ | | ✅ (friendly error) |
| Bed required/forbidden by capacity | | ✅ | ✅ |
| Block belongs to unit's building | | ✅ | |
| Capacity ≥ 1 | ✅ | | |
| Capacity > 1 only for hostels | | ✅ | |
| Allocation end ≥ start | ✅ | ✅ | |
| Amenity exactly-one-target | ✅ | ✅ | |
| Amenity unique per target | ✅ | | ✅ (upsert) |
| Amenity value matches type / property type | | ✅ | |
| Amenity `level`/`value_type` locked once used | | | ✅ |
| Occupant type ↔ building type (student→hostel, teacher→quarters, shopkeeper→shops) | | | ✅ |
| One active allocation per student/teacher (shopkeepers may hold several) | | | ✅ |

> **`clean()` is not called by `save()` or by DRF.** Services and serializers must call `full_clean()` explicitly, otherwise these rules never run. DB constraints are the final safety net.

---

## 6. Bed lifecycle (decision: auto-generate, manual edits allowed)

- **Create unit** with `capacity > 1` → services create beds "1".."N" in the same transaction. `capacity == 1` → no beds.
- **Rename bed:** allowed, unique within unit.
- **Add bed:** allowed; `capacity += 1`; next number assigned.
- **Remove bed:** soft-delete (`is_active=False`) only if no ACTIVE allocation; `capacity -= 1`.
- **Maintenance:** bed becomes non-allocatable; capacity unchanged.
- **Change capacity:** up → auto-add beds; down → blocked unless enough vacant beds exist to deactivate.
- **Invariant:** `unit.capacity == count(active beds)` for hostel units.
- A unit with ACTIVE allocations cannot switch between capacity 1 and capacity > 1.

---

## 7. Status sync

`Unit.status` / `Bed.status` are stored for fast filtering. They are updated **only** by service functions (`allocate_unit`, `vacate_allocation`, bed ops) inside the same transaction — not signals.
- Bed: ACTIVE allocation → OCCUPIED, else VACANT (MAINTENANCE untouched).
- Unit: no active beds occupied → VACANT; some → PARTIAL; all → OCCUPIED (single-capacity: VACANT/OCCUPIED). MAINTENANCE is set manually.

---

## 8. Soft delete

Every model has `is_active`. The API never hard-deletes Buildings/Blocks/Units/Occupants/Amenities — it toggles `is_active`. Hard delete stays available in Django admin/shell for cleanup.

---

## 9. Frontend flow (estate_admin)

1. Login → **Create Building**.
2. **Step 1:** name, type, location, BUILDING-level amenities.
3. **Step 2 (optional):** blocks + BLOCK-level amenities. Skip to attach units directly to the building.
4. **Step 3:** units under each block (or directly under the building): number, capacity, floor, UNIT-level amenities. Beds auto-generate and are editable.
5. **Review → Save.** One nested payload, one atomic transaction (`create_building_with_structure`).
6. Bulk helper: "add rooms 101–120, capacity 4".

Amenity definitions must exist in the catalog before they appear as fillable fields.

---

## 10. Migration plan

- `0001_initial` — already applied.
- `0002` — generated from this revision: drops `AmenityValue.unique_together`, adds the partial unique constraints, the check constraints (unit capacity, allocation dates, amenity single target). Generate with:
  `uv run python manage.py makemigrations estate -n constraints_and_validation`
- If dev data already contains duplicate amenity values or bad dates, clean them before `migrate`.
- Uses `CheckConstraint(condition=...)` (Django ≥ 5.1; compatible with 5.2 and 6.x). Pin `django>=5.2,<6` to match the ERP.

---

## 11. Next phase

1. `admin.py` + Groups (`estate_admin`, `hall_assistant`) + DRF settings (default permissions, pagination, auth).
2. `services.py`: `create_building_with_structure`, bed ops, `allocate_unit`, `vacate_allocation`, status sync.
3. `permissions.py`, serializers, views, urls (incl. stats and "room of student" endpoints).
4. Tests: allocation constraints, amenity rules, bed lifecycle.