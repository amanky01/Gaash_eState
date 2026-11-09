# Business Rules

Where enforced: **DB** = constraint, **Model** = `clean()`, **Svc** = `services.py`, **Ser** = serializer.

## 1. Allocation

| Rule | DB | Model | Svc | Ser |
|---|:-:|:-:|:-:|:-:|
| One ACTIVE allocation per bed | ✅ | | ✅ friendly msg | |
| One ACTIVE allocation per single-capacity unit | ✅ | | ✅ friendly msg | |
| Bed required if capacity > 1, forbidden if 1 | | ✅ | ✅ | |
| Bed belongs to the unit, is active, not in maintenance | | partly | ✅ | |
| End date ≥ start date | ✅ | ✅ | ✅ (on vacate) | |
| Student → hostel, teacher → quarters, shopkeeper → shop complex | | | ✅ | |
| Boys hostel ⇒ male, girls hostel ⇒ female (student gender required) | | | ✅ | ✅ (gender required) |
| One active allocation per student/teacher (shopkeepers may hold several) | | | ✅ | |
| Occupant, unit and building must be active; unit not in maintenance | | | ✅ | |
| Occupant type/gender locked while they hold an active allocation | | | | ✅ |

`start_date` defaults to today. Allocations cannot be edited or deleted; use:
- **vacate** — normal move-out: status `VACATED`, `end_date` (default today, not before start).
- **cancel** — entered by mistake: status `CANCELLED`.

Both only work on ACTIVE allocations. Moving someone = vacate + allocate (no transfer endpoint yet).

## 2. Status sync (`Unit.status`, `Bed.status`)

Changed only by services, in the same transaction as the change.

- **Bed:** ACTIVE allocation → `OCCUPIED`, else `VACANT`. `MAINTENANCE` is never overwritten.
- **Unit (hostel):** counts bookable beds (active and not in maintenance). No taken beds → `VACANT`;
  all bookable taken → `OCCUPIED`; otherwise `PARTIAL`.
- **Unit (single):** ACTIVE allocation → `OCCUPIED`, else `VACANT`.
- **Maintenance** is set manually (`units/{id}/maintenance/`, `beds/{id}/maintenance/`); refused while
  there are active allocations; turning it off recomputes the status.

## 3. Beds and capacity

- Creating a unit with capacity N > 1 creates beds `"1".."N"` in the same transaction.
- **Add bed:** only on a multi-bed unit; `capacity += 1`; number auto-assigned (reuses the lowest removed
  bed first) or supplied; duplicate active number rejected.
- **Remove bed:** soft-delete only if no ACTIVE allocation; `capacity -= 1`; a multi-bed unit keeps ≥ 2 beds.
- **Rename bed:** allowed, unique within the unit.
- **Change capacity (PATCH unit):**
  - up → reactivate removed beds, then create new ones;
  - down → needs enough free beds (highest numbers removed first), else rejected;
  - 1 ↔ >1 → rejected while the unit has ACTIVE allocations; to 1 deactivates all beds.
- Capacity > 1 is only valid for hostel property types.
- **Bulk create:** `units/bulk/` creates `prefix+start .. prefix+end` (max 500) in one transaction; any
  existing number in the range rejects the whole request.

## 4. Amenities

- Definitions are a catalog; they must exist before they can be filled in the building wizard.
- A value targets exactly one of building/block/unit, and its level must equal the definition's level.
- If `applicable_property_types` is non-empty, the target's building type must be in it.
- Only the field matching `value_type` is stored; it must be present. Service coerces input
  (`"yes"/"true"`, numeric strings) and rejects bad types.
- **POST is an upsert** — one value per (definition, target); posting again overwrites.
- Value's definition/target are immutable (delete and re-create to move it).
- `level` / `value_type` of a definition are locked once values exist.
- Inactive definitions cannot receive new values.

## 5. Soft delete

- `DELETE` on buildings, blocks, units, occupants, amenity definitions sets `is_active=False`; beds are
  soft-removed via the bed rules above. Hard delete exists only in Django admin/shell.
- Blocked while the object (or anything beneath it) has an ACTIVE allocation.
- `POST .../activate/` restores; a block/unit can only be activated if its building (and block) is active.
- Lists hide inactive rows unless `?is_active=false|all`.
- Changing a building's `property_type` is refused once it has units; a block/unit/bed cannot move to
  another parent.

## 6. Building creation (wizard)

One nested payload → `services.create_building_with_structure` → one atomic transaction: building,
building amenities, blocks (+ block amenities), units under blocks, units directly under the building,
beds auto-generated, unit amenities. Any failure rolls back everything.
Duplicate block names or unit numbers inside the payload are rejected up front.
