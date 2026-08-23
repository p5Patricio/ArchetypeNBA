import urllib.request
import urllib.parse
import json
import unicodedata

def _normalize_str(s: str) -> str:
    if not s: return ""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower().replace("'", "").replace("’", "").replace("-", "").replace(".", "").replace(" ", "").strip()

base_url = "http://127.0.0.1:8000/api/v1"


test_cases = [
    ("Stephen Curry", None),
    ("Nikola Jokic", None),
    ("LeBron James", None),
    ("Kawhi Leonard", None),
    ("Anthony Edwards", None),
    ("Giannis Antetokounmpo", None),
    ("Luka Doncic", None),
    ("Michael Jordan", None),
    ("Kobe Bryant", None),
    ("Shaquille O'Neal", None),
    ("Victor Wembanyama", None),
]

print("=== VERIFYING TRAINING CAMP ENDPOINTS WITH LIVE FASTAPI BACKEND ===")

for name, season_id in test_cases:
    params = {"player_name": name}
    if season_id:
        params["season_id"] = season_id
    
    url = f"{base_url}/training/analyze?{urllib.parse.urlencode(params)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            p_name = _normalize_str(data["player_name"])
            pos = f"{data['position']} ({data['position_group']})"
            grade = f"{data['role_fulfillment']['letter_grade']} ({data['role_fulfillment']['overall_score']} pts)"
            peers = data["total_position_peers"]
            drills_count = len(data["recommended_drills"])
            regimes_count = len(data["training_regimes"])
            gaps_count = len(data["stat_gaps"])
            print(f"[OK] {name:<22} -> Match: {p_name:<20} | Pos: {pos:<14} | Grade: {grade:<12} | Peers: {peers} | Drills: {drills_count} | Regimes: {regimes_count} | Gaps: {gaps_count}")

    except Exception as e:
        print(f"[FAIL] {name:<20} -> Error: {e}")

print("\n=== VERIFYING DRILLS CATALOG ENDPOINT ===")
try:
    drills_url = f"{base_url}/training/drills"
    req = urllib.request.Request(drills_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as resp:
        catalog = json.loads(resp.read().decode("utf-8"))
        print(f"[OK] Catalog returned {len(catalog)} professional tactical drills.")
        for d in catalog[:4]:
            print(f"  - [{d['category'].upper()}] {d['name_es']} (Target: {d['stat_target']}, Intensity: {d['intensity']})")
except Exception as e:
    print(f"[FAIL] Drills catalog -> Error: {e}")
