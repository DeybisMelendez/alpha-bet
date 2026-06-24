import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.utils import timezone

from api_client.models import ApiResponseCache


class FootballDataClient:
    def __init__(
        self,
        token=None,
        base_url=None,
        cache_ttl_minutes=None,
        timeout=30,
    ):
        self.token = token or settings.FOOTBALL_DATA_API_KEY
        self.base_url = (base_url or settings.FOOTBALL_DATA_API_BASE_URL).rstrip("/")
        self.cache_ttl = cache_ttl_minutes or settings.API_CACHE_TTL_MINUTES
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"X-Auth-Token": self.token})

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
        response.raise_for_status()
        body = response.json()

        if use_cache:
            ApiResponseCache.objects.update_or_create(
                url=url, defaults={"body": body}
            )
        return body

    def get_competitions(self):
        return self._get("/competitions").get("competitions", [])

    def get_competition(self, code):
        return self._get(f"/competitions/{code}")

    def get_competition_teams(self, code):
        return self._get(f"/competitions/{code}/teams").get("teams", [])

    def get_competition_matches(self, code, matchday=None, season=None,
                                date_from=None, date_to=None):
        params = {}
        if matchday is not None:
            params["matchday"] = matchday
        if season is not None:
            params["season"] = season
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        return self._get(f"/competitions/{code}/matches", params=params).get(
            "matches", []
        )

    def get_team(self, team_id):
        return self._get(f"/teams/{team_id}")

    def get_team_matches(
        self,
        team_id,
        limit=None,
        date_from=None,
        date_to=None,
        status=None,
        season=None,
    ):
        params = {}
        if limit is not None:
            params["limit"] = limit
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        if status is not None:
            params["status"] = status
        if season is not None:
            params["season"] = season
        return self._get(f"/teams/{team_id}/matches", params=params).get(
            "matches", []
        )

    def get_matches(self, date_from=None, date_to=None, competitions=None):
        params = {}
        if date_from is not None:
            params["dateFrom"] = date_from
        if date_to is not None:
            params["dateTo"] = date_to
        if competitions:
            params["competitions"] = ",".join(competitions)
        return self._get("/matches", params=params).get("matches", [])


class ApiFootballClient:
    """Cliente para api-football.com (api-sports.io v3).

    Fuente de selecciones nacionales, copas CONCACAF y ligas de
    Centro/Norteamérica. Ver docs/api_football.md.
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
            # Rate limit: esperar 60s y reintentar una vez.
            import logging
            logging.getLogger("alpha").warning(
                "API-Football 429, esperando 60s para reintentar..."
            )
            time.sleep(60)
            response = self.session.get(url, timeout=self.timeout)
        response.raise_for_status()
        body = response.json()

        if use_cache:
            ApiResponseCache.objects.update_or_create(
                url=url, defaults={"body": body}
            )
        return body

    def get_leagues(self, search=None, country=None):
        params = {}
        if search:
            params["search"] = search
        if country:
            params["country"] = country
        return self._get("/leagues", params=params).get("response", [])

    def get_league(self, league_id):
        return self._get("/leagues", params={"id": league_id}).get("response", [])

    def get_teams(self, league, season):
        return self._get(
            "/teams", params={"league": league, "season": season}
        ).get("response", [])

    def get_fixtures_by_date(self, date_str):
        """Partidos de todas las ligas en una fecha (ventana hoy ± 1 en Free)."""
        return self._get(
            "/fixtures", params={"date": date_str}
        ).get("response", [])

    def get_fixtures(self, league, season, date_from=None, date_to=None):
        params = {"league": league, "season": season}
        if date_from:
            params["from"] = date_from
        if date_to:
            params["to"] = date_to
        return self._get("/fixtures", params=params).get("response", [])

    def get_countries(self):
        return self._get("/countries").get("response", [])
