from sqlmodel import Session, select
from app.deps import engine
from app.models import Player, PlayerSeasonStats, PlayerAdvancedStats, Season, Team


def seed_bulls_1996():
    with Session(engine) as session:
        s96 = session.exec(select(Season).where(Season.season_label == "1995-96")).first()
        if not s96:
            s96 = Season(season_label="1995-96", is_active=False)
            session.add(s96)
            session.commit()
            session.refresh(s96)

        chi = session.exec(select(Team).where(Team.abbreviation == "CHI")).first()
        if not chi:
            raise ValueError("Team CHI not found in DB")

        players_data = [
            {
                "id": 166,
                "name": "Ron Harper",
                "pos": "G",
                "height": 198,
                "weight": 98,
                "stats": {
                    "gp": 80, "min": 1888.0, "pts": 592.0, "reb": 216.0, "ast": 208.0,
                    "stl": 104.0, "blk": 32.0, "fgm": 236.0, "fga": 505.0, "fg_pct": 0.467,
                    "fg3m": 36.0, "fg3a": 134.0, "fg3_pct": 0.269, "ftm": 84.0, "fta": 119.0, "ft_pct": 0.705,
                    "oreb": 72.0, "dreb": 144.0, "tov": 79.0, "pf": 172.0, "cluster_id": 3
                },
                "adv": {"per": 13.5, "bpm": 1.5, "ts_pct": 0.526, "usg_pct": 0.154, "ws": 5.6, "ws_per_48": 0.142}
            },
            {
                "id": 937,
                "name": "Scottie Pippen",
                "pos": "F",
                "height": 203,
                "weight": 103,
                "stats": {
                    "gp": 77, "min": 2825.0, "pts": 1496.0, "reb": 496.0, "ast": 452.0,
                    "stl": 133.0, "blk": 57.0, "fgm": 565.0, "fga": 1220.0, "fg_pct": 0.463,
                    "fg3m": 150.0, "fg3a": 401.0, "fg3_pct": 0.374, "ftm": 216.0, "fta": 318.0, "ft_pct": 0.679,
                    "oreb": 157.0, "dreb": 339.0, "tov": 206.0, "pf": 206.0, "cluster_id": 4
                },
                "adv": {"per": 21.0, "bpm": 6.9, "ts_pct": 0.551, "usg_pct": 0.251, "ws": 12.3, "ws_per_48": 0.209}
            },
            {
                "id": 23,
                "name": "Dennis Rodman",
                "pos": "F",
                "height": 201,
                "weight": 100,
                "stats": {
                    "gp": 64, "min": 2088.0, "pts": 352.0, "reb": 952.0, "ast": 161.0,
                    "stl": 28.0, "blk": 28.0, "fgm": 137.0, "fga": 285.0, "fg_pct": 0.480,
                    "fg3m": 1.0, "fg3a": 9.0, "fg3_pct": 0.111, "ftm": 77.0, "fta": 146.0, "ft_pct": 0.528,
                    "oreb": 356.0, "dreb": 596.0, "tov": 138.0, "pf": 203.0, "cluster_id": 0
                },
                "adv": {"per": 14.1, "bpm": 2.1, "ts_pct": 0.505, "usg_pct": 0.104, "ws": 6.2, "ws_per_48": 0.143}
            },
            {
                "id": 26,
                "name": "Luc Longley",
                "pos": "C",
                "height": 218,
                "weight": 120,
                "stats": {
                    "gp": 62, "min": 1643.0, "pts": 564.0, "reb": 316.0, "ast": 118.0,
                    "stl": 25.0, "blk": 87.0, "fgm": 242.0, "fga": 502.0, "fg_pct": 0.482,
                    "fg3m": 0.0, "fg3a": 0.0, "fg3_pct": 0.0, "ftm": 80.0, "fta": 103.0, "ft_pct": 0.777,
                    "oreb": 104.0, "dreb": 212.0, "tov": 109.0, "pf": 226.0, "cluster_id": 2
                },
                "adv": {"per": 13.9, "bpm": 0.8, "ts_pct": 0.518, "usg_pct": 0.182, "ws": 3.5, "ws_per_48": 0.102}
            },
            {
                "id": 389,
                "name": "Toni Kukoc",
                "pos": "F",
                "height": 208,
                "weight": 87,
                "stats": {
                    "gp": 81, "min": 2106.0, "pts": 1061.0, "reb": 324.0, "ast": 283.0,
                    "stl": 65.0, "blk": 24.0, "fgm": 382.0, "fga": 780.0, "fg_pct": 0.490,
                    "fg3m": 92.0, "fg3a": 228.0, "fg3_pct": 0.403, "ftm": 205.0, "fta": 265.0, "ft_pct": 0.772,
                    "oreb": 112.0, "dreb": 212.0, "tov": 158.0, "pf": 178.0, "cluster_id": 4
                },
                "adv": {"per": 19.3, "bpm": 4.8, "ts_pct": 0.589, "usg_pct": 0.228, "ws": 8.8, "ws_per_48": 0.201}
            },
            {
                "id": 70,
                "name": "Steve Kerr",
                "pos": "G",
                "height": 190,
                "weight": 79,
                "stats": {
                    "gp": 82, "min": 1919.0, "pts": 688.0, "reb": 106.0, "ast": 188.0,
                    "stl": 66.0, "blk": 1.0, "fgm": 244.0, "fga": 482.0, "fg_pct": 0.506,
                    "fg3m": 122.0, "fg3a": 237.0, "fg3_pct": 0.515, "ftm": 78.0, "fta": 84.0, "ft_pct": 0.929,
                    "oreb": 27.0, "dreb": 79.0, "tov": 85.0, "pf": 110.0, "cluster_id": 1
                },
                "adv": {"per": 14.7, "bpm": 2.2, "ts_pct": 0.663, "usg_pct": 0.141, "ws": 8.3, "ws_per_48": 0.207}
            },
        ]

        for pdata in players_data:
            p = session.exec(select(Player).where(Player.id == pdata["id"])).first()
            if not p:
                p = Player(
                    id=pdata["id"],
                    full_name=pdata["name"],
                    position=pdata["pos"],
                    height_cm=pdata["height"],
                    weight_kg=pdata["weight"],
                    headshot_url=f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pdata['id']}.png",
                )
                session.add(p)
                session.commit()
                session.refresh(p)
            else:
                p.position = pdata["pos"]
                p.height_cm = pdata["height"]
                p.weight_kg = pdata["weight"]
                if not p.headshot_url:
                    p.headshot_url = f"https://cdn.nba.com/headshots/nba/latest/1040x760/{pdata['id']}.png"
                session.add(p)
                session.commit()

            # Upsert 1995-96 stats
            stat = session.exec(
                select(PlayerSeasonStats).where(
                    PlayerSeasonStats.player_id == p.id,
                    PlayerSeasonStats.season_id == s96.id,
                )
            ).first()
            if not stat:
                stat = PlayerSeasonStats(
                    player_id=p.id,
                    team_id=chi.id,
                    season_id=s96.id,
                    **pdata["stats"],
                )
                session.add(stat)
            else:
                for k, v in pdata["stats"].items():
                    setattr(stat, k, v)
                session.add(stat)
            session.commit()

            # Upsert 1995-96 advanced stats
            adv = session.exec(
                select(PlayerAdvancedStats).where(
                    PlayerAdvancedStats.player_id == p.id,
                    PlayerAdvancedStats.season_id == s96.id,
                )
            ).first()
            if not adv:
                adv = PlayerAdvancedStats(
                    player_id=p.id,
                    season_id=s96.id,
                    **pdata["adv"],
                )
                session.add(adv)
            else:
                for k, v in pdata["adv"].items():
                    setattr(adv, k, v)
                session.add(adv)
            session.commit()

        print("Successfully seeded 1995-96 Chicago Bulls players into PostgreSQL!")


if __name__ == "__main__":
    seed_bulls_1996()
