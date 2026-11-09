# API Reference

Base URL: `/api/estate/` · JSON · session auth · paginated lists (`count`, `next`, `previous`, `results`, 20/page).

## 1. Endpoints

| Resource | Routes | Extra actions |
|---|---|---|
| Buildings | `buildings/` `buildings/{id}/` | `POST buildings/` = nested wizard · `POST {id}/activate/` |
| Blocks | `blocks/` `blocks/{id}/` | `activate` |
| Units | `units/` `units/{id}/` | `POST units/bulk/` · `POST {id}/maintenance/` · `activate` |
| Beds | `beds/` `beds/{id}/` | `POST {id}/maintenance/` |
| Occupants | `occupants/` `occupants/{id}/` | `GET {id}/room/` · `activate` |
| Allocations | `allocations/` `allocations/{id}/` (no PUT/PATCH/DELETE) | `POST {id}/vacate/` · `POST {id}/cancel/` |
| Amenity definitions | `amenity-definitions/` `.../{id}/` | `activate` |
| Amenity values | `amenity-values/` `.../{id}/` | POST is an upsert |
| Stats | `GET stats/` | |

Who may call what: see [USERS.md](USERS.md).

## 2. List filters

All lists: `?is_active=true` (default) · `false` · `all` (where the model has `is_active`), `?search=`, `?page=`.

| Resource | Filters | Search fields |
|---|---|---|
| buildings | `property_type` | name, location |
| blocks | `building` | name |
| units | `building`, `block`, `status`, `property_type`, `floor` | number |
| beds | `unit`, `status`, `building` | bed_number |
| occupants | `occupant_type`, `gender` | name, contact, email, external_ref_id |
| allocations | `status`, `occupant`, `unit`, `bed`, `building` | occupant name, unit number |
| amenity-definitions | `level`, `value_type` | name |
| amenity-values | `definition`, `building`, `block`, `unit` | — |

A malformed filter value (e.g. `?building=abc`) returns 400.

## 3. Payload examples

### Create a building (wizard, one transaction)
`POST /api/estate/buildings/`
```json
{
  "name": "Gaash Boys Hostel",
  "property_type": "HOSTEL_BOYS",
  "location": "North campus",
  "amenities": [{"definition": 1, "value": true}],
  "blocks": [
    {"name": "A",
     "amenities": [],
     "units": [
       {"number": "101", "capacity": 4, "floor": "1",
        "amenities": [{"definition": 7, "value": true}]},
       {"number": "102", "capacity": 2}
     ]}
  ],
  "units": [{"number": "G1", "capacity": 1}]
}
```
`blocks` and `units` are optional (units without a block attach straight to the building). Beds are
auto-generated. Amenity `definition` ids must exist, be active, and match the level (building/block/unit).
`value` is validated against the definition's type.

### Bulk rooms
`POST /api/estate/units/bulk/`
```json
{"building": 1, "block": 2, "start": 101, "end": 120, "prefix": "", "capacity": 4, "floor": "1"}
```

### Allocate
`POST /api/estate/allocations/`
```json
{"occupant": 12, "unit": 5, "bed": 31, "start_date": "2026-11-01"}
```
`bed` is required for hostel rooms and must be omitted for shops/quarters. `start_date` is optional
(default today). `allocated_by` and `status` are set by the server.

### Vacate / cancel
`POST /api/estate/allocations/{id}/vacate/` with optional `{"end_date": "2026-12-15"}` · `.../cancel/` with no body.

### Beds
`POST beds/ {"unit": 5}` → adds the next bed (or `{"unit": 5, "bed_number": "D"}`) · `PATCH beds/{id}/ {"bed_number": "D"}` renames ·
`DELETE beds/{id}/` soft-removes · `POST beds/{id}/maintenance/ {"maintenance": true}`.

### Change unit capacity
`PATCH units/{id}/ {"capacity": 6}` adds/removes beds as needed.

### Amenity value (upsert)
`POST amenity-values/ {"definition": 3, "building": 1, "value_number": "5"}`.
Send only the field matching the definition's `value_type`.

### Where does this person live?
`GET occupants/{id}/room/` → `{"occupant": {...}, "allocations": [ ... ]}` (empty list if none; shopkeepers can have several).

## 4. Response shapes (highlights)

- **Unit:** `number_label` ("Room No" / "Shop No" / "Quarter No"), `status`, `beds[]` (`bed_number`, `status`, `occupant`), `amenities[]`.
- **Allocation:** adds `occupant_name`, `building`, `building_name`, `unit_number`, `bed_number`.
- **Bed:** `occupant` is the current occupant (`id`, `full_name`) or null.
- **Amenity value:** `value` is the typed value (bool / number / string).

## 5. Stats
`GET stats/` →
```json
{"buildings": 3, "blocks": 5,
 "units": {"total": 120, "by_status": {"VACANT": 40, "PARTIAL": 20, "OCCUPIED": 60}},
 "beds": {"total": 400, "by_status": {"VACANT": 120, "OCCUPIED": 280}},
 "occupants": {"total": 310, "by_type": {"STUDENT": 280, "TEACHER": 20, "SHOPKEEPER": 10}},
 "active_allocations": 305,
 "by_property_type": {"HOSTEL_BOYS": {"total": 60, "by_status": {"OCCUPIED": 30}}}}
```
Counts active records only.

## 6. Errors

| Code | When |
|---|---|
| 400 | validation / business rule failure, malformed filter, DB conflict |
| 403 | not logged in, no estate role, or action not allowed for the role |
| 404 | unknown id |
| 405 | method not offered (e.g. DELETE/PATCH on allocations) |

Body: `{"bed": ["Bed is already occupied."]}` for field errors, or `["message"]` for general ones.
