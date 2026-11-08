"""Configuração via variáveis de ambiente (com defaults pensados para o teste de 1 semana)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_SPORTS = [
    "soccer_brazil_campeonato",
    "soccer_brazil_serie_b",
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_uefa_champs_league",
    "basketball_nba",
]

# Casas de exchange: cobram comissão sobre o lucro líquido da aposta vencedora.
EXCHANGES = {"betfair_ex_eu", "betfair_ex_uk", "betfair_ex_au", "matchbook", "smarkets"}


def _list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [x.strip() for x in raw.split(",") if x.strip()]


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    return float(raw) if raw not in (None, "") else default


@dataclass(frozen=True)
class Config:
    api_key: str = ""
    sports: list[str] = field(default_factory=lambda: list(DEFAULT_SPORTS))
    regions: list[str] = field(default_factory=lambda: ["eu", "uk"])
    markets: list[str] = field(default_factory=lambda: ["h2h", "totals"])
    excluded_bookmakers: list[str] = field(default_factory=list)

    # Banca virtual
    bankroll_initial: float = 1000.0
    stake_pct: float = 0.10          # fração da banca por surebet
    stake_max: float = 150.0         # teto em R$ por surebet
    stake_min: float = 20.0          # abaixo disso não vale a pena (arredondamento come a margem)
    stake_rounding: float = 1.0      # apostas reais são em reais inteiros
    test_days: float = 7.0           # após isso só liquida, não abre novas

    # Filtros de qualidade do gap
    min_roi: float = 0.005           # 0,5% de lucro garantido mínimo
    max_roi: float = 0.08            # acima disso é quase sempre odd errada/obsoleta: registra, não aposta
    max_quote_age_min: float = 15.0  # odd mais velha que isso é descartada
    min_minutes_to_start: float = 15.0
    max_days_to_start: float = 7.0
    exchange_commission: float = 0.05

    # Orçamento de API
    min_credits_left: int = 150

    data_dir: Path = ROOT / "data"
    report_path: Path = ROOT / "REPORT.md"

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            api_key=os.getenv("ODDS_API_KEY", ""),
            sports=_list("SUREBET_SPORTS", DEFAULT_SPORTS),
            regions=_list("SUREBET_REGIONS", ["eu", "uk"]),
            markets=_list("SUREBET_MARKETS", ["h2h", "totals"]),
            excluded_bookmakers=_list("SUREBET_EXCLUDED_BOOKMAKERS", []),
            bankroll_initial=_float("SUREBET_BANKROLL", 1000.0),
            stake_pct=_float("SUREBET_STAKE_PCT", 0.10),
            stake_max=_float("SUREBET_STAKE_MAX", 150.0),
            stake_min=_float("SUREBET_STAKE_MIN", 20.0),
            test_days=_float("SUREBET_TEST_DAYS", 7.0),
            min_roi=_float("SUREBET_MIN_ROI", 0.005),
            max_roi=_float("SUREBET_MAX_ROI", 0.08),
            max_quote_age_min=_float("SUREBET_MAX_QUOTE_AGE_MIN", 15.0),
            exchange_commission=_float("SUREBET_EXCHANGE_COMMISSION", 0.05),
            min_credits_left=int(_float("SUREBET_MIN_CREDITS_LEFT", 150)),
            data_dir=Path(os.getenv("SUREBET_DATA_DIR", str(ROOT / "data"))),
            report_path=Path(os.getenv("SUREBET_REPORT_PATH", str(ROOT / "REPORT.md"))),
        )
