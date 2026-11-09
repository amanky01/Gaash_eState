### ==========================================
### GAASH_ESTATE API INTEGRATION TEST SUITE
### ==========================================

### 1. Create a Building
POST http://127.0.0.1:8000/api/estate/buildings/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "name": "Chenab Hostel",
    "property_type": "HOSTEL_BOYS"
}

### 2. Create a Block
POST http://127.0.0.1:8000/api/estate/blocks/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "name": "Block A",
    "building": 1
}

### 3. Create a Unit (Room)
POST http://127.0.0.1:8000/api/estate/units/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "number": "101",
    "building": 1,
    "block": 1,
    "capacity": 2
}

### 4. Create a Bed
POST http://127.0.0.1:8000/api/estate/beds/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "bed_number": "B1",
    "unit": 1
}

### 5. Create an Occupant
POST http://127.0.0.1:8000/api/estate/occupants/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "full_name": "Akashat Tiwari",
    "occupant_type": "STUDENT",
    "bed": 1,
    "gender": "MALE"
}

### 6. Create an Amenity Definition
POST http://127.0.0.1:8000/api/estate/amenity-definitions/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "name": "High-Speed Wi-Fi",
    "level": "BLOCK",
    "value_type": "BOOLEAN"
}

### 7. Assign Amenity Value to Block A
POST http://127.0.0.1:8000/api/estate/amenity-values/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "definition": 1,
    "block": 1,
    "value_boolean": true
}

### 8. Create an Allocation (Lease)
POST http://127.0.0.1:8000/api/estate/allocations/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "occupant": 1,
    "unit": 1,
    "bed": 1,
    "start_date": "2026-11-09"
}

### 9. Vacate Allocation
POST http://127.0.0.1:8000/api/estate/allocations/1/vacate/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

### 10. Fetch Estate Stats
GET http://127.0.0.1:8000/api/estate/stats/
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

### 11. Fetch Occupant Room Info
GET http://127.0.0.1:8000/api/estate/occupants/1/room/
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

### 12. Toggle Unit Maintenance Mode
POST http://127.0.0.1:8000/api/estate/units/1/maintenance/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "is_under_maintenance": true
}

### 13. Bulk Create Units
POST http://127.0.0.1:8000/api/estate/units/bulk/
Content-Type: application/json
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID

{
    "building": 1,
    "block": 1,
    "start": 201,
    "end": 203
}

### 14. Test Cascade Deletion (Delete Bed)
DELETE http://127.0.0.1:8000/api/estate/beds/1/
X-CSRFToken: YOUR_CSRF_TOKEN
Cookie: csrftoken=YOUR_CSRF_TOKEN; sessionid=YOUR_SESSION_ID
