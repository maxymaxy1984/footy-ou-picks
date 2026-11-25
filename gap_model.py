"""
GAP (Generalised Attacking Performance) ratings model for the Over/Under 2.5 goals market.

Implements: Wheatcroft, E. (2020) "A profitable model for predicting the over/under market
in football", International Journal of Forecasting 36(3), 916-932.
Open-access copy: http://eprints.lse.ac.uk/103712/

Each team carries four ratings:  Ha (home attack), Hd (home defence),
                                 Aa (away attack), Ad (away defence)
measured in units of the chosen performance measure (e.g. shots + corners).

Home team i v away team j, with measures Sh (home) and Sa (away):
    eh = Sh - (Ha_i + Ad_j)/2          (home attacking surprise)
    ea = Sa - (Aa_j + Hd_i)/2          (away attacking surprise)
    Ha_i += lam*phi1*eh      Aa_i += lam*(1-phi1)*eh
    Hd_i += lam*phi1*ea      Ad_i += lam*(1-phi1)*ea
    Aa_j += lam*phi2*ea      Ha_j += lam*(1-phi2)*ea
    Ad_j += lam*phi2*eh      Hd_j += lam*(1-phi2)*eh
    (all clipped at 0)

Forecast:  logit P(over 2.5) = alpha + beta1 * (Ha_i + Hd_i + Aa_j + Ad_j) + beta2 * r
where r = 1/(market odds on over 2.5).  The market is a regressor, so the model
"nudges" the market price rather than replacing it.
"""
from __future__ import annotations

import io
import math
import os
import urllib.request
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.optimize import minimize

# --------------------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------------------
LEAGUES = {  # football-data.co.uk division codes used in the paper
    "E0": "English Premier League", "E1": "Championship", "E2": "League One",
    "E3": "League Two", "EC": "National League", "SC0": "Scottish Premiership",
    "SP1": "La Liga", "F1": "Ligue 1", "I1": "Serie A", "D1": "Bundesliga",
}
GAMES_PER_TEAM = {"SC0": 38}  # otherwise 2*(n_teams-1)

MEASURES = {
    "goals": [("FTHG", "FTAG")],
    "shots": [("HS", "AS")],
    "sot": [("HST", "AST")],
    "corners": [("HC", "AC")],
    "shots_corners": [("HS", "AS"), ("HC", "AC")],      # best performer in the paper
    "sot_corners": [("HST", "AST"), ("HC", "AC")],
}

ODDS_COLS = {  # first column found is used
    "max_over": ["Max>2.5", "BbMx>2.5"], "max_under": ["Max<2.5", "BbMx<2.5"],
    "avg_over": ["Avg>2.5", "BbAv>2.5"], "avg_under": ["Avg<2.5", "BbAv<2.5"],
    "bfe_over": ["BFE>2.5", "BFEC>2.5"], "bfe_under": ["BFE<2.5", "BFEC<2.5"],
    "b365_over": ["B365>2.5"], "b365_under": ["B365<2.5"],
}


def season_codes(first: int, last: int) -> list[str]:
    """first=2005 -> '0506' ... last = starting year of final season."""
    return [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(first, last + 1)]


def download(data_dir: str, first_year: int, last_year: int, leagues=None, refresh_last=True):
    os.makedirs(data_dir, exist_ok=True)
    leagues = leagues or list(LEAGUES)
    seasons = season_codes(first_year, last_year)
    for s in seasons:
        for lg in leagues:
            path = os.path.join(data_dir, f"{s}_{lg}.csv")
            if os.path.exists(path) and not (refresh_last and s == seasons[-1]):
                continue
            url = f"https://www.football-data.co.uk/mmz4281/{s}/{lg}.csv"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                with open(path, "wb") as f:
                    f.write(raw)
                print(f"  got {s} {lg}")
            except Exception as e:  # season not available yet etc.
                print(f"  skip {s} {lg}: {e}")


def _first_col(df, names):
    for n in names:
        if n in df.columns:
            return pd.to_numeric(df[n], errors="coerce")
    return pd.Series(np.nan, index=df.index)


