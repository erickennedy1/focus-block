"""Detecção de surebets: para cada mercado, pega a melhor odd de cada resultado entre todas as casas.
Se a soma das probabilidades implícitas (1/odd) for < 1, existe lucro garantido."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone

from .config import EXCHANGES, Config


def parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


@dataclass
class Leg:
    outcome: str
    bookmaker: str
    bookmaker_title: str
    price: float
    effective: float  # odd líquida de comissão (exchanges)
    last_update: str


@dataclass
class Surebet:
    key: str
    event_id: str
    sport_key: str
    sport_title: str
    home: str
    away: str
    commence_time: str
    market: str
    point: float | None
    legs: list[Leg]
    implied_sum: float
    roi: float
    suspicious: bool
    flags: list[str] = field(default_factory=list)

    @property
    def slot(self) -> str:
        """Identifica o mercado do jogo (uma aposta por slot, mesmo que a combinação de casas mude)."""
        return f"{self.event_id}|{self.market}|{self.point}"

    def to_dict(self) -> dict:
        return asdict(self)


def effective_price(price: float, bookmaker: str, commission: float) -> float:
    if bookmaker in EXCHANGES:
        return 1.0 + (price - 1.0) * (1.0 - commission)
    return price


def _expected_outcomes(market: str, event: dict, offered: set[str]) -> set[str] | None:
    if market == "h2h":
        exp = {event["home_team"], event["away_team"]}
        if "Draw" in offered:
            exp.add("Draw")
        return exp
    if market == "totals":
        return {"Over", "Under"}
    return None


def find_surebets(events: list[dict], cfg: Config, now: datetime) -> list[Surebet]:
    found: list[Surebet] = []
    max_age = timedelta(minutes=cfg.max_quote_age_min)
    for ev in events:
        start = parse_ts(ev["commence_time"])
        if start - now < timedelta(minutes=cfg.min_minutes_to_start):
            continue
        if start - now > timedelta(days=cfg.max_days_to_start):
            continue

        # (mercado, linha) -> resultado -> [Leg]
        groups: dict[tuple[str, float | None], dict[str, list[Leg]]] = {}
        for bk in ev.get("bookmakers", []):
            if bk["key"] in cfg.excluded_bookmakers:
                continue
            for m in bk.get("markets", []):
                if m["key"] not in cfg.markets:
                    continue
                lu_raw = m.get("last_update") or bk.get("last_update")
                if not lu_raw or now - parse_ts(lu_raw) > max_age:
                    continue
                for o in m.get("outcomes", []):
                    price = float(o["price"])
                    if price <= 1.0:
                        continue
                    point = float(o["point"]) if m["key"] == "totals" and o.get("point") is not None else None
                    leg = Leg(o["name"], bk["key"], bk.get("title", bk["key"]), price,
                              effective_price(price, bk["key"], cfg.exchange_commission), lu_raw)
                    groups.setdefault((m["key"], point), {}).setdefault(o["name"], []).append(leg)

        for (market, point), by_outcome in groups.items():
            expected = _expected_outcomes(market, ev, set(by_outcome))
            if expected is None or set(by_outcome) != expected:
                continue
            best = [max(legs, key=lambda l: l.effective) for legs in by_outcome.values()]
            implied = sum(1.0 / l.effective for l in best)
            roi = 1.0 / implied - 1.0
            if roi < cfg.min_roi:
                continue
            flags = []
            if roi > cfg.max_roi:
                flags.append("margem_alta_provavel_erro")
            if len({l.bookmaker for l in best}) == 1:
                flags.append("casa_unica")
            best.sort(key=lambda l: l.outcome)
            key = f"{ev['id']}|{market}|{point}|" + "|".join(f"{l.outcome}@{l.bookmaker}" for l in best)
            found.append(Surebet(
                key=key, event_id=ev["id"], sport_key=ev["sport_key"],
                sport_title=ev.get("sport_title", ev["sport_key"]), home=ev["home_team"],
                away=ev["away_team"], commence_time=ev["commence_time"], market=market, point=point,
                legs=best, implied_sum=round(implied, 6), roi=round(roi, 6),
                suspicious=bool(flags), flags=flags,
            ))
    return found


def allocate_stakes(sb: Surebet, total: float, rounding: float) -> dict | None:
    """Divide o valor entre os resultados para retorno igual; arredonda como numa aposta real."""
    implied = sum(1.0 / l.effective for l in sb.legs)
    stakes = []
    for l in sb.legs:
        raw = total * (1.0 / l.effective) / implied
        stakes.append(max(rounding, round(raw / rounding) * rounding))
    payouts = [s * l.effective for s, l in zip(stakes, sb.legs)]
    staked = sum(stakes)
    guaranteed = min(payouts)
    profit = guaranteed - staked
    if profit <= 0:
        return None
    return {
        "stakes": [round(s, 2) for s in stakes],
        "total_stake": round(staked, 2),
        "guaranteed_return": round(guaranteed, 2),
        "expected_profit": round(profit, 2),
    }
