"""CLI: python -m surebet run | report | demo"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, Config
from .detector import find_surebets, parse_ts
from .odds_api import OddsAPI, OddsAPIError
from .portfolio import Portfolio
from .report import brl, build_report, pct


def log(msg: str) -> None:
    print(msg, flush=True)


def cycle(cfg: Config, pf: Portfolio, now: datetime, fetch_odds, fetch_scores, credits=lambda: None) -> None:
    pf.start(now)
    events, errors = [], []
    if pf.accepting_new_bets(now):
        for sport in cfg.sports:
            rem = credits()
            if rem is not None and rem < cfg.min_credits_left:
                errors.append(f"orçamento de API no limite ({rem} créditos), leitura interrompida")
                break
            try:
                evs = fetch_odds(sport)
                events += evs
                log(f"  {sport}: {len(evs)} jogos")
            except OddsAPIError as e:
                errors.append(f"{sport}: {e}")
                log(f"  {sport}: ERRO {e}")
    else:
        log("Janela do teste encerrada: apenas liquidando apostas abertas.")

    surebets = find_surebets(events, cfg, now)
    pf.record_poll(now, surebets, len(events), errors, credits())
    for sb in surebets:
        tag = " [SUSPEITA: " + ",".join(sb.flags) + "]" if sb.suspicious else ""
        log(f"  GAP {pct(sb.roi)} {sb.home} x {sb.away} {sb.market} {sb.point or ''}: "
            + " | ".join(f"{l.outcome}@{l.price} {l.bookmaker}" for l in sb.legs) + tag)

    for bet in pf.place(surebets, now):
        log(f"  APOSTA #{bet['id']} {brl(bet['total_stake'])} lucro garantido {brl(bet['expected_profit'])}")

    scores = {}
    for sport in pf.sports_to_settle(now):
        try:
            scores[sport] = fetch_scores(sport)
        except OddsAPIError as e:
            pf.state["polls"][-1]["errors"].append(f"placar {sport}: {e}")
    for bet in pf.settle(scores, now):
        log(f"  LIQUIDADA #{bet['id']} {bet['result']} lucro {brl(bet['profit'])}")

    pf.save()
    cfg.report_path.write_text(build_report(pf.state, now, cfg), encoding="utf-8")
    log(f"Caixa {brl(pf.state['cash'])} | gaps nesta leitura: {len(surebets)} | relatório: {cfg.report_path}")


def cmd_run(cfg: Config) -> int:
    try:
        api = OddsAPI(cfg.api_key)
    except OddsAPIError as e:
        log(f"ERRO: {e}")
        return 2
    pf = Portfolio(cfg)
    now = datetime.now(timezone.utc)
    log(f"Leitura {now.isoformat(timespec='seconds')}")
    cycle(cfg, pf, now,
          fetch_odds=lambda s: api.odds(s, cfg.regions, cfg.markets),
          fetch_scores=lambda s: api.scores(s, 3),
          credits=lambda: api.remaining)
    return 0


def cmd_report(cfg: Config) -> int:
    pf = Portfolio(cfg)
    cfg.report_path.write_text(build_report(pf.state, datetime.now(timezone.utc), cfg), encoding="utf-8")
    log(f"Relatório: {cfg.report_path}")
    return 0


def cmd_demo(out_dir: Path) -> int:
    """Roda duas leituras + liquidação sobre fixtures locais, sem rede."""
    fx = ROOT / "tests" / "fixtures"
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = replace(Config(), data_dir=out_dir / "data", report_path=out_dir / "REPORT.md")
    for f in (cfg.data_dir / "state.json", cfg.data_dir / "sightings.jsonl"):
        f.unlink(missing_ok=True)
    pf = Portfolio(cfg)
    polls = json.loads((fx / "odds_polls.json").read_text())
    scores = json.loads((fx / "scores.json").read_text())
    for p in polls:
        now = parse_ts(p["now"])
        log(f"Leitura simulada {p['now']}")
        cycle(cfg, pf, now, fetch_odds=lambda s, p=p: [e for e in p["events"] if e["sport_key"] == s],
              fetch_scores=lambda s: [e for e in scores["events"] if e["sport_key"] == s])
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="surebet")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="uma leitura: busca odds, detecta, aposta virtualmente, liquida, gera relatório")
    sub.add_parser("report", help="só regenera o REPORT.md")
    d = sub.add_parser("demo", help="simulação offline com fixtures")
    d.add_argument("--out", default=str(ROOT / ".demo"))
    args = ap.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(Config.from_env())
    if args.cmd == "report":
        return cmd_report(Config.from_env())
    return cmd_demo(Path(args.out))


if __name__ == "__main__":
    sys.exit(main())
