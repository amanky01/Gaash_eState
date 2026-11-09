# Decision Log

Two groups: **A. Decided** (agreed during design) and **B. Built by default** during the API phase.
Group B items are working defaults, not yet explicitly signed off. Change them freely; the
"Where" column says what to touch.

## A. Decided

| # | Decision | Why / notes |
|---|---|---|
| A1 | Separate Django app `estate`, integrated into the ERP by copy + register + mount | The ERP is modular and app-based |
| A2 | Hierarchy Building → Block (optional) → Unit → Bed (hostels only); units may attach straight to a building | Covers hostels, shop complexes and quarters |
| A3 | Design models first, then code | Deliberate sequencing; open questions deferred to their phase |
| A4 | Service layer owns all writes and status sync; **no signals** | One traceable path; signals are bypassed by `update()` and hard to debug |
| A5 | Stored `Unit.status` / `Bed.status`, updated in the same transaction | Fast filtering/stats |
| A6 | Soft delete everywhere (`is_active`); hard delete only in admin/shell | History and safety |
| A7 | Allocations are never deleted; vacate flips status | History for free |
| A8 | Dynamic amenities: `AmenityDefinition` (catalog) + `AmenityValue` at Building/Block/Unit level | New attributes without code changes |
| A9 | Amenity `level` and `value_type` immutable once values exist (reject, don't migrate) | Avoids data conversion bugs |
| A10 | Amenity values are current-state only, no audit history | Deferred |
| A11 | Beds auto-generate from capacity at unit creation; manual add/rename/remove allowed afterwards | Convenience + flexibility |
| A12 | Students soft-linked to ERP through generic `external_ref_id`; teachers/shopkeepers manual; fields kept minimal | ERP code not shareable; defer coupling |
| A13 | `gender` on Occupant to enforce boys/girls hostels (added in migration 0002) | Rule needs the data |
| A14 | One active allocation per student/teacher; shopkeepers may hold several | Business reality |
| A15 | Session auth for now; frontend on a different origin → CORS + credentials | Simplest start |
| A16 | Non-role endpoints require login, not anonymous | Privacy of occupant data. **As built, they also need a role; see B10** |
| A17 | `clean()` is never auto-called; services/serializers call `full_clean()`; DB constraints are the last line | Django doesn't call it on `save()` / DRF |
| A18 | Amenity definitions must exist in the catalog before they appear as fillable fields in the wizard | Frontend flow |
| A19 | Pin `django>=5.2,<6` to match the ERP | Compatibility |

## B. Built by default (confirm or change)

| # | Choice | Where |
|---|---|---|
| B1 | **Hall assistant scope:** read structure; full beds; occupants create/update; allocate/vacate/cancel; amenity values create/update | `assistant_actions` on each view |
| B2 | Hostel unit `OCCUPIED` when all **bookable** (active, non-maintenance) beds are taken | `services.recompute_unit_status` |
| B3 | `DELETE` = soft delete (blocked by active allocations); `POST .../activate/` restores | `SoftDeleteMixin`, `services.deactivate/activate` |
| B4 | Allocations: no update/delete; `vacate` (move-out) and `cancel` (mistake) only; no transfer endpoint | `AllocationViewSet` |
| B5 | A bedded unit keeps ≥ 2 beds; to go to capacity 1, change capacity while empty | `services.remove_bed`, `_apply_capacity` |
| B6 | Amenity value `POST` is an upsert | `services.set_amenity_value` |
| B7 | `status`, `is_active`, `created_by`, `allocated_by` are read-only in the API | serializers |
| B8 | Lists default to `is_active=true`; `?is_active=all` shows everything | `EstateViewMixin.get_queryset` |
| B9 | Superuser counts as estate admin | `permissions.is_estate_admin` |
| B10 | **`stats/` and `room` require a role**, not just login | `IsEstateStaff` / `assistant_actions` |
| B11 | Removed beds keep their number; re-adding reuses the lowest removed bed first | `_activate_or_create_beds` |
| B12 | Maintenance toggles are refused while there are active allocations | `set_unit_maintenance`, `set_bed_maintenance` |
| B13 | Building `property_type` frozen once units exist; children can't move between parents | serializers |
| B14 | Errors: `ValidationError` and `IntegrityError` → HTTP 400 | `EstateViewMixin.handle_exception` |
| B15 | Bulk unit creation capped at 500 per request | `services.MAX_BULK_UNITS` |

## C. Still open

- Exact lookups/aggregates for a no-role logged-in tier (B10 / A16).
- Token/JWT vs session once the ERP frontend is known.
- How students are pulled from the ERP (field mapping behind `external_ref_id`).
- Audit history for amenity values (deferred, A10).
- Rent/billing, bed transfer, check-in/out notifications (not scoped).
