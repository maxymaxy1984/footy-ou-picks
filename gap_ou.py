#!/usr/bin/env python3
"""
GAP Over/Under 2.5 tool for Bet Angel.

  python gap_ou.py download                 # fetch football-data.co.uk CSVs (2005/06 -> now)
  python gap_ou.py backtest                 # walk-forward test of the paper's strategy
  python gap_ou.py backtest --odds bfe      # same, at Betfair Exchange prices with commission
  python gap_ou.py build                    # fit model, write GAP_OU_BetAngel.xlsx for Guardian
  python gap_ou.py update                   # refresh this season's data, then build (run weekly)
"""
import argparse
import datetime as dt
import json
import os
import sys

import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gap_model as gm  # noqa: E402
from build_workbook import build  # noqa: E402

DATA = os.path.join(HERE, "data")
WORKBOOK = os.path.join(HERE, "GAP_OU_BetAngel.xlsx")


def current_season_start(today=None):
    today = today or dt.date.today()
    return today.year if today.month >= 7 else today.year - 1


def load_overrides():
    p = os.path.join(HERE, "team_names.csv")
    if not os.path.exists(p):
        return {}
    df = pd.read_csv(p)
    return dict(zip(df["team"].astype(str), df["betfair_name"].astype(str)))


def cmd_download(a):
    last = a.to or current_season_start()
    print(f"Downloading {a.frm}/{(a.frm + 1) % 100:02d} to {last}/{(last + 1) % 100:02d} ...")
    gm.download(a.data, a.frm, last, a.leagues)


def _filter(d, a, first_year):
    d = d[d["season"].map(gm._season_year) >= first_year]
    if a.leagues:
        d = d[d["league"].isin(a.leagues)]
    return d.reset_index(drop=True)


def cmd_backtest(a):
    d = _filter(gm.load(a.data), a, a.frm)
    odds = {"max": ("max_over", "max_under"), "avg": ("avg_over", "avg_under"),
            "bfe": ("bfe_over", "bfe_under")}[a.odds]
    comm = a.commission if a.commission is not None else (0.05 if a.odds == "bfe" else 0.0)
    print(f"{len(d)} matches. Measure={a.measure}. Betting at {a.odds} odds, commission {comm:.1%}.")
    print("Selecting parameters season by season (this takes a few minutes) ...")
    pred, bets = gm.backtest(d, measure=a.measure, start_season=a.start, reg_odds="max_over",
                             bet_odds=odds, commission=comm)
    bets = gm.settle(pred, odds, comm, a.min_edge)
    if bets.empty:
        print("No bets."); return
    pd.set_option("display.width", 160)
    print("\n=== Overall ===");   print(gm.summarise(bets))
    print("\n=== By side ===");   print(gm.summarise(bets, "side"))
    print("\n=== By league ==="); print(gm.summarise(bets, "league"))
    print("\n=== By season ==="); print(gm.summarise(bets, "season"))
    out = os.path.join(HERE, f"backtest_{a.measure}_{a.odds}.csv")
    bets.to_csv(out, index=False)
    pred.to_csv(os.path.join(HERE, f"predictions_{a.measure}.csv"), index=False)
    print(f"\nBets saved to {out}")


def cmd_build(a):
    d = _filter(gm.load(a.data), a, a.fit_from)
    print(f"Fitting on {len(d)} matches from {a.fit_from}/{(a.fit_from + 1) % 100:02d} ...")
    params_path = os.path.join(HERE, "model_params.json")
    theta0 = (0.3, 0.5, 0.5)
    if os.path.exists(params_path):
        try:
            p = json.load(open(params_path))
            if p.get("measure") == a.measure:
                theta0 = (p["lam"], p["phi1"], p["phi2"])
        except Exception:
            pass
    params, teams = gm.fit_live(d, measure=a.measure, theta0=theta0)
    # keep only teams in each league's latest season
    latest = teams.groupby("league")["season"].transform(lambda s: max(s, key=gm._season_year))
    teams = teams[teams["season"] == latest]
    json.dump(params, open(params_path, "w"), indent=2)
    teams.to_csv(os.path.join(HERE, "team_ratings.csv"), index=False)
    try:
        build(a.out, params, teams, n_sheets=a.sheets, name_overrides=load_overrides())
    except PermissionError:
        sys.exit(f"Cannot write {a.out} - close it in Excel (and disconnect Guardian) and run again.")
    print(f"Workbook written: {a.out}  ({len(teams)} teams)")


