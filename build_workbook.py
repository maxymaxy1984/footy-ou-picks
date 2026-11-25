"""Build the Bet Angel Guardian Excel workbook from fitted GAP parameters and team ratings."""
from __future__ import annotations

import os

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from team_names import betfair_name

GREY = PatternFill("solid", fgColor="E7E6E6")
YELLOW = PatternFill("solid", fgColor="FFF2CC")
GREEN = PatternFill("solid", fgColor="E2EFDA")
BLUE = PatternFill("solid", fgColor="DDEBF7")
BOLD = Font(bold=True)
H1 = Font(bold=True, size=14)

# (name, label, default, help) -- user settings, preserved across rebuilds
USER_SETTINGS = [
    ("BettingOn", "Betting switched on (YES/NO)", "NO", "Master switch. Leave NO until you have checked the sheets in Guardian."),
    ("Commission", "Exchange commission", 0.05, "Your Betfair market base rate, e.g. 0.05 = 5%."),
    ("MinEdge", "Minimum edge (EV per £1, after commission)", 0.02, "0.02 = only bet when expected return is at least 2%."),
    ("MinOdds", "Minimum back odds", 1.40, ""),
    ("MaxOdds", "Maximum back odds", 4.00, ""),
    ("Sides", "Sides to bet (BOTH/OVER/UNDER)", "BOTH", ""),
    ("StakeMode", "Stake mode (LEVEL/KELLY)", "LEVEL", "The paper found Kelly beat level stakes, but with more variance."),
    ("LevelStake", "Level stake (£)", 2.0, ""),
    ("Bank", "Bank for Kelly (£)", 200.0, ""),
    ("KellyFraction", "Kelly fraction", 0.25, "0.25 = quarter Kelly."),
    ("MaxStake", "Maximum stake (£)", 10.0, ""),
    ("MinStake", "Minimum stake (£)", 1.0, "Betfair minimum; bets with a smaller stake are skipped."),
    ("ReqElig", "Apply the paper's 6-game rule (YES/NO)", "YES", "No bets until both teams have played 6 league games, and none in either team's last 6."),
    ("MinVol", "Minimum matched on market (£, 0 = off)", 0, "Reads cell C2 of the Bet Angel sheet. Check that cell holds matched volume in your Bet Angel version before using."),
]
CHOICES = {"BettingOn": "YES,NO", "Sides": "BOTH,OVER,UNDER", "StakeMode": "LEVEL,KELLY", "ReqElig": "YES,NO"}
MAX_TEAMS = 600


def _read_existing(path):
    """Keep the user's settings and Betfair-name edits from a previous build."""
    settings, names = {}, {}
    if not os.path.exists(path):
        return settings, names
    try:
        wb = load_workbook(path, data_only=False)
    except Exception:
        return settings, names
    if "SETTINGS" in wb.sheetnames:
        ws = wb["SETTINGS"]
        for row in ws.iter_rows(min_row=1, max_col=4):
            key = row[3].value if len(row) > 3 else None
            if key in {s[0] for s in USER_SETTINGS} and row[1].value is not None:
                settings[key] = row[1].value
    if "TEAMS" in wb.sheetnames:
        ws = wb["TEAMS"]
        for r in ws.iter_rows(min_row=2, max_col=3, values_only=True):
            if r[1]:
                names[(r[0], r[1])] = r[2]
    return settings, names


def _name(wb, name, ref):
    wb.defined_names[name] = DefinedName(name, attr_text=ref)


