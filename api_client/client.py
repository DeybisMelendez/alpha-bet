import logging
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

from api_client.models import ApiResponseCache

logger = logging.getLogger("alpha")


class FootballDataClient:
    """Cliente para football-data.org (API v4).

    Única fuente de datos. La caché ApiResponseCache (TTL configurable,
    default 60 min) evita quemar requests durante reintentos y backfill
    interrumpido. El header X-Requests-Available-Minute se expone vía
    last_rate_remaining para que el backfill pueda cortar antes de tocar
    el techo por minuto (plan Free: 10 req/min).

    Plan Free: solo 12 competiciones (settings.FOOTBALL_DATA_FREE_COMPETITION_CODES);
    sin bookings, alineaciones ni estadísticas agregadas. Las temporadas
    históricas de las 12 competiciones Free son accesibles vía
    /v4/competitions/{id}/matches?season=YYYY.
    """

    BASE_URL = "https://api.football-data.org"

    def __init__(
        self,
        token=None,
        base_url=None,
        cache_ttl_minutes=None,
        timeout=30,
    ):
        self.token = token or settings.FOOTBALL_DATA_TOKEN
        self.base_url = (base_url or settings.FOOTBALL_DATA_BASE_URL).rstrip("/")
        self.cache_ttl = cache_ttl_minutes or settings.API_CACHE_TTL_MINUTES
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": self.token})
        # Requests restantes en la ventana actual (header
        # X-Requests-Available-Minute). Lo lee el backfill para cortar a
        # tiempo.
        self.last_rate_remaining = None

    def _build_url(self, path, params=None):
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            clean = {k: v for k, v in params.items() if v is not None}
            if clean:
                url = f"{url}?{urlencode(clean)}"
        return url

    def _is_cache_fresh(self, cache):
        if cache is None:
            return False
        age = timezone.now() - cache.fetched_at
        return age.total_seconds() < self.cache_ttl * 60

    def _get(self, path, params=None, use_cache=True):
        url = self._build_url(path, params)

        if use_cache:
            cache = ApiResponseCache.objects.filter(url=url).first()
            if self._is_cache_fresh(cache):
                return cache.body

        response = self.session.get(url, timeout=self.timeout)
        if response.status_code == 429:
            # Rate limit por minuto: esperar el reset counter y reintentar
            # una vez. El header X-RequestCounter-Reset indica los segundos
            # hasta el reset de la ventana.
            reset = response.headers.get("X-RequestCounter-Reset", "60")
            try:
                wait = int(reset)
            except ValueError:
                wait = 60
            logger.warning(
                "football-data.org 429, esperando %ss para reintentar...", wait
            )
            time.sleep(max(wait, 1))
            response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()

        # Exponer remaining de la ventana por minuto (si viene en headers).
        remaining = response.headers.get("X-Requests-Available-Minute")
        if remaining is not None:
            try:
                self.last_rate_remaining = int(remaining)
            except ValueError:
                pass

        if use_cache:
            ApiResponseCache.objects.update_or_create(
                url=url, defaults={"body": body}
            )
        return body

    def _list(self, path, params=None, use_cache=True):
        """Devuelve la lista 'matches'/'teams'/'competitions' del envelope."""
        body = self._get(path, params=params, use_cache=use_cache)
        if isinstance(body, dict):
            key = self._list_key(path)
            return body.get(key, []) or []
        return body or []

    @staticmethod
    def _list_key(path):
        """Nombre de la clave de lista según el endpoint (v4)."""
        if path.startswith("/v4/competitions"):
            if path.endswith("/matches"):
                return "matches"
            if path.endswith("/teams"):
                return "teams"
            if path.endswith("/scorers"):
                return "scorers"
            return "competitions"
        if path.startswith("/v4/matches"):
            return "matches"
        if path.startswith("/v4/teams"):
            return "teams"
        if path.startswith("/v4/areas"):
            return "areas"
        return "response"

    # ------------------------------------------------------------------ #
    # Competiciones
    # ------------------------------------------------------------------ #

    def get_competitions(self):
        """Lista todas las competiciones del catálogo (plan Free: las 12
        accesibles devuelven datos; las demás 403 al pedir subrecursos)."""
        return self._list("/v4/competitions")

    def get_competition(self, competition_id):
        """Detalle de una competición, incluyendo seasons[] (sirve para
        saber qué años hay disponibles para backfill)."""
        return self._get(f"/v4/competitions/{competition_id}")

    def get_competition_matches(
        self,
        competition_id,
        season=None,
        date_from=None,
        date_to=None,
        status=None,
        matchday=None,
    ):
        """Partidos de una competición. Por defecto la temporada activa;
        usar season=YYYY para temporadas históricas (backfill)."""
        params = {
            "season": season,
            "dateFrom": date_from,
            "dateTo": date_to,
            "status": status,
            "matchday": matchday,
        }
        return self._list(
            f"/v4/competitions/{competition_id}/matches", params=params
        )

    def get_competition_teams(self, competition_id, season=None):
        """Equipos participantes en una competición/temporada."""
        params = {"season": season}
        return self._list(
            f"/v4/competitions/{competition_id}/teams", params=params
        )

    # ------------------------------------------------------------------ #
    # Partidos
    # ------------------------------------------------------------------ #

    def get_matches(
        self,
        date_from=None,
        date_to=None,
        competitions=None,
        status=None,
    ):
        """Partidos de todas las competiciones accesibles en un rango de
        fechas. Una sola petición cubre toda la ventana del daily sync."""
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "competitions": competitions,
            "status": status,
        }
        return self._list("/v4/matches", params=params)

    # ------------------------------------------------------------------ #
    # Equipos
    # ------------------------------------------------------------------ #

    def get_team(self, team_id):
        """Detalle de un equipo (founded, venue, clubColors, ...)."""
        return self._get(f"/v4/teams/{team_id}")
