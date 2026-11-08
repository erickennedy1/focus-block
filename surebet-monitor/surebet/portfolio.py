"""Banca virtual: abre apostas nos gaps, mede quanto tempo o gap dura e liquida com o placar real."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .config import Config
from .detector import Surebet, allocate_stakes, parse_ts

SETTLE_AFTER = timedelta(hours=3)    # tempo após o início para buscar o resultado
VOID_AFTER = timedelta(hours=72)     # sem resultado até aqui: devolve (void)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Portfolio:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.path: Path = cfg.data_dir / "state.json"
        self.sightings_log: Path = cfg.data_dir / "sightings.jsonl"
        self.state = self._load()

    # ---------- persistência ----------
    def _load(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text(encoding="utf-8"))
        return {"bankroll_initial": self.cfg.bankroll_initial, "cash": self.cfg.bankroll_initial,
                "started_at": None, "polls": [], "bets": [], "sightings": {}, "api": {}}

    def save(self) -> None:
        self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    # ---------- janela do teste ----------
    def start(self, now: datetime) -> None:
        if not self.state["started_at"]:
            self.state["started_at"] = iso(now)

    def accepting_new_bets(self, now: datetime) -> bool:
        started = parse_ts(self.state["started_at"])
        return now < started + timedelta(days=self.cfg.test_days)

    # ---------- leitura (poll) ----------
    def record_poll(self, now: datetime, surebets: list[Surebet], events: int, errors: list[str],
                    credits_remaining: int | None) -> None:
        current = {sb.key for sb in surebets}
        sightings = self.state["sightings"]
        log_lines = []
        for sb in surebets:
            s = sightings.get(sb.key)
            if s is None:
                s = sightings[sb.key] = {
                    "slot": sb.slot, "sport_key": sb.sport_key, "match": f"{sb.home} x {sb.away}",
                    "commence_time": sb.commence_time, "market": sb.market, "point": sb.point,
                    "bookmakers": sorted({l.bookmaker for l in sb.legs}),
                    "first_seen": iso(now), "last_seen": iso(now), "polls_seen": 0,
                    "max_roi": sb.roi, "suspicious": sb.suspicious, "flags": sb.flags,
                }
            s["last_seen"] = iso(now)
            s["polls_seen"] += 1
            s["max_roi"] = max(s["max_roi"], sb.roi)
            log_lines.append(json.dumps({"ts": iso(now), **sb.to_dict()}, ensure_ascii=False))

        # Confirmação: o gap da aposta ainda existia em uma leitura posterior?
        for bet in self.state["bets"]:
            if bet["status"] != "open" or bet["placed_at"] == iso(now):
                continue
            if parse_ts(bet["commence_time"]) <= now:
                continue
            bet["rechecks"] = bet.get("rechecks", 0) + 1
            if bet["key"] in current:
                bet["confirmed"] = True

        self.state["polls"].append({"ts": iso(now), "events": events, "surebets": len(surebets),
                                    "errors": errors, "credits_remaining": credits_remaining})
        if credits_remaining is not None:
            self.state["api"]["remaining"] = credits_remaining
        if log_lines:
            self.cfg.data_dir.mkdir(parents=True, exist_ok=True)
            with self.sightings_log.open("a", encoding="utf-8") as f:
                f.write("\n".join(log_lines) + "\n")

    # ---------- abrir apostas ----------
    def place(self, surebets: list[Surebet], now: datetime) -> list[dict]:
        if not self.accepting_new_bets(now):
            return []
        taken = {b["slot"] for b in self.state["bets"]}
        placed = []
        for sb in sorted(surebets, key=lambda s: s.roi, reverse=True):
            if sb.suspicious or sb.slot in taken:
                continue
            equity = self.state["cash"] + sum(b["total_stake"] for b in self.state["bets"] if b["status"] == "open")
            target = min(self.cfg.stake_max, equity * self.cfg.stake_pct, self.state["cash"])
            if target < self.cfg.stake_min:
                continue
            alloc = allocate_stakes(sb, target, self.cfg.stake_rounding)
            if alloc is None or alloc["total_stake"] > self.state["cash"]:
                continue
            bet = {
                "id": len(self.state["bets"]) + 1, "key": sb.key, "slot": sb.slot,
                "event_id": sb.event_id, "sport_key": sb.sport_key, "sport_title": sb.sport_title,
                "home": sb.home, "away": sb.away, "commence_time": sb.commence_time,
                "market": sb.market, "point": sb.point, "roi_detected": sb.roi,
                "legs": [{"outcome": l.outcome, "bookmaker": l.bookmaker, "bookmaker_title": l.bookmaker_title,
                          "price": l.price, "effective": round(l.effective, 4), "stake": st}
                         for l, st in zip(sb.legs, alloc["stakes"])],
                **{k: alloc[k] for k in ("total_stake", "guaranteed_return", "expected_profit")},
                "placed_at": iso(now), "status": "open", "confirmed": False, "rechecks": 0,
            }
            self.state["cash"] = round(self.state["cash"] - bet["total_stake"], 2)
            self.state["bets"].append(bet)
            taken.add(sb.slot)
            placed.append(bet)
        return placed

    # ---------- liquidar ----------
    def sports_to_settle(self, now: datetime) -> set[str]:
        return {b["sport_key"] for b in self.state["bets"]
                if b["status"] == "open" and now >= parse_ts(b["commence_time"]) + SETTLE_AFTER}

    def settle(self, scores_by_sport: dict[str, list[dict]], now: datetime) -> list[dict]:
        settled = []
        index = {ev["id"]: ev for evs in scores_by_sport.values() for ev in evs}
        for bet in self.state["bets"]:
            if bet["status"] != "open":
                continue
            start = parse_ts(bet["commence_time"])
            if now < start + SETTLE_AFTER:
                continue
            ev = index.get(bet["event_id"])
            if ev and ev.get("completed") and ev.get("scores"):
                self._settle_one(bet, ev, now)
                settled.append(bet)
            elif now >= start + VOID_AFTER:
                self._close(bet, payout=bet["total_stake"], status="void", now=now, note="sem resultado em 72h")
                settled.append(bet)
        return settled

    def _settle_one(self, bet: dict, ev: dict, now: datetime) -> None:
        sc = {s["name"]: float(s["score"]) for s in ev["scores"]}
        home, away = sc.get(bet["home"]), sc.get(bet["away"])
        if home is None or away is None:
            self._close(bet, bet["total_stake"], "void", now, "placar incompleto")
            return
        score_txt = f"{home:g} x {away:g}"
        if bet["market"] == "h2h":
            winner = bet["home"] if home > away else bet["away"] if away > home else "Draw"
        else:
            total = home + away
            if total == bet["point"]:
                self._close(bet, bet["total_stake"], "settled", now, f"push ({score_txt})", winner="push")
                return
            winner = "Over" if total > bet["point"] else "Under"
        payout = sum(l["stake"] * l["effective"] for l in bet["legs"] if l["outcome"] == winner)
        self._close(bet, payout, "settled", now, score_txt, winner=winner)

    def _close(self, bet: dict, payout: float, status: str, now: datetime, note: str, winner: str | None = None):
        bet.update(status=status, settled_at=iso(now), payout=round(payout, 2),
                   profit=round(payout - bet["total_stake"], 2), result=note, winner=winner)
        self.state["cash"] = round(self.state["cash"] + payout, 2)
