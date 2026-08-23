from typing import List, Dict, Any
from app.repositories.team import TeamRepository

# Official NBA 30 Franchises Metadata & Official NBA CDN IDs
OFFICIAL_NBA_30 = {
    "ATL": {"official_id": 1610612737, "full_name": "Atlanta Hawks", "city": "Atlanta", "conference": "East", "division": "Southeast"},
    "BOS": {"official_id": 1610612738, "full_name": "Boston Celtics", "city": "Boston", "conference": "East", "division": "Atlantic"},
    "BKN": {"official_id": 1610612751, "full_name": "Brooklyn Nets", "city": "Brooklyn", "conference": "East", "division": "Atlantic"},
    "CHA": {"official_id": 1610612766, "full_name": "Charlotte Hornets", "city": "Charlotte", "conference": "East", "division": "Southeast"},
    "CHI": {"official_id": 1610612741, "full_name": "Chicago Bulls", "city": "Chicago", "conference": "East", "division": "Central"},
    "CLE": {"official_id": 1610612739, "full_name": "Cleveland Cavaliers", "city": "Cleveland", "conference": "East", "division": "Central"},
    "DAL": {"official_id": 1610612742, "full_name": "Dallas Mavericks", "city": "Dallas", "conference": "West", "division": "Southwest"},
    "DEN": {"official_id": 1610612743, "full_name": "Denver Nuggets", "city": "Denver", "conference": "West", "division": "Northwest"},
    "DET": {"official_id": 1610612765, "full_name": "Detroit Pistons", "city": "Detroit", "conference": "East", "division": "Central"},
    "GSW": {"official_id": 1610612744, "full_name": "Golden State Warriors", "city": "San Francisco", "conference": "West", "division": "Pacific"},
    "HOU": {"official_id": 1610612745, "full_name": "Houston Rockets", "city": "Houston", "conference": "West", "division": "Southwest"},
    "IND": {"official_id": 1610612754, "full_name": "Indiana Pacers", "city": "Indianapolis", "conference": "East", "division": "Central"},
    "LAC": {"official_id": 1610612746, "full_name": "LA Clippers", "city": "Los Angeles", "conference": "West", "division": "Pacific"},
    "LAL": {"official_id": 1610612747, "full_name": "Los Angeles Lakers", "city": "Los Angeles", "conference": "West", "division": "Pacific"},
    "MEM": {"official_id": 1610612763, "full_name": "Memphis Grizzlies", "city": "Memphis", "conference": "West", "division": "Southwest"},
    "MIA": {"official_id": 1610612748, "full_name": "Miami Heat", "city": "Miami", "conference": "East", "division": "Southeast"},
    "MIL": {"official_id": 1610612749, "full_name": "Milwaukee Bucks", "city": "Milwaukee", "conference": "East", "division": "Central"},
    "MIN": {"official_id": 1610612750, "full_name": "Minnesota Timberwolves", "city": "Minneapolis", "conference": "West", "division": "Northwest"},
    "NOP": {"official_id": 1610612740, "full_name": "New Orleans Pelicans", "city": "New Orleans", "conference": "West", "division": "Southwest"},
    "NYK": {"official_id": 1610612752, "full_name": "New York Knicks", "city": "New York", "conference": "East", "division": "Atlantic"},
    "OKC": {"official_id": 1610612760, "full_name": "Oklahoma City Thunder", "city": "Oklahoma City", "conference": "West", "division": "Northwest"},
    "ORL": {"official_id": 1610612753, "full_name": "Orlando Magic", "city": "Orlando", "conference": "East", "division": "Southeast"},
    "PHI": {"official_id": 1610612755, "full_name": "Philadelphia 76ers", "city": "Philadelphia", "conference": "East", "division": "Atlantic"},
    "PHX": {"official_id": 1610612756, "full_name": "Phoenix Suns", "city": "Phoenix", "conference": "West", "division": "Pacific"},
    "POR": {"official_id": 1610612757, "full_name": "Portland Trail Blazers", "city": "Portland", "conference": "West", "division": "Northwest"},
    "SAC": {"official_id": 1610612758, "full_name": "Sacramento Kings", "city": "Sacramento", "conference": "West", "division": "Pacific"},
    "SAS": {"official_id": 1610612759, "full_name": "San Antonio Spurs", "city": "San Antonio", "conference": "West", "division": "Southwest"},
    "TOR": {"official_id": 1610612761, "full_name": "Toronto Raptors", "city": "Toronto", "conference": "East", "division": "Atlantic"},
    "UTA": {"official_id": 1610612762, "full_name": "Utah Jazz", "city": "Salt Lake City", "conference": "West", "division": "Northwest"},
    "WAS": {"official_id": 1610612764, "full_name": "Washington Wizards", "city": "Washington", "conference": "East", "division": "Southeast"},
}


class TeamService:
    def __init__(self, team_repo: TeamRepository):
        self.team_repo = team_repo

    def list_teams(self) -> List[Dict[str, Any]]:
        teams = self.team_repo.list()
        result = []
        seen_abbr = set()
        
        for team in teams:
            abbr = (team.abbreviation or "").upper().strip()
            if abbr in OFFICIAL_NBA_30 and abbr not in seen_abbr:
                seen_abbr.add(abbr)
                meta = OFFICIAL_NBA_30[abbr]
                player_count = len(team.player_stats) if team.player_stats else 0
                
                result.append({
                    "id": meta["official_id"],
                    "db_id": team.id,
                    "abbreviation": abbr,
                    "full_name": meta["full_name"],
                    "city": meta["city"],
                    "conference": meta["conference"],
                    "division": meta["division"],
                    "players": player_count,
                })
        
        # Sort alphabetically by full name
        return sorted(result, key=lambda x: x["full_name"])
