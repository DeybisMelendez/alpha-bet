# Documentación rápida: Football-Data.org con Python

La API de Football-Data.org permite consultar competiciones, equipos, partidos, clasificaciones y resultados mediante solicitudes HTTP autenticadas con un token API. Todas las peticiones deben incluir el encabezado `X-Auth-Token`. ([Postman][1])

## 1. Instalación

```bash
pip install requests
```

## 2. Configuración básica

```python
import requests

API_TOKEN = "TU_API_TOKEN"
BASE_URL = "https://api.football-data.org/v4"

HEADERS = {
    "X-Auth-Token": API_TOKEN
}
```

---

# Obtener partidos del día

El endpoint `/matches` devuelve los partidos disponibles. Puedes filtrar por fecha para obtener únicamente los encuentros de hoy. La API dispone de un recurso específico para partidos (`Match Resource`). ([Football Data][2])

```python
import requests
from datetime import date

today = date.today().isoformat()

response = requests.get(
    f"{BASE_URL}/matches",
    headers=HEADERS,
    params={
        "dateFrom": today,
        "dateTo": today
    }
)

data = response.json()

for match in data["matches"]:
    print(
        f"{match['homeTeam']['name']} vs "
        f"{match['awayTeam']['name']} - "
        f"{match['utcDate']}"
    )
```

---

# Obtener información de una competición

Primero puedes listar todas las competiciones disponibles.

```python
response = requests.get(
    f"{BASE_URL}/competitions",
    headers=HEADERS
)

competitions = response.json()["competitions"]

for comp in competitions[:10]:
    print(comp["code"], "-", comp["name"])
```

La API proporciona un recurso específico para consultar competiciones mediante su código o ID. ([Football Data][3])

Consultar una competición concreta:

```python
competition_code = "PL"  # Premier League

response = requests.get(
    f"{BASE_URL}/competitions/{competition_code}",
    headers=HEADERS
)

competition = response.json()

print(competition["name"])
print(competition["area"]["name"])
```

---

# Obtener equipos de una competición

Puedes obtener todos los equipos participantes de una competición.

```python
competition_code = "PL"

response = requests.get(
    f"{BASE_URL}/competitions/{competition_code}/teams",
    headers=HEADERS
)

teams = response.json()["teams"]

for team in teams:
    print(team["id"], team["name"])
```

La API dispone del endpoint `/competitions/{id}/teams` para recuperar los equipos de una competición determinada. ([Football Data][4])

---

# Obtener información de un equipo

Una vez conocido el ID del equipo:

```python
team_id = 64  # Liverpool (ejemplo)

response = requests.get(
    f"{BASE_URL}/teams/{team_id}",
    headers=HEADERS
)

team = response.json()

print("Nombre:", team["name"])
print("Fundado:", team["founded"])
print("Estadio:", team["venue"])
print("Sitio web:", team["website"])
```

---

# Obtener los últimos partidos de un equipo

```python
team_id = 64

response = requests.get(
    f"{BASE_URL}/teams/{team_id}/matches",
    headers=HEADERS,
    params={
        "limit": 5
    }
)

matches = response.json()["matches"]

for match in matches:
    print(
        match["homeTeam"]["name"],
        "-",
        match["awayTeam"]["name"]
    )
```

El endpoint `/teams/{id}/matches` permite consultar los partidos de un equipo y aplicar filtros por fecha, competición, estado y temporada. ([Football Data][4])

---

# Competiciones populares

Algunos códigos útiles:

| Competición      | Código |
| ---------------- | ------ |
| Premier League   | PL     |
| La Liga          | PD     |
| Bundesliga       | BL1    |
| Serie A          | SA     |
| Ligue 1          | FL1    |
| Champions League | CL     |
| World Cup        | WC     |

Estos códigos pueden utilizarse directamente en los endpoints de competiciones. ([Football Data][3])

---

# Ejemplo completo

```python
import requests
from datetime import date

API_TOKEN = "TU_API_TOKEN"

headers = {
    "X-Auth-Token": API_TOKEN
}

today = date.today().isoformat()

response = requests.get(
    "https://api.football-data.org/v4/matches",
    headers=headers,
    params={
        "dateFrom": today,
        "dateTo": today
    }
)

for match in response.json()["matches"]:
    print(
        f"{match['competition']['name']} | "
        f"{match['homeTeam']['name']} vs "
        f"{match['awayTeam']['name']}"
    )
```

Con estos cuatro endpoints (`/matches`, `/competitions`, `/competitions/{code}/teams` y `/teams/{id}`) puedes construir una base sólida para una plataforma de pronósticos, rankings Elo o análisis estadístico de fútbol. ([Football Data][4])

[1]: https://www.postman.com/api-noob/football-data-org-apis/documentation/yjgfm4j/football-data-org-v4?utm_source=chatgpt.com "Football-data.org v4 | Documentation | Postman API Network"
[2]: https://www.football-data.org/documentation/api?utm_source=chatgpt.com "API Reference"
[3]: https://docs.football-data.org/general/v4/competition.html?utm_source=chatgpt.com "Competition - football-data API documentation"
[4]: https://www.football-data.org/documentation/quickstart?utm_source=chatgpt.com "API Quickstart"
