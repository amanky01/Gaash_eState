# Gaash eState

A Django-based real estate management application.

## Backend Setup

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) - Fast Python package installer

### Installation

1. Navigate to the backend directory:
```bash
cd backend
```

2. Install dependencies using uv:
```bash
uv sync
```

### Running the Backend

Start the Django development server using uv:
```bash
uv run python manage.py runserver
```

The backend will be available at `http://localhost:8000`

### Other Useful Commands


**Run database migrations:**
```bash
uv run python manage.py migrate
```

**Make migrations:**
```bash
uv run python manage.py makemigrations
```

**Access the Django admin panel:**
Navigate to `http://localhost:8000/admin` and log in with your superuser credentials.

## Project Structure

```
backend/
├── manage.py          # Django management script
├── db.sqlite3         # SQLite database (development)
├── pyproject.toml     # Project configuration
└── config/            # Main Django project settings
    ├── settings.py    # Django settings
    ├── urls.py        # URL routing
    ├── asgi.py        # ASGI configuration (for async servers)
    └── wsgi.py        # WSGI configuration (for production)
```

## Technologies

- **Django** 5.2.17+ - Web framework
- **Django REST Framework** 3.18.0+ - API framework

