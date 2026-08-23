import sys
sys.path.insert(0, ".")
import unicodedata
from app.deps import get_db_context
from app.models import Player, PlayerSeasonStats
from sqlmodel import select

def _normalize_str(s: str) -> str:
    if not s: return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().replace("'", "").replace("’", "").replace("-", "").replace(".", "").replace(" ", "").strip()

with get_db_context() as session:
    targets = ["Nikola Jokic", "Luka Doncic", "Stephen Curry", "LeBron James", "Kawhi Leonard", "Anthony Edwards"]
    all_players = session.exec(select(Player)).all()
    stats_all = session.exec(select(PlayerSeasonStats)).all()
    stats_map = {}
    for s in stats_all:
        stats_map.setdefault(s.player_id, []).append(s)

    for target in targets:
        clean_t = _normalize_str(target)
        candidates = []
        for p in all_players:
            clean_p = _normalize_str(p.full_name)
            if clean_p == clean_t:
                candidates.append((p, 3))
            elif clean_p.startswith(clean_t) or clean_t.startswith(clean_p):
                candidates.append((p, 2))
            elif clean_t in clean_p or clean_p in clean_t:
                candidates.append((p, 1))

        candidates.sort(
            key=lambda x: (
                1 if len(stats_map.get(x[0].id, [])) > 0 else 0,
                x[1],
                len(stats_map.get(x[0].id, [])),
            ),
            reverse=True,
        )

        best = candidates[0][0] if candidates else None
        st_count = len(stats_map.get(best.id, [])) if best else 0
        clean_name = _normalize_str(best.full_name) if best else "None"
        print(f"Target: {target} -> Matched ID: {best.id if best else 'None'} ({clean_name}), Stats Count: {st_count}")
