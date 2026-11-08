import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from surebet.__main__ import cycle
from surebet.config import Config
from surebet.detector import allocate_stakes, find_surebets, parse_ts
from surebet.portfolio import Portfolio

FX = Path(__file__).parent / "fixtures"
POLLS = json.loads((FX / "odds_polls.json").read_text())
SCORES = json.loads((FX / "scores.json").read_text())


class DetectorTest(unittest.TestCase):
    def setUp(self):
        self.cfg = Config()
        self.now = parse_ts(POLLS[0]["now"])
        self.found = {(s.event_id, s.market): s for s in find_surebets(POLLS[0]["events"], self.cfg, self.now)}

    def test_three_way_arb(self):
        sb = self.found[("ev_fla_pal", "h2h")]
        self.assertEqual({l.bookmaker for l in sb.legs}, {"pinnacle", "betsson", "unibet_eu"})
        self.assertAlmostEqual(sb.roi, 1 / (1 / 2.6 + 1 / 3.7 + 1 / 3.25) - 1, places=5)
        self.assertFalse(sb.suspicious)

    def test_exchange_commission_applied(self):
        sb = self.found[("ev_ars_che", "totals")]
        under = next(l for l in sb.legs if l.outcome == "Under")
        self.assertAlmostEqual(under.effective, 1 + 1.12 * 0.95)
        self.assertEqual(sb.point, 2.5)

    def test_no_false_arb_in_h2h(self):
        self.assertNotIn(("ev_ars_che", "h2h"), self.found)

    def test_absurd_margin_flagged(self):
        self.assertTrue(self.found[("ev_lal_bos", "h2h")].suspicious)

    def test_stale_quote_ignored(self):
        self.assertNotIn(("ev_stale", "h2h"), self.found)

    def test_allocation_equalizes_return(self):
        sb = self.found[("ev_fla_pal", "h2h")]
        a = allocate_stakes(sb, 100, 1.0)
        payouts = [s * l.effective for s, l in zip(a["stakes"], sb.legs)]
        self.assertTrue(all(p > a["total_stake"] for p in payouts))
        self.assertGreater(a["expected_profit"], 0)


class EndToEndTest(unittest.TestCase):
    def test_full_cycle(self):
        with tempfile.TemporaryDirectory() as d:
            cfg = replace(Config(), data_dir=Path(d) / "data", report_path=Path(d) / "REPORT.md")
            pf = Portfolio(cfg)
            for p in POLLS:
                cycle(cfg, pf, parse_ts(p["now"]),
                      fetch_odds=lambda s, p=p: [e for e in p["events"] if e["sport_key"] == s],
                      fetch_scores=lambda s: [e for e in SCORES["events"] if e["sport_key"] == s])
            bets = {b["event_id"]: b for b in pf.state["bets"]}
            self.assertEqual(set(bets), {"ev_fla_pal", "ev_ars_che"})  # suspeita e obsoleta não apostadas
            self.assertTrue(bets["ev_fla_pal"]["confirmed"])            # gap persistiu
            self.assertFalse(bets["ev_ars_che"]["confirmed"])           # gap fechou em 30 min
            self.assertEqual(bets["ev_ars_che"]["winner"], "Under")     # 1x1 em linha 2.5
            self.assertEqual(bets["ev_fla_pal"]["winner"], "Flamengo")
            for b in bets.values():
                self.assertEqual(b["status"], "settled")
                self.assertGreater(b["profit"], 0)
            total_profit = sum(b["profit"] for b in bets.values())
            self.assertAlmostEqual(pf.state["cash"], 1000 + total_profit, places=2)
            self.assertIn("Banca", cfg.report_path.read_text())


if __name__ == "__main__":
    unittest.main()