def cmd_selections(a):
    """Fit, then write data.json for the selections web page (keeps and settles history)."""
    season = current_season_start()
    if not a.no_download:
        gm.download(a.data, a.fit_from, season, a.leagues, refresh_last=True)
        import urllib.request
        req = urllib.request.Request("https://www.football-data.co.uk/fixtures.csv",
                                     headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r, open(a.fixtures, "wb") as f:
            f.write(r.read())
    d = _filter(gm.load(a.data), a, a.fit_from)
    params, teams = gm.fit_live(d, measure=a.measure)
    latest = teams.groupby("league")["season"].transform(lambda s: max(s, key=gm._season_year))
    teams = teams[teams["season"] == latest]
    fx = gm.load_fixtures(a.fixtures)
    today = pd.Timestamp(dt.date.today())
    fx = fx[fx["date"] >= today]
    picks = gm.upcoming_selections(params, teams, fx, a.commission, a.min_edge, a.min_odds, a.max_odds)

    prev = {"history": [], "upcoming": []}
    if os.path.exists(a.json):
        try:
            prev = json.load(open(a.json, encoding="utf-8"))
        except Exception:
            pass
    results = gm.add_measure(d, a.measure)
    settled, still_open = gm.settle_history(prev.get("upcoming", []), results, a.commission)
    keys = {(p["league"], p["date"], p["home"], p["away"], p["side"]) for p in picks}
    # keep open picks from earlier runs that are not in this run's fixtures (e.g. already kicked off)
    carried = [p for p in still_open if (p["league"], p["date"], p["home"], p["away"], p["side"]) not in keys
               and pd.Timestamp(p["date"]) >= today - pd.Timedelta(days=14)]
    data = {
        "updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "model": {k: params[k] for k in ("measure", "lam", "phi1", "phi2", "alpha", "beta1", "beta2", "last_match", "n_train")},
        "settings": {"commission": a.commission, "min_edge": a.min_edge, "min_odds": a.min_odds, "max_odds": a.max_odds},
        "fixtures_checked": int(len(fx)),
        "upcoming": sorted(picks + carried, key=lambda p: (p["date"], p["time"], p["league"])),
        "history": prev.get("history", []) + settled,
    }
    json.dump(data, open(a.json, "w", encoding="utf-8"), indent=1)
    print(f"{len(picks)} selections from {len(fx)} fixtures; {len(settled)} newly settled. Written {a.json}")


def cmd_update(a):
    season = current_season_start()
    gm.download(a.data, season, season, a.leagues, refresh_last=True)
    cmd_build(a)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=DATA)
    ap.add_argument("--leagues", nargs="*", default=None, help="e.g. E0 E1 SP1 (default: the paper's 10)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("download")
    p.add_argument("--from", dest="frm", type=int, default=2005)
    p.add_argument("--to", type=int, default=None)
    p.set_defaults(fn=cmd_download)

    p = sub.add_parser("backtest")
    p.add_argument("--measure", default="shots_corners", choices=list(gm.MEASURES))
    p.add_argument("--from", dest="frm", type=int, default=2005, help="first season year used (burn-in)")
    p.add_argument("--start", default=None, help="first test season code, e.g. 0607 (default: 2nd season)")
    p.add_argument("--odds", default="max", choices=["max", "avg", "bfe"],
                   help="prices bets are settled at; bfe = Betfair Exchange (from 2019/20 data)")
    p.add_argument("--commission", type=float, default=None)
    p.add_argument("--min-edge", type=float, default=0.0)
    p.set_defaults(fn=cmd_backtest)

    for name, fn in (("build", cmd_build), ("update", cmd_update)):
        p = sub.add_parser(name)
        p.add_argument("--measure", default="shots_corners", choices=list(gm.MEASURES))
        p.add_argument("--fit-from", type=int, default=current_season_start() - 8,
                       help="first season year used to fit (default: last ~8 seasons)")
        p.add_argument("--out", default=WORKBOOK)
        p.add_argument("--sheets", type=int, default=20, help="number of 'Bet Angel' sheets")
        p.set_defaults(fn=fn)

    p = sub.add_parser("selections", help="write data.json for the selections web page")
    p.add_argument("--measure", default="shots_corners", choices=list(gm.MEASURES))
    p.add_argument("--fit-from", type=int, default=current_season_start() - 8)
    p.add_argument("--fixtures", default=os.path.join(HERE, "fixtures.csv"))
    p.add_argument("--json", default=os.path.join(HERE, "data.json"))
    p.add_argument("--commission", type=float, default=0.05)
    p.add_argument("--min-edge", type=float, default=0.02)
    p.add_argument("--min-odds", type=float, default=1.4)
    p.add_argument("--max-odds", type=float, default=4.0)
    p.add_argument("--no-download", action="store_true")
    p.set_defaults(fn=cmd_selections)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
