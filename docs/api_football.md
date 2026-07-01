# Integración con API-Football

## Objetivo

API-Football (api-sports.io v3) es la **única fuente de datos** de Alpha Bet:
clubes, selecciones nacionales y amistosos. Este documento describe los endpoints
utilizados, los límites por plan y el procedimiento de carga (descubrimiento,
sync diaria y backfill histórico).

Para la capa de persistencia y transformación de los datos en bruto, ver
`docs/api.md`.

---

# Cliente

Implementado en `api_client/client.py` (`ApiFootballClient`).

- Base URL: `https://v3.football.api-sports.io` (`settings.API_FOOTBALL_BASE_URL`).
- Autenticación: header `x-apisports-key` desde `settings.API_FOOTBALL_KEY`
  (variable de entorno, cargada desde `.secret`).
- Caché: `ApiResponseCache` (TTL configurable vía
  `settings.API_CACHE_TTL_MINUTES`, default 60 min). Las respuestas se cachean
  por URL completa para evitar quemar requests durante reintentos y backfill
  interrumpido.
- Rate limit: si la API responde `429` (límite por minuto), el cliente espera
  60s y reintenta una vez. El header `x-ratelimit-requests-remaining` se
  expone en `last_rate_remaining` para que el backfill pueda cortar antes de
  tocar el techo diario.
- `settings.API_FOOTBALL_RATE_LIMIT_SECONDS` (default 0.25): pausa entre
  requests en flujos batch.
- `settings.API_FOOTBALL_DAILY_BUDGET` (default 7000): techo diario de
  requests; el backfill lo respeta.

---

# Endpoints utilizados

| Endpoint | Método del cliente | Uso |
| --- | --- | --- |
| `/countries` | `get_countries()` | Catálogo de países. |
| `/leagues/seasons` | `get_all_seasons()` | Años con cobertura (detecta plan Pro: incluye 2025+). |
| `/leagues` | `get_leagues()`, `get_league(id)` | Descubrimiento de competiciones (`sync_competitions`). |
| `/teams` | `get_teams(league, season)` | Equipos de una liga×temporada (`sync_teams`). |
| `/fixtures?date=YYYY-MM-DD` | `get_fixtures_by_date(date_str)` | Sync diaria por fecha (`sync_matches`). |
| `/fixtures?league=&season=` | `get_fixtures(league, season, ...)` | Backfill histórico por liga×temporada (`load_history`). |
| `/fixtures/statistics?fixture=ID` | `get_fixture_statistics(fixture_id)` | Stats de partido finalizado (remates, posesión, etc.). |

No se usan endpoints de cuotas/odds (la plataforma trabaja con planes Free/Pro,
que no los incluyen; las cuotas se ingresan manualmente en el detalle del
pronóstico vía `ValueBetForm`).

---

# Planes

API-Football limita por plan. Los valores relevantes para Alpha Bet:

- **Free**: `date=hoy ± 1 día` en `/fixtures`; `/fixtures/statistics` puede no
  estar disponible en competiciones select; seasons limitadas (2022-2024).
- **Pro ($19/mo)**: sin restricción de fechas; `/fixtures/statistics` en todas
  las competiciones; seasons históricas y temporada actual.

`LeagueStrength.average_elo` se inicializa con `ELO_DEFAULT` (1500) para cada
competición × temporada. `recompute_league_strength` recalibra con los promedios
reales tras el backfill. `Competition.kind` y `home_advantage` usan los defaults
del modelo (LEAGUE, 80). La cobertura real se descubre dinámicamente con
`sync_competitions` (filtra femenil/juvenil/futsal/beach/esports).

---

# Procedimiento de carga

## 1. Descubrimiento de competiciones

```bash
python manage.py sync_competitions [--all]
```

- Sin `--all`: descubre solo ligas con `current=true` (temporada activa).
- Con `--all`: descubre todo el catálogo (requiere plan Pro).
- Filtra automáticamente femenil, juvenil, futsal, beach y esports.

## 2. Sincronización de equipos

```bash
python manage.py sync_teams --league ID --season YYYY
```

Requiere plan Pro para temporadas fuera de 2022-2024.

## 3. Sync diaria de partidos

```bash
python manage.py sync_matches [--days-back N --days-ahead N]
```

- Por defecto ventana `hoy ± 1 día`.
- Filtra a las competiciones registradas (`Competition` con `id_api`).
- Procesa Elo de finalizados y genera pronósticos de programados.
- Flags opcionales: `--no-elo`, `--no-forecasts`, `--no-stats`.

## 4. Backfill histórico progresivo

El backfill es **idempotente y reanudable** vía la cola `BackfillJob`
(`api_client.models.BackfillJob`).

### 4.1 Crear la cola (no consume requests)

```bash
python manage.py load_history --seed --from 2020
```

Crea trabajos `BackfillJob(PENDING)` para cada `liga × temporada` del rango.
`--from` define el año inicial (default 2020). Opcional `--to` (default año
actual). No consume requests; solo encola.

### 4.2 Procesar la cola

```bash
python manage.py load_history [--max-requests N] [--leagues A,B] [--seasons 2020:2026]
```

- Respeta el presupuesto diario (`settings.API_FOOTBALL_DAILY_BUDGET`).
- Lee el siguiente `PENDING`, lo procesa y lo marca `DONE` (o `EMPTY`).
- Reanudable: tras interrupciones continúa desde el siguiente `PENDING`.
- Flags adicionales: `--rate-limit-seconds`, `--reset` (reinicia la cola),
  `--no-elo`, `--no-forecasts`, `--no-recompute`, `--fetch-stats` (descarga
  `/fixtures/statistics` para cada partido finalizado).

## 5. Orquestador diario

```bash
python manage.py daily_update
```

Ejecuta en orden: `sync_matches` (ventana semanal, ver abajo) → procesar Elo
de finalizados → generar pronósticos de programados → poda de pronósticos/
partidos stale fuera de ventana → purge de la caché API vencida. Pensado para
cron diario.

La ventana del orquestador difiere del default de `sync_matches`: usa
`settings.SYNC_BACK_DAYS` (3) hacia atrás y
`settings.FORECAST_SCHEDULE_DAYS` (7) hacia adelante, ampliable con
`--days-back` / `--days-ahead`. Flags opcionales: `--no-prune`, `--no-elo`,
`--no-forecasts`, `--no-cache-purge`.

Cron recomendado (8:00 AM):

```bash
0 8 * * * cd /home/deybis/Repos/alpha-bet && .venv/bin/python manage.py daily_update >> /tmp/alpha-bet-daily.log 2>&1
```

---

# Purga de caché

`daily_update` purga `ApiResponseCache` vencida (entradas cuya antigüedad
supera `settings.API_CACHE_TTL_MINUTES`). Esto evita que la caché crezca
indefinidamente y que respuestas stale (partidos cuyo resultado cambió tras
un update) se sirvan en re-sincronizaciones.
