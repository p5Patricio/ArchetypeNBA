from app.services.gemini_analyzer import GeminiAnalyzerService
from app.services.injury_scraper import InjuryItem


def test_gemini_analyzer_heuristics():
    analyzer = GeminiAnalyzerService(api_key="")
    assert not analyzer.is_configured

    sample_injuries = [
        InjuryItem(
            game_date="2026-09-08",
            matchup="DAL @ BOS",
            team="Dallas Mavericks",
            player_name="Luka Doncic",
            status="Out",
            reason="Knee sprain",
        ),
        InjuryItem(
            game_date="2026-09-08",
            matchup="LAL @ GSW",
            team="Los Angeles Lakers",
            player_name="LeBron James",
            status="Questionable",
            reason="Ankle sore",
        ),
    ]

    result = analyzer.analyze_injuries_and_news(sample_injuries)
    assert len(result.modifiers) == 2

    luka_mod = next(m for m in result.modifiers if m.player_name == "Luka Doncic")
    assert luka_mod.status == "OUT"
    assert luka_mod.minute_multiplier == 0.0
    assert luka_mod.risk_level == "EXTREME"

    lebron_mod = next(m for m in result.modifiers if m.player_name == "LeBron James")
    assert lebron_mod.status == "QUESTIONABLE"
    assert lebron_mod.minute_multiplier < 1.0
