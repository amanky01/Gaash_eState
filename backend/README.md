# Gaash eState — Documentation

Estate Management module: a standalone Django app (`estate`) that manages hostels, shop complexes and
teacher quarters, built to be dropped into a modular, Django-based ERP.

| Doc | What it answers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the code is organised, how a request flows, why it is built this way |
| [DATA_MODEL.md](DATA_MODEL.md) | The 8 models, fields, relations, DB constraints, migrations |
| [BUSINESS_RULES.md](BUSINESS_RULES.md) | Every rule (allocation, beds, status, amenities, soft delete) and where it is enforced |
| [USERS.md](USERS.md) | Roles, who can do what, how to create users |
| [API.md](API.md) | Endpoints, payloads, filters, error format |
| [DECISIONS.md](DECISIONS.md) | Decision log: what was decided, what was built by default and still needs sign-off |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Setup, tests, migrations, ERP integration, roadmap, known gaps |

**Status (Nov 2026):** models locked (rev 2, migrations 0001–0003 applied) · services, permissions,
serializers, views, URLs and a 50-test suite written · frontend not started.

> `backend/ESTATE_MODELS_IMPLEMENTATION.md` predates the API layer and `Occupant.gender`.
> These docs supersede it; keep it only as history or delete it.