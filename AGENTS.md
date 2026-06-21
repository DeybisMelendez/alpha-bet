# Alpha Bet

Personal football prediction platform using Django 6.0 + Elo system + football-data.org API.

## Dev Commands

```bash
# Activate venv
source .venv/bin/activate

# Run dev server
python manage.py runserver

# Django management
python manage.py <command>
```

## Environment

- Env vars loaded from `.secret` via `dotenv` (not committed - see `.gitignore`)
- `DJANGO_SECRET_KEY` and `FOOTBALL_DATA_API_KEY` required
- `DJANGO_DEBUG=True` for development

## Tech Stack

- Django 6.0.6 / Python
- SQLite default (db.sqlite3)
- Pico CSS for styling (see `docs/picocss.md`)
- No tests currently

## Key Docs

- `docs/elo.md` - Elo rating algorithm with K-factor, goal difference multiplier
- `docs/pronostico.md` - Poisson-based match prediction system
- `docs/api.md` - football-data.org API integration

## Architecture

- Single Django project (`core/`) with default config
- `core/settings.py` loads env from `.secret`
- Language: Spanish (LANGUAGE_CODE=`es-ni`, TIME_ZONE=`America/Managua`)
