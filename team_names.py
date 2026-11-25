"""football-data.co.uk name -> Betfair event name.

Only names that differ are listed. Anything missing falls back to the football-data name.
Override or add your own in team_names.csv (columns: team,betfair_name) or directly in the
BetfairName column of the TEAMS sheet (your edits are kept when the workbook is rebuilt).
The Bet Angel sheets show "Home team not found: X" when a name needs adding.
"""
BETFAIR_NAMES = {
    # England
    "Man United": "Man Utd", "Nott'm Forest": "Nottm Forest", "Sheffield United": "Sheff Utd",
    "Sheffield Weds": "Sheff Wed", "Wolves": "Wolves", "Brighton": "Brighton",
    "Newcastle": "Newcastle", "West Ham": "West Ham", "Tottenham": "Tottenham",
    "Leicester": "Leicester", "Leeds": "Leeds", "QPR": "QPR", "West Brom": "West Brom",
    "Peterboro": "Peterborough", "Middlesboro": "Middlesbrough", "Bristol Rvs": "Bristol Rovers",
    "Milton Keynes Dons": "MK Dons", "Accrington": "Accrington", "Crawley Town": "Crawley Town",
    "Forest Green": "Forest Green", "Cheltenham": "Cheltenham", "Wycombe": "Wycombe",
    "Oxford": "Oxford Utd", "Cambridge": "Cambridge Utd", "Stockport": "Stockport",
    # Scotland
    "St Johnstone": "St Johnstone", "St Mirren": "St Mirren", "Dundee United": "Dundee Utd",
    # Spain
    "Ath Madrid": "Atletico Madrid", "Ath Bilbao": "Athletic Bilbao", "Sociedad": "Real Sociedad",
    "Betis": "Real Betis", "Celta": "Celta Vigo", "Vallecano": "Rayo Vallecano",
    "Espanol": "Espanyol", "La Coruna": "Deportivo", "Sp Gijon": "Sporting Gijon",
    # Germany
    "M'gladbach": "Mgladbach", "Ein Frankfurt": "Eintracht Frankfurt", "Hertha": "Hertha Berlin",
    "FC Koln": "FC Koln", "Fortuna Dusseldorf": "Fortuna Dusseldorf", "Bielefeld": "Arminia Bielefeld",
    "Greuther Furth": "Greuther Furth",
    # Italy
    "Milan": "AC Milan", "Verona": "Verona", "Spal": "Spal",
    # France
    "Paris SG": "Paris St-G", "St Etienne": "St Etienne", "Clermont": "Clermont",
}


def betfair_name(team: str, overrides: dict | None = None) -> str:
    if overrides and team in overrides:
        return overrides[team]
    return BETFAIR_NAMES.get(team, team)
