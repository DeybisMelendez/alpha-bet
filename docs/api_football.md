# Documentación: API-Football (api-sports.io v3)

API-Football es la fuente complementaria a football-data.org. Se utiliza para:

* **Selecciones nacionales** de todas las confederaciones (CONCACAF, UEFA, CONMEBOL, AFC, CAF, OFC).
* **Copas de clubes CONCACAF** (Champions Cup, CONCACAF League, Central American Cup).
* **Ligas domésticas de Centroamérica y Norteamérica**.

football-data.org sigue siendo la fuente para competiciones de clubes europeos y sudamericanos. La división es excluyente: ninguna competición se obtiene de ambas APIs a la vez, lo que evita duplicación de partidos y doble conteo de Elo.

---

## 1. Configuración

La API key se lee desde el archivo `.secret` con `dotenv` (variable `API_FOOTBALL_KEY`).

```python
import requests

API_TOKEN = "TU_API_TOKEN"
BASE_URL = "https://v3.football.api-sports.io"

HEADERS = {
    "x-apisports-key": API_TOKEN
}
```

---

## 2. Restricciones del plan Free (verificadas empíricamente)

| Recurso | Acceso en Free |
| --------- | --------- |
| `league=X&season=Y` (histórico) | Solo temporadas **2022, 2023 y 2024**. La temporada actual (2025/2026) está bloqueada para todas las ligas. |
| `date=YYYY-MM-DD` (fixture por fecha) | Solo **hoy ± 1 día** (ventana rolling de 3 días). Es la única forma de acceder a la temporada actual. |
| `last=N` | Prohibido en Free. |
| Paises multi-palabra | Se filtran con guion: `Costa-Rica`, `El-Salvador`, `Dominican-Republic`. |
| Rate limit | 100 req/día + ~10 req/min. |

---

## 3. Endpoints principales

### Competiciones (`/leagues`)

```python
response = requests.get(
    f"{BASE_URL}/leagues",
    headers=HEADERS,
    params={"search": "concacaf"}
)

for r in response.json()["response"]:
    print(r["league"]["id"], r["league"]["name"], r["country"]["name"])
```

Filtrar por país (sin espacios, usar guion):

```python
response = requests.get(
    f"{BASE_URL}/leagues",
    headers=HEADERS,
    params={"country": "Costa-Rica"}
)
```

### Equipos (`/teams`)

```python
response = requests.get(
    f"{BASE_URL}/teams",
    headers=HEADERS,
    params={"league": 262, "season": 2024}  # Liga MX 2024
)

for r in response.json()["response"]:
    t = r["team"]
    print(t["id"], t["name"], t.get("code"), t.get("founded"))
```

### Partidos (`/fixtures`)

Por fecha (todas las ligas, ventana hoy ± 1 día en Free):

```python
from datetime import date, timedelta

today = date.today().isoformat()

response = requests.get(
    f"{BASE_URL}/fixtures",
    headers=HEADERS,
    params={"date": today}
)

for f in response.json()["response"]:
    fx = f["fixture"]
    t = f["teams"]
    g = f["goals"]
    print(fx["id"], fx["date"], t["home"]["name"], g["home"], "-", g["away"], t["away"]["name"])
```

Por liga y temporada (solo 2022-2024 en Free):

```python
response = requests.get(
    f"{BASE_URL}/fixtures",
    headers=HEADERS,
    params={"league": 396, "season": 2024}  # Nicaragua Primera Division 2024
)
```

### Paises (`/countries`)

```python
response = requests.get(
    f"{BASE_URL}/countries",
    headers=HEADERS,
)
```

---

## 4. Mapeo de datos al modelo de Alpha Bet

### Status de partido

| API-Football | Match.Status |
| --------- | --------- |
| `NS`, `TBD` | `SCHEDULED` / `TIMED` |
| `1H`, `HT`, `2H`, `ET`, `LIVE`, `BT` | `IN_PLAY` / `PAUSED` |
| `FT`, `AET` | `FINISHED` |
| `PEN` | `FINISHED` (goles = fulltime; Elo trata como empate) |
| `PST` | `POSTPONED` |
| `CANC`, `ABD` | `CANCELLED` |
| `AWD` | `AWARDED` |
| `SUSP`, `INT` | `SUSPENDED` |

### Goles y penales

Se usan los goles de `score.fulltime` (90 minutos + extra time). Si el partido se decidió por penales (`PEN`), el resultado para Elo es **empate** (S=0.5) independientemente del marcador de penales. Esto sigue la práctica estándar: los penales no reflejan fuerza relativa, solo desempate.

### Estructura de respuesta

```json
{
  "fixture": {
    "id": 1207949,
    "date": "2024-07-30T22:00:00+00:00",
    "status": {"short": "FT"}
  },
  "league": {
    "id": 1028,
    "name": "CONCACAF Central American Cup",
    "season": 2024,
    "round": "Group Stage - 1"
  },
  "teams": {
    "home": {"id": 1234, "name": "Port Layola", "logo": "..."},
    "away": {"id": 5678, "name": "Antigua GFC", "logo": "..."}
  },
  "goals": {"home": 1, "away": 4},
  "score": {
    "halftime": {"home": 0, "away": 2},
    "fulltime": {"home": 1, "away": 4}
  }
}
```

---

## 5. Competiciones trackeadas

Definidas en `settings.API_FOOTBALL_LEAGUES` como tuplas `(league_id, code, nombre, elo_inicial)`.

El `code` se almacena como el `league_id` en formato string (ej. `"396"`), lo que evita colisiones con los códigos alfanuméricos de football-data (PL, PD, ...).

---

## 6. Estrategia de sincronización

### Daily sync (3 req/día)

Se consultan `date=hoy-1`, `date=hoy` y `date=hoy+1` (3 peticiones). Cada respuesta trae partidos de todas las ligas; se filtra client-side a las ligas trackeadas en `API_FOOTBALL_LEAGUES`.

### Backfill histórico (~75 req, 1 día)

`load_af_history` recorre las ligas trackeadas × temporadas 2022-2024 con `league+season`. Idempotente: omite ligas/temporadas que ya tienen partidos cargados.

### Rate limit

* `API_FOOTBALL_RATE_LIMIT_SECONDS`: pausa entre peticiones (default 6s).
* `API_FOOTBALL_DAILY_BUDGET`: tope diario (default 80, sobre 100).
* Backoff 429: espera 60s y reintenta una vez.

---

## 7. División de fuentes

| Fuente | Competiciones |
| --------- | --------- |
| football-data.org | Clubes: PL, PD, BL1, SA, FL1, CL, BSA, ELC, DED, PPL, CLI |
| API-Football | Selecciones (todas), copas CONCACAF, ligas CA/NA |

El campo `source` en `Competition`, `Team` y `Match` distingue el origen (`footballdata` / `apifootball`). La unicidad es por `(id_api, source)` porque los IDs de ambas APIs son independientes y pueden colisionar.
