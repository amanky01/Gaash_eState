# Users, Roles & Permissions

## 1. Roles

| Role | How assigned | Purpose |
|---|---|---|
| **Estate admin** | Django group `estate_admin` (or superuser) | Creates and manages the structure (buildings, blocks, units, amenity catalog), occupants, everything |
| **Hall assistant** | Django group `hall_assistant` | Day-to-day operations: allocate / vacate, manage beds and occupants, fill amenity values |
| **Logged-in, no group** | any authenticated user | **Currently denied (403) on every estate endpoint** — see open item below |
| **Anonymous** | — | Denied |

Groups are created by migration `0003_create_groups`. Superusers are treated as estate admins.
A user can be in both groups; admin wins.

## 2. Permission matrix

✅ allowed · 👁 read only · — denied (403)

| Resource | Estate admin | Hall assistant |
|---|:-:|:-:|
| Buildings | ✅ CRUD (+ wizard create, activate) | 👁 list, retrieve |
| Blocks | ✅ CRUD, activate | 👁 |
| Units | ✅ CRUD, activate, `bulk`, `maintenance` | 👁 |
| Beds | ✅ list, add, rename, remove, `maintenance` | ✅ same |
| Occupants | ✅ CRUD, activate, `room` | list, retrieve, create, update, `room` (no delete/activate) |
| Allocations | ✅ list, retrieve, create, `vacate`, `cancel` | ✅ same |
| Amenity definitions | ✅ CRUD, activate | 👁 |
| Amenity values | ✅ list, create (upsert), update, delete | list, retrieve, create, update (no delete) |
| `stats/` | ✅ | ✅ |

Nobody can update or delete an allocation (history is permanent).

Implemented per view with an `assistant_actions` set of DRF action names, checked by `IsHallAssistant`;
admins pass `IsEstateAdmin`. Views use `permission_classes = [IsEstateAdmin | IsHallAssistant]`.
To change what assistants can do, edit that set on the view.

## 3. Authentication

- Session auth (cookie). Browsable API login: `/api-auth/login/`. Django admin: `/admin/`.
- Unsafe methods need a CSRF token (`X-CSRFToken`). For Postman during development add
  `rest_framework.authentication.BasicAuthentication` while `DEBUG` is true.
- The frontend runs on a different origin: set `CORS_ALLOWED_ORIGINS`; `CORS_ALLOW_CREDENTIALS` is on.
- Planned: token/JWT if the ERP's auth requires it (see DEVELOPMENT.md).

## 4. Creating users

```bash
uv run python manage.py createsuperuser           # becomes an estate admin automatically
```
Then in `/admin/` → Users → add user → Groups: pick `estate_admin` or `hall_assistant`.
Staff status is only needed for the Django admin itself, not for the API.

## 5. Audit fields

`created_by` is set from the request user on Building, Block, Unit, Occupant, AmenityDefinition.
`allocated_by` is set on Allocation. Both are read-only in the API (client values are ignored).
Beds and amenity values carry no user stamp (they follow their parent).

## 6. Occupants are not users

Students, teachers and shopkeepers are **Occupants** (data records), not login accounts.
Students are soft-linked to the ERP via `external_ref_id`; teachers and shopkeepers are entered manually.

## 7. Open item — "no-role" tier

The original design had a third, no-role tier for aggregate reporting and lookups, decided as
"login required, not anonymous". As built, `stats/` and the `room` lookup need a role.
If any logged-in user should see aggregates, change `StatsView.permission_classes` to
`[IsAuthenticated]` (one line). Not done yet because it needs a decision on exactly which lookups that tier gets.
