"""Gera o REPORT.md (PT-BR) a partir do estado da banca."""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from statistics import median

from .detector import parse_ts


def brl(v: float) -> str:
    s = f"{abs(v):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{'-' if v < 0 else ''}R$ {s}"


def pct(v: float) -> str:
    return f"{v * 100:.2f}%".replace(".", ",")


def _dur_min(s: dict) -> float:
    return (parse_ts(s["last_seen"]) - parse_ts(s["first_seen"])).total_seconds() / 60


def build_report(state: dict, now: datetime, cfg) -> str:
    bets, polls, sightings = state["bets"], state["polls"], state["sightings"]
    initial = state["bankroll_initial"]
    open_bets = [b for b in bets if b["status"] == "open"]
    closed = [b for b in bets if b["status"] != "open"]
    open_stake = sum(b["total_stake"] for b in open_bets)
    realized = sum(b["profit"] for b in closed)
    expected_open = sum(b["expected_profit"] for b in open_bets)
    conf_closed = [b for b in closed if b.get("confirmed")]
    conf_open = [b for b in open_bets if b.get("confirmed")]
    conservative = sum(b["profit"] for b in conf_closed)
    turnover = sum(b["total_stake"] for b in bets)

    valid = [s for s in sightings.values() if not s["suspicious"]]
    susp = [s for s in sightings.values() if s["suspicious"]]
    multi_poll = [s for s in valid if s["polls_seen"] > 1]
    rois = [s["max_roi"] for s in valid]

    L = []
    L.append("# Teste surebet: banca virtual de R$ 1.000\n")
    L.append(f"Atualizado em {now.strftime('%d/%m/%Y %H:%M')} UTC. "
             f"Início: {state['started_at'] or 'n/d'}. Duração planejada: {cfg.test_days:g} dias. "
             f"Leituras realizadas: {len(polls)}. Créditos de API restantes: {state['api'].get('remaining', 'n/d')}.\n")

    L.append("## Banca\n")
    L.append("| Métrica | Valor |\n|---|---|")
    L.append(f"| Banca inicial | {brl(initial)} |")
    L.append(f"| Caixa livre | {brl(state['cash'])} |")
    L.append(f"| Em apostas abertas | {brl(open_stake)} ({len(open_bets)} apostas) |")
    L.append(f"| Lucro realizado | {brl(realized)} ({pct(realized / initial)}) |")
    L.append(f"| Lucro garantido ainda a liquidar | {brl(expected_open)} |")
    L.append(f"| Banca projetada | {brl(initial + realized + expected_open)} |")
    L.append(f"| Volume apostado (giro) | {brl(turnover)} |")
    L.append(f"| Cenário conservador: lucro realizado só com gaps que persistiram até a leitura seguinte | "
             f"{brl(conservative)} ({len(conf_closed)} liquidadas, {len(conf_open)} abertas) |\n")

    L.append("## Os gaps existem?\n")
    L.append("| Métrica | Valor |\n|---|---|")
    L.append(f"| Surebets distintas detectadas (válidas) | {len(valid)} |")
    L.append(f"| Descartadas como suspeitas (margem > {pct(cfg.max_roi)} ou casa única) | {len(susp)} |")
    if rois:
        L.append(f"| Margem mediana / máxima | {pct(median(rois))} / {pct(max(rois))} |")
    if valid:
        L.append(f"| Persistiram por 2+ leituras | {len(multi_poll)} ({pct(len(multi_poll) / len(valid))}) |")
    if multi_poll:
        L.append(f"| Duração mediana das que persistiram | {median(_dur_min(s) for s in multi_poll):.0f} min |")
    gaps_per_poll = [p["surebets"] for p in polls]
    if gaps_per_poll:
        L.append(f"| Gaps por leitura (média) | {sum(gaps_per_poll) / len(gaps_per_poll):.1f}".replace(".", ",") + " |")
    L.append("")

    if valid:
        L.append("### Onde aparecem\n")
        by_sport = Counter(s["sport_key"] for s in valid)
        by_book = Counter(bk for s in valid for bk in s["bookmakers"])
        by_market = Counter(s["market"] for s in valid)
        L.append("| Esporte | Gaps |\n|---|---|")
        L += [f"| {k} | {v} |" for k, v in by_sport.most_common()]
        L.append("\n| Casa (participa do gap) | Gaps |\n|---|---|")
        L += [f"| {k} | {v} |" for k, v in by_book.most_common(15)]
        L.append("\n| Mercado | Gaps |\n|---|---|")
        L += [f"| {k} | {v} |" for k, v in by_market.most_common()]
        L.append("")

    L.append("## Apostas virtuais (mais recentes primeiro)\n")
    if not bets:
        L.append("Nenhuma aposta aberta ainda.\n")
    else:
        L.append("| # | Jogo | Mercado | Pernas | Apostado | Margem | Persistiu | Status | Lucro |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for b in sorted(bets, key=lambda b: b["id"], reverse=True)[:40]:
            mk = b["market"] + (f" {b['point']:g}" if b["point"] is not None else "")
            legs = "<br>".join(f"{l['outcome']} @ {l['price']:.2f} ({l['bookmaker_title']}) {brl(l['stake'])}"
                               for l in b["legs"])
            persisted = "sim" if b.get("confirmed") else ("não" if b.get("rechecks") else "n/a")
            status = b["status"] if b["status"] == "open" else f"{b['status']}: {b.get('result', '')}"
            profit = brl(b["profit"]) if "profit" in b else f"{brl(b['expected_profit'])} (esperado)"
            L.append(f"| {b['id']} | {b['home']} x {b['away']}<br>{b['commence_time'][:16]} | {mk} | {legs} | "
                     f"{brl(b['total_stake'])} | {pct(b['roi_detected'])} | {persisted} | {status} | {profit} |")
        L.append("")

    errs = [e for p in polls[-10:] for e in p["errors"]]
    if errs:
        L.append("## Erros recentes\n")
        L += [f"- {e}" for e in errs[-10:]]
        L.append("")

    L.append("## Como ler\n")
    L.append("- **Lucro realizado** já considera o placar real. Numa surebet o placar não deveria mudar o "
             "resultado; diferenças vêm de arredondamento das apostas, push em totals e jogos anulados.")
    L.append("- **Persistiu** = o mesmo gap (mesmas casas) ainda estava aberto na leitura seguinte, ~30 min depois. "
             "É o melhor proxy de que daria tempo de apostar manualmente. O cenário conservador conta só essas.")
    L.append("- O teste é otimista em três pontos: assume que as casas aceitariam o valor sem limitar, "
             "que a odd não mudou entre uma perna e outra e que nenhuma casa cancelaria a aposta.")
    return "\n".join(L) + "\n"
