# Footy O/U 2.5 picks

This repo publishes Over/Under 2.5 goals selections from the GAP ratings model in Wheatcroft (2020), "A profitable model for predicting the over/under market in football", *International Journal of Forecasting* 36(3). The paper is open access at http://eprints.lse.ac.uk/103712/.

## How it runs

- A GitHub Action (`.github/workflows/picks.yml`) runs every **Tuesday and Friday**. You can also start it any time with **Actions → Update O/U 2.5 picks → Run workflow**.
- Each run downloads results and fixtures from football-data.co.uk, refits the model and writes `docs/data.json`.
- GitHub Pages serves `docs/` as the picks page. It shows upcoming picks, the "back at" price and a running record of settled picks.

## One-time setup

1. **Settings → Pages:** set the source to *Deploy from a branch*, branch `main`, folder `/docs`.
2. **Actions tab:** enable workflows if GitHub asks you to, then press **Run workflow** once.
   - The first run downloads about 8 seasons of data and takes a few minutes.
   - The page then lives at `https://<your-user>.github.io/footy-ou-picks/`.

## Settings

Defaults: 5% commission, 2% minimum edge, odds 1.40–4.00, and the paper's 10 leagues.

To change them, edit the `selections` line in the workflow:

```
python gap_ou.py selections --json docs/data.json --min-edge 0.03 --max-odds 3.5
```

Add `--leagues E0 E1 SP1 D1` to pick leagues.

## Bet Angel and backtests

The same code also builds the Bet Angel Guardian workbook and runs backtests:

```
python gap_ou.py download
python gap_ou.py backtest --odds bfe
python gap_ou.py build
```

Not betting advice. The paper's edge was about 0.8% per bet at the best bookmaker prices, so judge it by the record on the page.
