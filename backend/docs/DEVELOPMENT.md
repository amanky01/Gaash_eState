# Development Guide

## 1. Setup

```bash
cd backend
uv sync
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver        # http://localhost:8000
```

Environment (all optional in dev): `DJANGO_DEBUG` (default `true`), `DJANGO_SECRET_KEY` (required when
debug is off), `DJANGO_ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` (defaults to localhost:3000 and :5173 in debug).

Try the API: log in at `/api-auth/login/`, then open `/api/estate/`.

## 2. Tests

```bash
uv run python manage.py test estate          # all
uv run python manage.py test estate.tests.AllocationTests   # one class
```
50 tests in `estate/tests.py`:

| Class | Covers |
|---|---|
| `UnitAndBedTests` | bed auto-generation, add/remove/rename, capacity up/down, 1↔multi switch, bulk create |
| `AllocationTests` | status flow, double booking, bed required/forbidden, type & gender rules, one-active rule, shopkeepers, maintenance, vacate/cancel, `sync_status`, soft-delete blocking |
| `AmenityTests` | upsert, level/type mismatch, property-type restriction, coercion, lock rule |
| `ApiTests` | wizard create + atomic rollback, labels, read-only fields, 400-not-500, filters, soft delete/activate, stats |
| `PermissionTests` | anonymous/outsider/superuser, assistant read-only vs operational actions |

Add a test with every new rule; constraint-heavy models regress silently otherwise.

## 3. Working conventions

- Business logic goes in `services.py` (atomic, `full_clean()`, raise `ValidationError`). Views stay thin.
- New model field → update `serializers.py`, `admin.py`, `DATA_MODEL.md`; run `makemigrations`.
- New rule → add to `BUSINESS_RULES.md` and note where it is enforced.
- New permission → `assistant_actions` on the view + `USERS.md` matrix.
- Non-trivial choice → add a line to `DECISIONS.md`.
- After manual edits in Django admin, run `services.sync_status()` (shell) to repair derived statuses.

## 4. Migrations

`0001_initial` → `0002_constraints_and_validation` → `0003_create_groups`.
Before applying 0002 to a database with real data, check for duplicate amenity values per target and
allocations where `end_date < start_date`.

## 5. Roadmap

**Done**
- [x] Models, constraints, migrations (rev 2)
- [x] Services: allocate, vacate, cancel, beds, capacity, maintenance, bulk, nested building, status sync, soft delete
- [x] Permissions (2 roles), serializers, views, URLs, stats, "room of student"
- [x] Test suite (50)

**Next**
- [ ] Run against real dev data; fix anything the suite didn't foresee
- [ ] Frontend: building wizard (steps 1–3 + review), occupancy grid, allocation screen, stats dashboard
- [ ] Decide the no-role tier (DECISIONS C) and auth method with the ERP
- [ ] Management command to bootstrap users/groups
- [ ] OpenAPI schema (e.g. `drf-spectacular`) for the frontend
- [ ] Student lookup/import from the ERP via `external_ref_id`

**Later / not scoped**
- Bed transfer, billing/rent, audit history for amenity values, notifications, Postgres in production, CI.

## 6. Known gaps

- Django admin bypasses services (no auto-beds, no status sync).
- Allocation `end_date` for an ACTIVE row can be set at creation (planned move-out) but nothing auto-vacates
  when it passes.
- No concurrency stress testing (row locks are used; SQLite ignores `select_for_update`, so test on Postgres before production).
- Hard-delete of `AmenityValue` is allowed for admins (current-state data, no history by design).
