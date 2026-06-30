import logging
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

from api_client.models import ApiResponseCache

logger = logging.getLogger("alpha")


class ApiFootballClient:
    """Cliente para api-football.com (api-sports.io v3).

    Única fuente de datos. La caché ApiResponseCache (TTL configurable,
    default 60 min) evita quemar requests durante reintentos y backfill
    interrumpido. El header x-ratelimit-requests-remaining se expose vía
    last_rate_remaining para que el backfill pueda cortar antes de tocar
    el techo diario.
    """

    BASE_URL = "https://v3.football.api-sports.io"

    def __init__(
        self,
        token=None,
        base_url=None,
        cache_ttl_minutes=None,
        timeout=30,
    ):
        self.token = token or settings.API_FOOTBALL_KEY
        self.base_url = (base_url or settings.API_FOOTBALL_BASE_URL).rstrip("/")
        self.cache_ttl = cache_ttl_minutes or settings.API_CACHE_TTL_MINUTES
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"x-apisports-key": self.token})
        self.last_rate_remaining = None

    def _build_url(self, path, params=None):
        url = f"{self.base_url}/{path.lstrip('/')}"
        if params:
            url = f"{url}?{urlencode(params)}"
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
            # Rate limit por minuto: esperar 60s y reintentar una vez.
            logger.warning("API-Football 429, esperando 60s para reintentar...")
            time.sleep(60)
            response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()

        # Exponer remaining del techo diario (si viene en headers).
        remaining = response.headers.get("x-ratelimit-requests-remaining")
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

    def _response(self, path, params=None, use_cache=True):
        return self._get(path, params=params, use_cache=use_cache).get("response", [])

    def get_countries(self):
        """Lista de países disponibles."""
        return self._response("/countries")

    def get_all_seasons(self):
        """Array plano de años con cobertura en el plan actual (vía
        /leagues/seasons). Útil para detectar el rango accesible y
        confirmar si la key tiene plan Pro (incluye 2025+)."""
        return self._get("/leagues/seasons").get("response", [])

    def get_leagues(self, current=None, search=None, country=None):
        """Lista competiciones. current=True → solo ligas en temporada
        activa (catálogo más pequeño). Sin filtros → todo el catálogo
        (apta para descubrimiento total con plan Pro)."""
        params = {}
        if current is not None:
            params["current"] = "true" if current else "false"
        if search:
            params["search"] = search
        if country:
            params["country"] = country
        return self._response("/leagues", params=params)

    def get_league(self, league_id):
        """Detalle de una liga, incluyendo seasons[] con coverage por
        temporada (sirve para saber qué años están disponibles para
        backfill)."""
        return self._response("/leagues", params={"id": league_id})

    def get_teams(self, league, season):
        """Equipos participantes en una liga/temporada."""
        return self._response(
            "/teams", params={"league": league, "season": season}
        )

    def get_fixtures_by_date(self, date_str):
        """Partidos de todas las ligas en una fecha (YYYY-MM-DD). En
        plan Free restringido a hoy ± 1 día; en plan Pro sin restricción."""
        return self._response("/fixtures", params={"date": date_str})

    def get_fixtures(self, league, season, date_from=None, date_to=None):
        """Partidos de una liga × temporada. api-football retorna todo
        en una sola respuesta (cientos de fixtures); si la respuesta
        trae paging.total>1 se debe paginar (raro en fixtures de liga)."""
        params = {"league": league, "season": season}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        return self._response("/fixtures", params=params)

    def get_fixture_statistics(self, fixture_id):
        """Estadísticas por equipo de un partido finalizado.

        Endpoint /fixtures/statistics?fixture=ID. Devuelve una lista de
        entradas (una por equipo) con statistics[] (pares tipo/valor).
        Disponible normalmente solo tras finalizado el partido. Plan
        Free puede no incluir este endpoint en competiciones select.
        """
        return self._response(
            "/fixtures/statistics", params={"fixture": fixture_id}
        )