def load(data_dir: str) -> pd.DataFrame:
    frames = []
    for fn in sorted(os.listdir(data_dir)):
        if not fn.endswith(".csv") or "_" not in fn:
            continue
        season, lg = fn[:-4].split("_", 1)
        if lg not in LEAGUES:
            continue
        with open(os.path.join(data_dir, fn), "rb") as f:
            raw = f.read()
        try:
            df = pd.read_csv(io.BytesIO(raw), encoding="latin-1", on_bad_lines="skip")
        except Exception as e:
            print(f"  cannot read {fn}: {e}")
            continue
        df = df.dropna(subset=["HomeTeam", "AwayTeam"])
        if df.empty:
            continue
        out = pd.DataFrame({
            "league": lg, "season": season,
            "date": pd.to_datetime(df["Date"], dayfirst=True, errors="coerce"),
            "home": df["HomeTeam"].astype(str).str.strip(),
            "away": df["AwayTeam"].astype(str).str.strip(),
        })
        for c in ["FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC"]:
            out[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
        for k, names in ODDS_COLS.items():
            out[k] = _first_col(df, names)
        frames.append(out)
    if not frames:
        raise SystemExit(f"No data files found in {data_dir}. Run the 'download' command first.")
    d = pd.concat(frames, ignore_index=True)
    d = d.dropna(subset=["date"]).sort_values(["date", "league"], kind="stable").reset_index(drop=True)
    d["goals"] = d["FTHG"] + d["FTAG"]
    d["over"] = (d["goals"] > 2.5).astype(float)
    d.loc[d["goals"].isna(), "over"] = np.nan
    return d


def add_measure(d: pd.DataFrame, measure: str, corner_weight: float = 1.0) -> pd.DataFrame:
    d = d.copy()
    sh = np.zeros(len(d))
    sa = np.zeros(len(d))
    for k, (h, a) in enumerate(MEASURES[measure]):
        w = corner_weight if h == "HC" and len(MEASURES[measure]) > 1 else 1.0
        sh = sh + w * d[h].to_numpy(float)
        sa = sa + w * d[a].to_numpy(float)
    d["Sh"], d["Sa"] = sh, sa
    # leagues/seasons where the stat isn't recorded (e.g. some lower-league seasons) are unusable
    cov = d.assign(_ok=np.isfinite(sh) & np.isfinite(sa)).groupby(["league", "season"])["_ok"].transform("mean")
    d["measure_ok"] = (cov >= 0.8).to_numpy()
    return d


# --------------------------------------------------------------------------------------
# Ratings
# --------------------------------------------------------------------------------------
@dataclass
class LeagueState:
    ratings: dict = field(default_factory=dict)  # team -> np.array([Ha, Hd, Aa, Ad])
    season: str | None = None
    played: dict = field(default_factory=dict)
    teams_this_season: set = field(default_factory=set)
    games_per_team: int = 38


def run_ratings(d: pd.DataFrame, lam: float, phi1: float, phi2: float):
    """Walk through matches in date order. Returns pre-match feature arrays and final states.

    Features per match: R (sum of the four relevant ratings), home/away games played this
    season before the match, and games remaining for each team after it.
    """
    n = len(d)
    R = np.full(n, np.nan)
    hp = np.zeros(n, int); ap = np.zeros(n, int)
    hrem = np.zeros(n, int); arem = np.zeros(n, int)

    leagues = d["league"].tolist(); seasons = d["season"].tolist()
    homes = d["home"].tolist(); aways = d["away"].tolist()
    Sh = d["Sh"].astype(float).tolist(); Sa = d["Sa"].astype(float).tolist()

    # team lists per league-season (known in advance from the fixture list)
    teams_ls = {}
    for (lg, s), g in d.groupby(["league", "season"]):
        teams_ls[(lg, s)] = set(g["home"]) | set(g["away"])

    states: dict[str, LeagueState] = {}
    for idx in range(n):
        lg, s = leagues[idx], seasons[idx]
        st = states.get(lg)
        if st is None or st.season != s:
            new_teams = teams_ls[(lg, s)]
            if st is None:
                st = LeagueState()
                g = d[(d.league == lg) & (d.season == s)]
                mh, ma = np.nanmean(g["Sh"]), np.nanmean(g["Sa"])
                mh = 0.0 if np.isnan(mh) else mh
                ma = 0.0 if np.isnan(ma) else ma
                for t in new_teams:
                    st.ratings[t] = [mh, ma, ma, mh]
                states[lg] = st
            else:
                # promoted/relegated: newcomers get the average of the teams that left
                old = set(st.ratings)
                leavers = old - new_teams
                arrivals = new_teams - old
                if leavers:
                    avg = np.mean([st.ratings[t] for t in leavers], axis=0)
                else:
                    avg = np.mean(list(st.ratings.values()), axis=0)
                for t in arrivals:
                    st.ratings[t] = [float(v) for v in avg]
                for t in leavers:
                    del st.ratings[t]
            st.season = s
            st.played = {t: 0 for t in new_teams}
            st.games_per_team = GAMES_PER_TEAM.get(lg, 2 * (len(new_teams) - 1))

        i, j = homes[idx], aways[idx]
        ri, rj = st.ratings[i], st.ratings[j]
        R[idx] = ri[0] + ri[1] + rj[2] + rj[3]
        hp[idx], ap[idx] = st.played[i], st.played[j]
        st.played[i] += 1; st.played[j] += 1
        hrem[idx] = st.games_per_team - st.played[i]
        arem[idx] = st.games_per_team - st.played[j]

        sh, sa = Sh[idx], Sa[idx]
        if sh != sh or sa != sa:  # NaN
            continue
        eh = sh - (ri[0] + rj[3]) / 2.0
        ea = sa - (rj[2] + ri[1]) / 2.0
        ri0, ri1, ri2, ri3 = ri
        rj0, rj1, rj2, rj3 = rj
        ri[0] = max(ri0 + lam * phi1 * eh, 0.0)
        ri[2] = max(ri2 + lam * (1 - phi1) * eh, 0.0)
        ri[1] = max(ri1 + lam * phi1 * ea, 0.0)
        ri[3] = max(ri3 + lam * (1 - phi1) * ea, 0.0)
        rj[2] = max(rj2 + lam * phi2 * ea, 0.0)
        rj[0] = max(rj0 + lam * (1 - phi2) * ea, 0.0)
        rj[3] = max(rj3 + lam * phi2 * eh, 0.0)
        rj[1] = max(rj1 + lam * (1 - phi2) * eh, 0.0)

    feats = pd.DataFrame({"R": R, "home_played": hp, "away_played": ap,
                          "home_left": hrem, "away_left": arem}, index=d.index)
    return feats, states


def eligible(feats: pd.DataFrame, min_played=6, exclude_last=6) -> np.ndarray:
    """Paper: no bets until both teams have 6 league games; none in either team's last 6."""
    return ((feats["home_played"] >= min_played) & (feats["away_played"] >= min_played)
            & (feats["home_left"] >= exclude_last) & (feats["away_left"] >= exclude_last)).to_numpy()


# --------------------------------------------------------------------------------------
# Logistic regression (IRLS) and scoring
# --------------------------------------------------------------------------------------
def fit_logit(X: np.ndarray, y: np.ndarray, iters=50) -> np.ndarray:
    X1 = np.column_stack([np.ones(len(X)), X])
    b = np.zeros(X1.shape[1])
    for _ in range(iters):
        z = np.clip(X1 @ b, -30, 30)
        p = 1 / (1 + np.exp(-z))
        w = p * (1 - p) + 1e-9
        H = X1.T @ (X1 * w[:, None]) + 1e-8 * np.eye(len(b))
        step = np.linalg.solve(H, X1.T @ (y - p))
        b += step
        if np.max(np.abs(step)) < 1e-9:
            break
    return b  # alpha, beta1, beta2


def predict_logit(b, X):
    z = b[0] + X @ b[1:]
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def ignorance(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(np.mean(-np.log2(np.where(y == 1, p, 1 - p))))


def design(d, feats, odds_col="max_over"):
    r = 1.0 / d[odds_col].to_numpy(float)
    return np.column_stack([feats["R"].to_numpy(float), r])


def usable(d, feats, odds_col="max_over"):
    X = design(d, feats, odds_col)
    ok = eligible(feats) & np.isfinite(X).all(axis=1) & d["over"].notna().to_numpy()
    if "measure_ok" in d:
        ok &= d["measure_ok"].to_numpy()
    return ok


# --------------------------------------------------------------------------------------
# Parameter selection (lambda, phi1, phi2) by minimum mean ignorance
# --------------------------------------------------------------------------------------
def fit_rating_params(d, train_mask, x0=(0.3, 0.5, 0.5), odds_col="max_over", verbose=False):
    y_all = d["over"].to_numpy(float)

    def obj(theta):
        lam, p1, p2 = theta
        if not (0 < lam < 2 and 0 < p1 < 1 and 0 < p2 < 1):
            return 10.0
        feats, _ = run_ratings(d, lam, p1, p2)
        m = usable(d, feats, odds_col) & train_mask
        if m.sum() < 200:
            return 10.0
        X = design(d, feats, odds_col)[m]
        b = fit_logit(X, y_all[m])
        val = ignorance(predict_logit(b, X), y_all[m])
        if verbose:
            print(f"    lam={lam:.3f} phi1={p1:.3f} phi2={p2:.3f} ign={val:.5f}")
        return val

    res = minimize(obj, np.array(x0, float), method="Nelder-Mead",
                   options={"xatol": 5e-3, "fatol": 1e-6, "maxiter": 120})
    return tuple(float(v) for v in res.x), float(res.fun)


# --------------------------------------------------------------------------------------
# Walk-forward backtest (mirrors the paper's protocol)
# --------------------------------------------------------------------------------------
def backtest(d, measure="shots_corners", start_season=None, reg_odds="max_over",
             bet_odds=("max_over", "max_under"), commission=0.0, refit="weekly", verbose=True):
    d = add_measure(d, measure)
    seasons = sorted(d["season"].unique(), key=_season_year)
    if start_season is None:
        start_season = seasons[1]
    test_seasons = [s for s in seasons if _season_year(s) >= _season_year(start_season)]
    burn_in = seasons[0]  # first season only warms ratings up

    y = d["over"].to_numpy(float)
    rows = []
    theta = (0.3, 0.5, 0.5)
    for s in test_seasons:
        train = (d["season"].map(_season_year) < _season_year(s)).to_numpy() & (d["season"] != burn_in).to_numpy()
        if train.sum() < 500:  # need at least a season of training data
            train = (d["season"].map(_season_year) < _season_year(s)).to_numpy()
        theta, ign = fit_rating_params(d, train, x0=theta, odds_col=reg_odds)
        if verbose:
            print(f"  {s}: lam={theta[0]:.3f} phi1={theta[1]:.3f} phi2={theta[2]:.3f} (train ign {ign:.4f})")
        feats, _ = run_ratings(d, *theta)
        X = design(d, feats, reg_odds)
        ok = usable(d, feats, reg_odds)
        not_burn = (d["season"] != burn_in).to_numpy()
        test_idx = np.where((d["season"] == s).to_numpy() & ok)[0]
        if len(test_idx) == 0:
            continue
        dates = d["date"].to_numpy()
        if refit == "weekly":
            keys = pd.to_datetime(dates[test_idx]).to_period("W-SUN")
        else:
            keys = pd.Series(["season"] * len(test_idx))
        for k in pd.unique(keys):
            idx = test_idx[np.asarray(keys == k)]
            cutoff = dates[idx].min()
            tr = ok & not_burn & (dates < cutoff)
            if tr.sum() < 200:
                continue
            b = fit_logit(X[tr], y[tr])
            p = predict_logit(b, X[idx])
            for ii, pp in zip(idx, p):
                rows.append((ii, pp, *theta, *b))
    pr = pd.DataFrame(rows, columns=["i", "p_over", "lam", "phi1", "phi2", "alpha", "beta1", "beta2"]).set_index("i")
    out = d.loc[pr.index, ["league", "season", "date", "home", "away", "goals", "over",
                           "max_over", "max_under", "avg_over", "avg_under", "bfe_over", "bfe_under"]].join(pr)
    out = out.join(feats.loc[pr.index, ["R"]])
    return out, settle(out, bet_odds, commission)


def settle(pred, bet_odds=("max_over", "max_under"), commission=0.0, min_edge=0.0):
    """Value bets: back a side when p * odds > 1 (+edge). Level stakes and Kelly."""
    o_col, u_col = bet_odds
    recs = []
    for side, col, p in (("over", o_col, pred["p_over"]), ("under", u_col, 1 - pred["p_over"])):
        odds = pred[col]
        net = 1 + (odds - 1) * (1 - commission)
        ev = p * net - 1
        m = odds.notna() & (ev > min_edge)
        won = (pred["over"] == 1) if side == "over" else (pred["over"] == 0)
        b = pred.loc[m, ["league", "season", "date", "home", "away", "goals"]].copy()
        b["side"], b["odds"], b["p"], b["ev"] = side, odds[m], p[m], ev[m]
        b["won"] = won[m].astype(int)
        b["pl_level"] = np.where(b["won"] == 1, (b["odds"] - 1) * (1 - commission), -1.0)
        k = ((p[m] * net[m]) - 1) / (net[m] - 1)
        b["kelly_f"] = k.clip(lower=0)
        recs.append(b)
    bets = pd.concat(recs).sort_values("date")
    if len(bets):
        bets["kelly_stake"] = bets["kelly_f"] / bets["kelly_f"].mean()  # paper: mean stake = 1
        bets["pl_kelly"] = np.where(bets["won"] == 1, bets["kelly_stake"] * (bets["odds"] - 1) * (1 - commission),
                                    -bets["kelly_stake"])
    return bets


def summarise(bets: pd.DataFrame, by=None) -> pd.DataFrame:
    if by is None:
        g = bets.assign(_all="ALL").groupby("_all")
    else:
        g = bets.groupby(by)
    s = g.agg(bets=("pl_level", "size"), level_pl=("pl_level", "sum"), kelly_pl=("pl_kelly", "sum"),
              strike=("won", "mean"), avg_odds=("odds", "mean"))
    s["level_roi_%"] = 100 * s["level_pl"] / s["bets"]
    s["kelly_roi_%"] = 100 * s["kelly_pl"] / s["bets"]
    return s.round(3)


def _season_year(s: str) -> int:
    y = int(s[:2])
    return 1900 + y if y >= 90 else 2000 + y


# --------------------------------------------------------------------------------------
# Live model (fit on everything, produce current team ratings)
# --------------------------------------------------------------------------------------
def fit_live(d, measure="shots_corners", reg_odds="max_over", theta0=(0.3, 0.5, 0.5), verbose=True):
    d = add_measure(d, measure)
    seasons = sorted(d["season"].unique(), key=_season_year)
    train = (d["season"] != seasons[0]).to_numpy()
    theta, ign = fit_rating_params(d, train, x0=theta0, odds_col=reg_odds, verbose=False)
    feats, states = run_ratings(d, *theta)
    ok = usable(d, feats, reg_odds) & train
    X = design(d, feats, reg_odds)
    b = fit_logit(X[ok], d["over"].to_numpy(float)[ok])
    if verbose:
        print(f"  lam={theta[0]:.4f} phi1={theta[1]:.4f} phi2={theta[2]:.4f}  "
              f"alpha={b[0]:.4f} beta1={b[1]:.5f} beta2={b[2]:.4f}  (n={ok.sum()}, ign={ign:.4f})")

    team_rows = []
    cov = d.groupby(["league", "season"])["measure_ok"].first()
    for lg, st in states.items():
        if not cov.get((lg, st.season), False):
            print(f"  note: {lg} {st.season} has no {measure} data - left out of the workbook")
            continue
        for t, r in st.ratings.items():
            played = st.played.get(t, 0)
            team_rows.append({"league": lg, "league_name": LEAGUES.get(lg, lg), "season": st.season,
                              "team": t, "Ha": r[0], "Hd": r[1], "Aa": r[2], "Ad": r[3],
                              "played": played, "left": st.games_per_team - played})
    teams = pd.DataFrame(team_rows).sort_values(["league", "team"]).reset_index(drop=True)
    params = {"measure": measure, "lam": theta[0], "phi1": theta[1], "phi2": theta[2],
              "alpha": b[0], "beta1": b[1], "beta2": b[2], "n_train": int(ok.sum()),
              "last_match": str(d["date"].max().date()), "reg_odds": reg_odds}
    return params, teams


# --------------------------------------------------------------------------------------
# Upcoming selections (for the web page)
# --------------------------------------------------------------------------------------
def load_fixtures(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
    df.columns = [c.replace("﻿", "").replace("ï»¿", "").strip() for c in df.columns]
    df = df[df["Div"].isin(list(LEAGUES))].dropna(subset=["HomeTeam", "AwayTeam"])
    out = pd.DataFrame({
        "league": df["Div"], "date": pd.to_datetime(df["Date"], dayfirst=True, errors="coerce"),
        "time": df["Time"].astype(str) if "Time" in df else "",
        "home": df["HomeTeam"].astype(str).str.strip(), "away": df["AwayTeam"].astype(str).str.strip(),
    })
    for k, names in ODDS_COLS.items():
        out[k] = _first_col(df, names)
    return out.dropna(subset=["date"]).reset_index(drop=True)


def upcoming_selections(params: dict, teams: pd.DataFrame, fixtures: pd.DataFrame,
                        commission=0.05, min_edge=0.02, min_odds=1.4, max_odds=4.0, apply_6=True):
    """Model probability for each fixture; a selection where the best bookmaker price shows value.

    'back_at' is the lowest Betfair price worth taking for that side after commission and the
    minimum edge, holding the model probability fixed.
    """
    t = {(r.league, r.team): r for r in teams.itertuples(index=False)}
    rows = []
    for f in fixtures.itertuples(index=False):
        h, a = t.get((f.league, f.home)), t.get((f.league, f.away))
        if h is None or a is None:
            continue
        ref_over = f.max_over if np.isfinite(f.max_over) else f.avg_over
        if not np.isfinite(ref_over):
            continue
        elig = h.played >= 6 and a.played >= 6 and h.left > 6 and a.left > 6
        if apply_6 and not elig:
            continue
        R = h.Ha + h.Hd + a.Aa + a.Ad
        z = params["alpha"] + params["beta1"] * R + params["beta2"] / ref_over
        p_over = 1 / (1 + math.exp(-z))
        for side, p, price in (("OVER", p_over, f.max_over if np.isfinite(f.max_over) else f.avg_over),
                               ("UNDER", 1 - p_over, f.max_under if np.isfinite(f.max_under) else f.avg_under)):
            if not np.isfinite(price):
                continue
            back_at = 1 + ((1 + min_edge) / p - 1) / (1 - commission)
            edge = p * (1 + (price - 1) * (1 - commission)) - 1
            if edge >= min_edge and min_odds <= price <= max_odds:
                rows.append({
                    "league": f.league, "league_name": LEAGUES[f.league],
                    "date": f.date.strftime("%Y-%m-%d"), "time": (f.time or "")[:5],
                    "home": f.home, "away": f.away, "side": side,
                    "p": round(p, 4), "fair": round(1 / p, 2), "back_at": round(back_at, 2),
                    "price": round(float(price), 2), "edge": round(edge, 4),
                    "market_p_over": round(1 / ref_over, 4), "R": round(R, 2),
                })
    return rows


def settle_history(prev: list, results: pd.DataFrame, commission=0.05):
    """Move past selections whose result is now known into settled history."""
    res = {(r.league, r.date.strftime("%Y-%m-%d"), r.home, r.away): r
           for r in results.dropna(subset=["goals"]).itertuples(index=False)}
    settled, still_open = [], []
    for s in prev:
        r = res.get((s["league"], s["date"], s["home"], s["away"]))
        if r is None:
            still_open.append(s)
            continue
        goals = int(r.goals)
        won = (goals > 2.5) if s["side"] == "OVER" else (goals < 2.5)
        bfe = r.bfe_over if s["side"] == "OVER" else r.bfe_under
        s = dict(s, goals=goals, won=bool(won),
                 bfe=round(float(bfe), 2) if np.isfinite(bfe) else None,
                 pl=round((s["price"] - 1) * (1 - commission) if won else -1.0, 3))
        settled.append(s)
    return settled, still_open