def build(path, params: dict, teams: pd.DataFrame, n_sheets=20, name_overrides=None):
    old_settings, old_names = _read_existing(path)
    wb = Workbook()

    # ---------------- README ----------------
    ws = wb.active
    ws.title = "README"
    lines = [
        ("GAP Over/Under 2.5 model for Bet Angel Guardian", H1),
        ("Model: Wheatcroft (2020), 'A profitable model for predicting the over/under market in football', Int. J. Forecasting 36(3).", None),
        (f"Performance measure: {params['measure']}.  Ratings include matches up to {params['last_match']}.", None),
        ("", None),
        ("HOW IT WORKS", BOLD),
        ("1. TEAMS holds each team's four GAP ratings (home/away attack and defence, in shots+corners).", None),
        ("2. Each 'Bet Angel' sheet reads the event name Bet Angel writes in B1, finds both teams in TEAMS,", None),
        ("   and works out P(over 2.5) = 1 / (1 + EXP(-(Alpha + Beta1*R + Beta2 / OverBackOdds))).", None),
        ("   R = home team's (home attack + home defence) + away team's (away attack + away defence).", None),
        ("3. If a side's expected value after commission beats MinEdge, column L shows BACK and Bet Angel places it", None),
        ("   at the best back price (column M) for the stake in column N.", None),
        ("", None),
        ("SETUP IN BET ANGEL", BOLD),
        ("a) Run 'python gap_ou.py update' to refresh ratings (after weekend and midweek rounds). Close this file first.", None),
        ("b) Bet Angel > Guardian: add the 'Over/Under 2.5 Goals' markets for the leagues in TEAMS.", None),
        ("c) Guardian > Excel tab: browse to this workbook, open it, tick Connect and Auto-bind Bet Angel sheets.", None),
        ("   One market per 'Bet Angel' sheet (there are 20). Use Guardian's refresh restriction so markets only", None),
        ("   refresh in the window before kick-off you want to bet in (e.g. last 30 minutes).", None),
        ("d) Check column BA/BB on each sheet: it says 'Model live' or why a market is skipped (e.g. team not found).", None),
        ("e) Only then set SETTINGS > BettingOn to YES. Test with minimum stakes or Bet Angel practice mode first.", None),
        ("", None),
        ("NOTES", BOLD),
        ("- Bet Angel will not fire a trigger while the status cell (column O) is filled. If you reuse a sheet for", None),
        ("  a new market, clear O9 and O11 (or import ClearStatus.bas, included).", None),
        ("- If B1 in your Bet Angel version doesn't hold the event name, change cell BB1 on each Bet Angel sheet.", None),
        ("- Team names: edit TEAMS column C (BetfairName) so it matches the Betfair event name. Edits survive rebuilds.", None),
        ("- The paper's edge was about 0.8% per bet at best bookmaker prices. Exchange commission eats into that:", None),
        ("  backtest with 'python gap_ou.py backtest --odds bfe' before staking real money.", None),
    ]
    for i, (t, f) in enumerate(lines, 1):
        c = ws.cell(i, 1, t)
        if f:
            c.font = f
    ws.column_dimensions["A"].width = 120

    # ---------------- SETTINGS ----------------
    ws = wb.create_sheet("SETTINGS")
    ws["A1"], ws["A1"].font = "Model parameters (written by gap_ou.py - do not edit)", BOLD
    model_rows = [("Alpha", "alpha"), ("Beta1", "beta1"), ("Beta2", "beta2"),
                  ("Lambda", "lam"), ("Phi1", "phi1"), ("Phi2", "phi2")]
    r = 2
    for nm, key in model_rows:
        ws.cell(r, 1, nm); c = ws.cell(r, 2, float(params[key])); c.fill = GREY
        ws.cell(r, 4, nm)
        _name(wb, nm, f"SETTINGS!$B${r}")
        r += 1
    ws.cell(r, 1, "Measure"); ws.cell(r, 2, params["measure"]).fill = GREY; r += 1
    ws.cell(r, 1, "Ratings up to"); ws.cell(r, 2, params["last_match"]).fill = GREY; r += 1
    ws.cell(r, 1, "Training matches"); ws.cell(r, 2, params["n_train"]).fill = GREY; r += 2

    ws.cell(r, 1, "Your settings (kept when the workbook is rebuilt)").font = BOLD; r += 1
    for key, label, default, help_ in USER_SETTINGS:
        ws.cell(r, 1, label)
        c = ws.cell(r, 2, old_settings.get(key, default)); c.fill = YELLOW
        ws.cell(r, 3, help_).alignment = Alignment(wrap_text=False)
        ws.cell(r, 4, key).font = Font(color="999999")
        _name(wb, key, f"SETTINGS!$B${r}")
        if key in CHOICES:
            dv = DataValidation(type="list", formula1=f'"{CHOICES[key]}"', allow_blank=False)
            ws.add_data_validation(dv); dv.add(c)
        r += 1
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 90
    ws.column_dimensions["D"].width = 14

    # ---------------- TEAMS ----------------
    ws = wb.create_sheet("TEAMS")
    hdr = ["League", "Team (football-data)", "BetfairName", "HomeAttack", "HomeDefence", "AwayAttack",
           "AwayDefence", "Played", "Left", "Eligible", "Season"]
    for j, h in enumerate(hdr, 1):
        ws.cell(1, j, h).font = BOLD
    overrides = name_overrides or {}
    for i, t in enumerate(teams.itertuples(index=False), 2):
        bf = old_names.get((t.league, t.team)) or betfair_name(t.team, overrides)
        vals = [t.league, t.team, bf, round(t.Ha, 4), round(t.Hd, 4), round(t.Aa, 4), round(t.Ad, 4),
                int(t.played), int(t.left), f"=AND(H{i}>=6,I{i}>=6)", t.season]
        for j, v in enumerate(vals, 1):
            c = ws.cell(i, j, v)
            if j == 3:
                c.fill = YELLOW
    ws.freeze_panes = "A2"
    for col, w in zip("ABCDEFGHIJK", [8, 24, 24, 12, 12, 12, 12, 8, 8, 9, 8]):
        ws.column_dimensions[col].width = w
    last = MAX_TEAMS + 1
    for nm, col in [("T_BF", "C"), ("T_HA", "D"), ("T_HD", "E"), ("T_AA", "F"), ("T_AD", "G"), ("T_ELIG", "J")]:
        _name(wb, nm, f"TEAMS!${col}$2:${col}${last}")

    # ---------------- CALCULATOR (manual check, like the video's spreadsheet) ----------------
    ws = wb.create_sheet("CALCULATOR")
    ws["A1"], ws["A1"].font = "Manual match calculator", H1
    rows = [
        ("Home team (BetfairName)", None, YELLOW), ("Away team (BetfairName)", None, YELLOW),
        ("Over 2.5 odds (decimal)", 2.0, YELLOW), ("Under 2.5 odds (decimal)", 1.9, YELLOW),
        ("Home attacking pressure (HomeAttack)", "=INDEX(T_HA,MATCH(B3,T_BF,0))", GREY),
        ("Home defensive pressure (HomeDefence)", "=INDEX(T_HD,MATCH(B3,T_BF,0))", GREY),
        ("Away attacking pressure (AwayAttack)", "=INDEX(T_AA,MATCH(B4,T_BF,0))", GREY),
        ("Away defensive pressure (AwayDefence)", "=INDEX(T_AD,MATCH(B4,T_BF,0))", GREY),
        ("Expected home pressure", "=(B7+B10)/2", GREY),
        ("Expected away pressure", "=(B9+B8)/2", GREY),
        ("Total match pressure R", "=B7+B8+B9+B10", GREY),
        ("Market implied P(over) = 1/odds", "=1/B5", GREY),
        ("Model P(over 2.5)", "=1/(1+EXP(-(Alpha+Beta1*B13+Beta2*B14)))", GREEN),
        ("Model P(under 2.5)", "=1-B15", GREEN),
        ("Fair odds over", "=1/B15", GREEN), ("Fair odds under", "=1/B16", GREEN),
        ("EV over per £1 (after commission)", "=B15*(1+(B5-1)*(1-Commission))-1", GREEN),
        ("EV under per £1 (after commission)", "=B16*(1+(B6-1)*(1-Commission))-1", GREEN),
        ("Verdict", '=IF(B19>=MinEdge,"BACK OVER",IF(B20>=MinEdge,"BACK UNDER","No bet"))', GREEN),
    ]
    for i, (lab, val, fill) in enumerate(rows, 3):
        ws.cell(i, 1, lab)
        c = ws.cell(i, 2, val)
        c.fill = fill
        if i >= 15 and i <= 16:
            c.number_format = "0.0%"
        if i in (19, 20):
            c.number_format = "0.0%"
        if i in (17, 18):
            c.number_format = "0.00"
    for i in (7, 8, 9, 10, 11, 12, 13):
        ws.cell(i, 2).number_format = "0.00"
    ws.cell(14, 2).number_format = "0.0%"
    if len(teams):
        first = teams.iloc[0]
        ws["B3"] = betfair_name(first.team, overrides)
        ws["B4"] = betfair_name(teams.iloc[1].team, overrides) if len(teams) > 1 else ws["B3"].value
    dv = DataValidation(type="list", formula1=f"=TEAMS!$C$2:$C${len(teams) + 1}", allow_blank=True)
    ws.add_data_validation(dv); dv.add("B3"); dv.add("B4")
    ws.column_dimensions["A"].width = 40
    ws.column_dimensions["B"].width = 22

    # ---------------- Bet Angel sheets ----------------
    for k in range(1, n_sheets + 1):
        ws = wb.create_sheet("Bet Angel" if k == 1 else f"Bet Angel {k}")
        _bet_angel_sheet(ws)

    wb.save(path)
    return path


