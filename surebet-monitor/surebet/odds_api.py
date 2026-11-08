"""Cliente mínimo (stdlib) da The Odds API v4: https://the-odds-api.com/liveapi/guides/v4/"""
from __future__ import annotations

import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://api.the-odds-api.com/v4"


class OddsAPIError(RuntimeError):
    pass


class OddsAPI:
    def __init__(self, api_key: str, timeout: float = 30.0):
        if not api_key:
            raise OddsAPIError("ODDS_API_KEY não definida")
        self.api_key = api_key
        self.timeout = timeout
        self.remaining: int | None = None
        self.used: int | None = None

    def _get(self, path: str, params: dict) -> list:
        query = urlencode({**params, "apiKey": self.api_key})
        req = Request(f"{BASE}{path}?{query}", headers={"User-Agent": "surebet-monitor/1.0"})
        try:
            with urlopen(req, timeout=self.timeout) as resp:
                rem, used = resp.headers.get("x-requests-remaining"), resp.headers.get("x-requests-used")
                if rem is not None:
                    self.remaining = int(float(rem))
                if used is not None:
                    self.used = int(float(used))
                return json.load(resp)
        except HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:300]
            raise OddsAPIError(f"HTTP {e.code} em {path}: {body}") from e

    def odds(self, sport: str, regions: list[str], markets: list[str]) -> list:
        return self._get(
            f"/sports/{sport}/odds",
            {"regions": ",".join(regions), "markets": ",".join(markets),
             "oddsFormat": "decimal", "dateFormat": "iso"},
        )

    def scores(self, sport: str, days_from: int = 3) -> list:
        return self._get(f"/sports/{sport}/scores", {"daysFrom": days_from, "dateFormat": "iso"})
