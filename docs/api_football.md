# Integración con football-data.org

## Objetivo

football-data.org (API v4) es la **única fuente de datos** de Alpha Bet:
clubes y selecciones. Este documento describe los endpoints utilizados, los
límites por plan y el procedimiento de carga (descubrimiento, sync diaria y
backfill histórico).

Para la capa de persistencia y transformación de los datos en bruto, ver
`docs/api.md`.

---

# Cliente

Implementado en `api_client/client.py` (`FootballDataClient`).

- Base URL: `https://api.football-data.org` (`settings.FOOTBALL_DATA_BASE_URL`).
- Autenticación: header `X-Auth-Token` desde `settings.FOOTBALL_DATA_TOKEN`
  (variable de entorno, cargada desde `.secret`).
- Caché: `ApiResponseCache` (TTL configurable vía
  `settings.API_CACHE_TTL_MINUTES`, default 60 min). Las respuestas se cachean
  por URL completa para evitar quemar requests durante reintentos y backfill
  interrumpido.
- Rate limit: si la API responde `429`, el cliente lee el header
  `X-RequestCounter-Reset`, espera ese número de segundos y reintenta una vez.
  El header `X-Requests-Available-Minute` se expone en `last_rate_remaining`
  para que el backfill pueda cortar antes de tocar el techo por minuto.
- `settings.FOOTBALL_DATA_RATE_LIMIT_SECONDS` (default 6.0): pausa entre
  requests en flujos batch (10 req/min → ~6s).
- `settings.FOOTBALL_DATA_DAILY_BUDGET` (default 1000): techo diario de
  seguridad; el backfill lo respeta.

---

# Endpoints utilizados

| Endpoint | Método del cliente | Uso |
| --- | --- | --- |
| `/v4/competitions` | `get_competitions()` | Descubrimiento de competiciones (`sync_competitions`). |
| `/v4/competitions/{id}` | `get_competition(id)` | Detalle + `seasons[]` (años disponibles para backfill). |
| `/v4/competitions/{id}/matches?season=YYYY` | `get_competition_matches(comp_id, season, ...)` | Backfill histórico por competición×temporada (`load_history`). |
| `/v4/competitions/{id}/teams?season=YYYY` | `get_competition_teams(comp_id, season)` | Equipos de una competición×temporada (`sync_teams`). |
| `/v4/matches?dateFrom=&dateTo=` | `get_matches(date_from, date_to, ...)` | Sync diaria por ventana de fechas, una sola petición (`sync_matches`). |
| `/v4/teams/{id}` | `get_team(team_id)` | Detalle de equipo (founded, venue, clubColors, ...). |

No se usan endpoints de cuotas/odds (la plataforma trabaja con plan Free, que
no los incluye; las cuotas se ingresan manualmente en el detalle del
pronóstico vía `ValueBetForm`).

Mapeo de `status` de football-data.org a `Match.Status` en
`api_client/sync.py:STATUS_MAP`. `SCHEDULED` y `TIMED` se persisten por
separado (programado sin hora / con hora confirmada); `AWARDED` se persiste
como tal para que entre al flujo de Elo. `save_match` aplica un fallback
defensivo: si la API reporta un status no finalizado pero el partido ya
tiene marcador y su fecha pasó, se reclasifica como `AWARDED`. Ver
`docs/api.md` §Partidos para la semántica completa de los estados.

---

# Planes

football-data.org limita por plan. Los valores relevantes para Alpha Bet:

- **Free (€0)**: 10 req/min, 12 competiciones (ver coverage), marcadores
  (delayed), fixtures/schedules (delayed), league tables. **Sin** bookings
  (tarjetas), alineaciones, goleadores detallados ni estadísticas agregadas
  (remates, posesión, córners, faltas). Los partidos históricos se solicitan
  vía `/v4/competitions/{id}/matches?season=YYYY`, pero el plan Free **solo
  permite las últimas ~3-4 temporadas** de cada competición: el catálogo
  `seasons[]` de `/v4/competitions/{id}` lista décadas de historia, mas al
  pedir `/matches?season=YYYY` de una temporada fuera de la ventana permitida
  el servidor responde `403` (ver §Ventana histórica real del plan Free).
- **Free + Deep Data (€29/mo)**: añade bookings/cards, line-ups, goal scorers,
  squads.
- **Statistic Add-On (€15/mo)**: corners, fouls, possession, saves, shots on/off
  goal, etc. (requiere un plan regular previo).

`FOOTBALL_DATA_FREE_COMPETITION_CODES` (en `settings.py`) enumera los 12
códigos del plan Free: `CL, PL, ELC, BL1, FL1, SA, PD, DED, PPL, BSA, WC, EC`.
`sync_competitions` filtra `/v4/competitions` por este set.