def _bet_angel_sheet(ws):
    ws["L7"], ws["M7"], ws["N7"] = "Trigger", "Odds", "Stake"
    for c in ("L7", "M7", "N7"):
        ws[c].font = BOLD
    helpers = [
        ("Event text (from B1)", "=$B$1"),
        ("Home team", '=IFERROR(TRIM(RIGHT(SUBSTITUTE(SUBSTITUTE(LEFT(BB1,FIND(" v ",BB1)-1)," - ","/"),"/",REPT(" ",100)),100)),"")'),
        ("Away team", '=IFERROR(TRIM(LEFT(MID(BB1,FIND(" v ",BB1)+3,200),MIN(FIND(" - ",MID(BB1,FIND(" v ",BB1)+3,200)&" - "),FIND("/",MID(BB1,FIND(" v ",BB1)+3,200)&"/"))-1)),"")'),
        ("Home row in TEAMS", '=IFERROR(MATCH(BB2,T_BF,0),"")'),
        ("Away row in TEAMS", '=IFERROR(MATCH(BB3,T_BF,0),"")'),
        ("Match pressure R", '=IFERROR(INDEX(T_HA,BB4)+INDEX(T_HD,BB4)+INDEX(T_AA,BB5)+INDEX(T_AD,BB5),"")'),
        ("Eligible (6-game rule)", '=IFERROR(IF(ReqElig="YES",AND(INDEX(T_ELIG,BB4),INDEX(T_ELIG,BB5)),TRUE),FALSE)'),
        ("Over 2.5 best back", '=IFERROR(IF(ISNUMBER(SEARCH("Over",B9)),G9,IF(ISNUMBER(SEARCH("Over",B11)),G11,"")),"")'),
        ("Model P(over 2.5)", '=IFERROR(1/(1+EXP(-(Alpha+Beta1*BB6+Beta2/BB8))),"")'),
        ("Market OK (pre-play, volume)", '=AND(TRIM(G1&"")="",OR(MinVol=0,N(C2)>=MinVol))'),
        ("Status", '=IF(BB2="","No event parsed from BB1",IF(BB4="","Home team not found: "&BB2,IF(BB5="","Away team not found: "&BB3,IF(NOT(BB7),"Skipped: 6-game rule",IF(BB9="","Waiting for prices",IF(NOT(BB10),"Market in play/suspended or too thin","Model live"))))))'),
    ]
    for i, (lab, f) in enumerate(helpers, 1):
        ws.cell(i, 53, lab).font = BOLD       # BA
        c = ws.cell(i, 54, f); c.fill = BLUE  # BB
    ws["BB9"].number_format = "0.0%"
    ws["BB6"].number_format = "0.00"
    ws["BB1"].comment = Comment("Bet Angel writes the event/market name into B1. If your version uses another cell, point this at it.", "GAP")

    ws["BD7"], ws["BE7"], ws["BF7"], ws["BG7"], ws["BH7"] = "Model P", "EV/£1", "Fair odds", "Kelly f", "Side"
    for c in ("BD7", "BE7", "BF7", "BG7", "BH7"):
        ws[c].font = BOLD
    for r in (9, 11):
        ws[f"BH{r}"] = f'=IF(ISNUMBER(SEARCH("Over",B{r})),"OVER",IF(ISNUMBER(SEARCH("Under",B{r})),"UNDER",""))'
        ws[f"BD{r}"] = f'=IFERROR(IF(BH{r}="OVER",$BB$9,IF(BH{r}="UNDER",1-$BB$9,"")),"")'
        ws[f"BE{r}"] = f'=IFERROR(BD{r}*(1+(G{r}-1)*(1-Commission))-1,"")'
        ws[f"BF{r}"] = f'=IFERROR(1/BD{r},"")'
        ws[f"BG{r}"] = f'=IFERROR(MAX(0,BE{r}/((G{r}-1)*(1-Commission))),0)'
        ws[f"N{r}"] = f'=IFERROR(IF(StakeMode="KELLY",MIN(MaxStake,ROUND(Bank*KellyFraction*BG{r},2)),LevelStake),0)'
        ws[f"M{r}"] = f'=IF(ISNUMBER(G{r}),G{r},"")'
        ws[f"L{r}"] = (f'=IFERROR(IF(AND(BettingOn="YES",$BB$10,$BB$7,ISNUMBER(BD{r}),ISNUMBER(G{r}),'
                       f'G{r}>=MinOdds,G{r}<=MaxOdds,BE{r}>=MinEdge,N{r}>=MinStake,O{r}="",'
                       f'OR(Sides="BOTH",Sides=BH{r})),"BACK",""),"")')
        for c in (f"BD{r}", f"BE{r}"):
            ws[c].number_format = "0.0%"
        ws[f"BF{r}"].number_format = "0.00"
        for c in (f"L{r}", f"M{r}", f"N{r}"):
            ws[c].fill = GREEN
    ws.column_dimensions["BA"].width = 30
    ws.column_dimensions["BB"].width = 34
