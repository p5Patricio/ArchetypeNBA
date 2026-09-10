from app.services.injury_scraper import InjuryScraperService


def test_injury_scraper_fallback():
    scraper = InjuryScraperService()
    items = scraper._get_fallback_sample_report()
    assert len(items) >= 3
    for item in items:
        assert item.player_name
        assert item.team
        assert item.status


def test_injury_scraper_html_parsing():
    scraper = InjuryScraperService()
    sample_html = """
    <table>
      <tr>
        <td>2026-09-08</td>
        <td>BOS @ MIA</td>
        <td>Miami Heat</td>
        <td>Jimmy Butler</td>
        <td>Questionable</td>
        <td>Right ankle sprain</td>
      </tr>
    </table>
    """
    items = scraper._parse_html_report(sample_html)
    assert len(items) == 1
    assert items[0].player_name == "Jimmy Butler"
    assert items[0].team == "Miami Heat"
    assert items[0].status == "Questionable"