`LeagueStrength.average_elo` se inicializa con `ELO_DEFAULT` (1500) para cada
competición × temporada. `recompute_league_strength` recalibra con los promedios
reales tras el backfill. `Competition.kind` se infiere del código (CL→CONTINENTAL,
WC→WORLD_CUP, EC→INTERNATIONAL, demás→LEAGUE) y `home_advantage` es 80 para
ligas nacionales y 0 para torneos neutral/sede internacional.

---

# Ventana histórica real del plan Free

El catálogo `seasons[]` que devuelve `/v4/competitions/{id}` **no refleja el
acceso real** del plan Free: lista todas las temporadas históricas (p. ej.
Premier League desde 1888), pero al solicitar `/matches?season=YYYY` de una
temporada fuera de la ventana permitida el servidor responde `403`.

El corte exacto se confirma empíricamente con los `BackfillJob`: un job
`DONE` indica temporada accesible (devolvió partidos); un job `EMPTY` con
`error_msg="403: temporada no accesible en plan Free"` indica restringida
(clasificación hecha por `load_history` en
`api_client/management/commands/load_history.py:346-355`).

Ventana observada (2026-07-08):

| code | Competición | Temporadas accesibles en Free |
| --- | --- | --- |
| BL1 | Bundesliga | 2023, 2024, 2025, 2026 (4) |
| BSA | Brasileirão Série A | 2023, 2024, 2025, 2026 (4) |
| CL | Champions League | 2023, 2024, 2025 (3) |
| DED | Eredivisie | 2023, 2024, 2025, 2026 (4) |
| EC | European Championship | 2024 (1) |
| ELC | Championship | 2023, 2024, 2025, 2026 (4) |
| FL1 | Ligue 1 | 2023, 2024, 2025, 2026 (4) |
| PD | La Liga | 2023, 2024, 2025, 2026 (4) |
| PL | Premier League | 2023, 2024, 2025, 2026 (4) |
| PPL | Primeira Liga | 2023, 2024, 2025, 2026 (4) |
| SA | Serie A | 2023, 2024, 2025, 2026 (4) |
| WC | FIFA World Cup | 2026 (1) |

Total: **41 temporadas** accesibles de las 471 listadas en los catálogos.
Toda temporada anterior a 2023 devuelve `403`. La ventana puede desplazarse
con el tiempo; ejecutar `load_history --seed --from 2000` rechequea y marca
los nuevos `403` de forma idempotente.

---

# Procedimiento de carga

## 1. Descubrimiento de competiciones

```bash
python manage.py sync_competitions
```

Descarga `/v4/competitions` y registra solo las del plan Free
(`FOOTBALL_DATA_FREE_COMPETITION_CODES`). Idempotente.

## 2. Sincronización de equipos

```bash
python manage.py sync_teams --competition ID --season YYYY
```

## 3. Sync diaria de partidos

```bash
python manage.py sync_matches [--days-back N --days-ahead N] [--no-elo --no-forecasts]
```

- Por defecto ventana `hoy ± 1 día`, en **una sola petición**
  (`/v4/matches?dateFrom=&dateTo=`).
- Filtra a las competiciones registradas.
- Procesa Elo de finalizados y genera pronósticos de programados.

## 4. Backfill histórico progresivo

El backfill es **idempotente y reanudable** vía la cola `BackfillJob`
(`api_client.models.BackfillJob`).

### 4.1 Crear la cola (no consume requests)

```bash
python manage.py load_history --seed --from 2020
```

Crea trabajos `BackfillJob(PENDING)` para cada `competición × temporada` del
rango. `--from` define el año inicial (default 2020). Opcional `--to` (default
año actual). No consume requests; solo encola.

### 4.2 Procesar la cola

```bash
python manage.py load_history [--max-requests N] [--competitions A,B] [--seasons 2020:2026]
```

- Respeta el presupuesto diario (`settings.FOOTBALL_DATA_DAILY_BUDGET`) y el
  rate limit por minuto (corta si `last_rate_remaining < 2`).
- Lee el siguiente `PENDING`, lo procesa y lo marca `DONE` (o `EMPTY`).
- Una petición por `competición × temporada` trae todos los partidos (con
  marcadores) de esa temporada.
- Reanudable: tras interrupciones continúa desde el siguiente `PENDING`.
- Flags adicionales: `--rate-limit-seconds`, `--reset` (reinicia la cola),
  `--no-elo`, `--no-forecasts`, `--no-recompute`.
- El backfill histórico **solo guarda marcadores** (el plan Free no expone
  bookings/estadísticas). Eso es suficiente para Elo y el pronóstico
  principal (Poisson sobre goles).

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
