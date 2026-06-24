# Alpha Bet

Personal football prediction platform using Django 6.0 + Elo system + two football APIs:
football-data.org (clubs) and api-football.com (national teams + CONCACAF + CA/NA leagues).

## Dev Commands

```bash
# Activate venv
source .venv/bin/activate

# Run dev server
python manage.py runserver

# Django management
python manage.py <command>
```

## Daily Update

Orquesta refresco de competiciones, sincronización de partidos de la ventana
semanal (procesa Elo de finalizados y genera pronósticos de programados) y
poda de pronósticos/partidos stale fuera de ventana. Pensado para ejecutarse
una vez al día.

```bash
python manage.py daily_update
```

Para ejecución recurrente vía cron (ej. 8:00 AM):

```bash
0 8 * * * cd /home/deybis/Repos/alpha-bet && .venv/bin/python manage.py daily_update >> /tmp/alpha-bet-daily.log 2>&1
```

## Environment

- Env vars loaded from `.secret` via `dotenv` (not committed - see `.gitignore`)
- `DJANGO_SECRET_KEY`, `FOOTBALL_DATA_API_KEY` and `API_FOOTBALL_KEY` required
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
- `docs/api_football.md` - api-football.com API integration (national teams, CONCACAF, CA/NA leagues)

## Architecture

- Single Django project (`core/`) with default config
- `core/settings.py` loads env from `.secret`
- Language: Spanish (LANGUAGE_CODE=`es-ni`, TIME_ZONE=`America/Managua`)
- Two data sources split by competition type (excluyente):
  - `footballdata`: club competitions (PL, PD, BL1, SA, FL1, CL, BSA, ELC, DED, PPL, CLI)
  - `apifootball`: national teams (all confederations), CONCACAF club cups, CA/NA leagues
- `source` field on `Competition`/`Team`/`Match` distinguishes origin; uniqueness is `(id_api, source)`
