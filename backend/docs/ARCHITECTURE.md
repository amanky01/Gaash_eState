# Architecture

## 1. What this is

A self-contained Django app, `estate`, exposing a REST API (Django REST Framework). It is a separate app
because the host ERP is modular: integration is "copy the folder, register the app, mount the URLs".

| Piece | Choice |
|---|---|
| Framework | Django 5.2 (`>=5.2,<6`, pinned to match the ERP), DRF 3.18 |
| Python | 3.11+ (managed with `uv`) |
| DB | SQLite in development (everything used is portable to Postgres) |
| Auth | Session auth (cookie + CSRF) |
| Cross-origin | `django-cors-headers`; frontend on a different origin, credentials allowed |
| Roles | Django groups `estate_admin`, `hall_assistant` |

## 2. Layout

```
backend/
├── manage.py
├── config/                 # project settings, root urls (api/estate/, admin/, api-auth/)
└── estate/
    ├── constants.py        # enums (TextChoices) + HOSTEL_PROPERTY_TYPES
    ├── models.py           # 8 models + DB constraints + clean() validation
    ├── services.py         # ALL write logic; the single owner of every invariant
    ├── permissions.py      # IsEstateAdmin / IsHallAssistant / IsEstateStaff
    ├── serializers.py      # validation + response shaping only
    ├── views.py            # thin HTTP layer, delegates to services
    ├── urls.py             # DRF router + stats
    ├── admin.py            # inspection / data repair (bypasses services!)
    ├── migrations/         # 0001 initial, 0002 constraints+gender, 0003 groups
    └── tests.py            # 50 tests
```

## 3. Layers and the one rule

```
HTTP ──► views.py ──► serializers.py (validate)
              │
              └────► services.py ──► models.py ──► DB constraints
                      (atomic, full_clean, status sync)
```

**Rule: views and serializers never write structural state directly.** Creating units, beds,
allocations, amenity values, changing capacity, vacating, soft-deleting: all go through `services.py`.
One code path owns every invariant, so the API, tests and future ERP hooks behave identically.

## 4. Defence in depth (where a rule can be enforced)

1. **Database** — `CHECK` and (partial) `UNIQUE` constraints: the final safety net (races, bad scripts).
2. **Model `clean()`** — structural rules (block belongs to building, capacity vs property type, amenity
   target/level/type). **Not called by `save()` or by DRF**, so services call `full_clean()` explicitly.
3. **Services** — business rules that need queries or context (occupant ↔ building type, gender,
   one active allocation, double booking with a friendly message, bed lifecycle).
4. **Serializers** — shape and cross-field input checks, lock rules, read-only server fields.

Full matrix: [BUSINESS_RULES.md](BUSINESS_RULES.md).

## 5. Request lifecycle (example: allocate a student to a bed)

1. `POST /api/estate/allocations/` → `IsEstateAdmin | IsHallAssistant` checks role and that `create`
   is in the view's `assistant_actions`.
2. `AllocationSerializer` resolves `occupant`/`unit`/`bed` ids; `allocated_by` and `status` are read-only.
3. `AllocationViewSet.create` calls `services.allocate_unit(allocated_by=request.user, ...)`.
4. Inside `transaction.atomic()`: lock unit/occupant/bed → check rules → `full_clean()` → save →
   recompute bed status → recompute unit status.
5. Any `ValidationError` becomes HTTP 400 via `EstateViewMixin.handle_exception`; an `IntegrityError`
   (lost race against the DB constraint) also becomes 400.

## 6. Status synchronisation

`Unit.status` and `Bed.status` are stored for fast filtering and are changed **only** by services, inside
the same transaction as the allocation change. No Django signals (hard to trace, easy to bypass with
`update()`). `services.sync_status()` recomputes everything if data ever drifts (e.g. after admin edits).

## 7. Cross-cutting conventions

- **Soft delete:** every entity has `is_active`; API `DELETE` deactivates, never removes rows.
- **History is free:** allocations are never deleted; vacating flips status and sets `end_date`.
- **Server-owned fields:** `created_by`, `allocated_by`, `status`, `is_active` are never client-writable.
- **Errors:** `{"field": ["msg"]}` or a list of messages, HTTP 400. Auth failures 403.
- **Lists:** paginated (20/page), `?is_active=true|false|all`, `?search=`, per-endpoint filters.
- **Soft-deleted beds keep their numbers** so unique `(unit, bed_number)` stays intact; re-adding a bed
  reactivates the lowest removed one first.

## 8. ERP integration

1. Copy `estate/` into the ERP project.
2. Add `'estate'` to `INSTALLED_APPS` (plus `rest_framework`, `corsheaders` if not present).
3. `path('api/estate/', include('estate.urls'))`.
4. `migrate` (creates tables and the two groups).
5. Students: ERP records are soft-linked through `Occupant.external_ref_id` (generic string, unused
   so far). Teachers and shopkeepers are entered manually in this module.

## 9. Known limits (by design, for now)

- Django admin writes bypass services (no bed auto-generation, no status sync). Use it for
  inspection and repair, then run `sync_status()`.
- Amenity values are current-state only (no history). Allocation history is retained.
- No rent/billing, no transfers between beds (vacate + allocate), no audit log.
