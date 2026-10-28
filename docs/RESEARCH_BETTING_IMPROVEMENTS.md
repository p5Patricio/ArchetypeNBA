# Research: how to improve the betting side of ArchetypeNBA

Date: 2026-10-28. Method: six web-research sub-questions fanned out to Antigravity (Gemini) as a cheap search worker; every load-bearing claim was then re-checked by Claude against a registry (Crossref, arXiv), a primary page read directly, a second independent domain, or this project's own database. **Gemini's raw output was not trusted**: of the 21 DOIs it cited, 11 did not resolve to the paper it named (7 resolve to an unrelated paper, 4 do not exist) and several numeric claims have no source. Section 5 lists what was rejected. Everything marked *unverified* is a lead, not a fact.

## 1. Executive summary

1. **The honest baseline expectation stays the same.** A model built on public box-score data does not beat the de-vigged Pinnacle close. Our own data agrees: champion Brier 0.2495 vs Pinnacle's close 0.2013 on 30 games (the 0.20 level of the close also matches Gemini's figure, so that one is corroborated). Gains must come from information the market has and we lack (injuries, lineups), or from price differences between books, not from tuning Elo.
2. **The cheapest real improvement is measurement, not modelling.** CLV has a standard deviation of 5.96% per bet in our data (n = 40). Detecting a true +1% mean CLV needs about 220 independent bets, +2% about 55; detecting a true +2% ROI needs about 15,000 bets. ROI cannot judge this system for years; CLV against **Pinnacle's** close and Brier can.
3. **The current "CLV +4.1%, t = 4.35" is not evidence of an edge.** It is same-book CLV (often a soft book), over 40 bets of which the flat and the Kelly strategy bet largely the same selections (not independent), and bets whose line moved are dropped (survivorship). The project documents these biases already; the fix is in section 3, item 1.
4. **Kelly should shrink with model uncertainty** (Baker and McHale), not use a fixed quarter. Flat staking stays the right instrument for validating the model.
5. **Injuries and lineups remain the first modelling item** (ROADMAP 1), but the legal question is not settled by what was found: see section 4.

## 2. Verified evidence

| # | Finding | How it was verified |
|---|---------|---------------------|
| E1 | Standard Kelly with an estimated probability over-bets; Baker and McHale derive a shrinkage of the stake for parameter uncertainty and show it beats raw Kelly in simulation and in tennis data. *Decision Analysis* 10(3), 189-199, 2013, DOI 10.1287/deca.2013.0271 | Crossref (title, author, year) plus abstract on INFORMS, RePEc and the Salford repository (3 domains) |
| E2 | Hubáček, Šourek and Železný (2019): a model that is penalised for agreeing with the bookmaker odds ("decorrelated"), combined with portfolio-theory bet sizing, produced positive cumulative profit on NBA data 2007-2014, while the alternatives tested did not do so consistently. *Int. J. Forecasting* 35(2), 783-796, DOI 10.1016/j.ijforecast.2019.01.001 | Crossref + abstract on RePEc and the CVUT repository (note: Gemini's DOI for this paper was wrong) |
| E3 | Rest effect exists but is modest: the home team does worse against the spread on the second night of a back-to-back when the visitor is rested (Ashman, Bowman and Lambrinos, *J. Sports Economics* 11(6), 602-613, 2010); a regression on 2003-2010 data puts the back-to-back penalty near 1.25 points (blog, weaker source) | RePEc record + one secondary source. **Already in the model**: `rest_*` and `b2b_*` are challenger features |
| E4 | Risk-constrained Kelly (bound on drawdown probability) exists as a convex program: Busseti, Ryu and Boyd, 2016, DOI 10.3905/joi.2016.25.3.118, arXiv 1603.06183 | Crossref and arXiv both return this title and authors; the algorithmic details come from Gemini's summary and were not re-read |
| E5 | Methods for the evaluation protocol exist and are citable: Wald SPRT (1945); White's Reality Check (2000); Hansen's SPA test (2005); Bailey and López de Prado's Deflated Sharpe Ratio (2014); Diebold-Mariano (1995) with the Harvey-Leybourne-Newbold small-sample correction (1997); anytime-valid "safe testing" with e-values (Grünwald et al., JRSS-B, 2024) | Crossref returns matching title, authors and year for each DOI. These are standard results; the descriptions were not re-read from the papers |
| E6 | Whitrow (2007), *JRSS-C*, on allocating stakes across many simultaneous bets; Jacot et al. (2023, *J. Quant. Anal. Sports*) on Kelly for non-mutually-exclusive bets | Whitrow's real DOI is 10.1111/j.1467-9876.2007.00594.x (Gemini's was wrong); Jacot found by title search in Crossref. Content not re-read |
| E7 | The official NBA injury page (2026-27) lists timestamped PDFs under `ak-static.cms.nba.com/referee/injury/`, states "Reports are updated on a continual basis", deadlines of 5 p.m. local the day before and 11 a.m.-1 p.m. local on game day, and carries the notice "No portion of NBA.com may be duplicated, redistributed or manipulated in any form" | Read directly from official.nba.com (the file name pattern is `Injury-Report_YYYY-MM-DD_HH_MMAM.pdf`, not `HHMM` as Gemini wrote) |
| E8 | `balldontlie`: free tier is 5 requests/minute, 1 sport, "Basic" data; paid tiers $9.99 (60 req/min), $39.99, $299.99 | Read directly from balldontlie.io. Which endpoints (injuries, lineups, odds) belong to which tier is **not stated** on the page |
| E9 | `nba_api` live `boxscore` returns, per player, `starter`, `status`, `notPlayingReason` and `notPlayingDescription` | Read directly from the project's docs. When these fields are filled before tip-off is **not stated** |
| E10 | In our database: Pinnacle's de-vigged close has Brier 0.2013 (30 games); CLV sd 5.96% (40 bets); flat and Kelly strategies largely duplicate selections | Own data (`paper_report.py` and a query on `simulated_bet`) |

## 3. Recommendations for the betting system

Ordered by value for effort. Each says which evidence supports it and how to know it worked.

1. **Report CLV against Pinnacle's close, per game, in log-odds.** Today CLV compares with the same book's close, which is often a soft book. Add a second CLV column against Pinnacle's de-vigged close (the sharp reference the project already stores), and test it with a one-sample t-test on log(price taken / fair closing price), **clustered by game** (flat and Kelly bet the same game, so they must count once). Support: E10 plus the project's own documented biases. Done when `paper_report.py` prints the Pinnacle-CLV mean, its standard error, the number of independent games and the sample needed for +1%. Small, no schema change.
2. **Add a market-only benchmark arm.** Paper-trade a strategy with no model: bet when the best soft-book price beats Pinnacle's de-vigged probability by a margin. This separates "the model has skill" from "line shopping pays", which the current blended policy mixes. It is the strategy that the decorrelation result (E2) points towards: use the market as the base, bet only on what the model adds. Registered as a new `model_version` (rule 8), shadow only. Done when the league report compares it with the champion on CLV vs Pinnacle.
3. **Shrink the Kelly fraction with model uncertainty.** Replace the fixed quarter-Kelly with a fraction that falls as the model disagrees with Pinnacle or as the model's recorded sample is small (E1). Keep flat 1 u as the validation strategy. Keep the existing caps (2% per bet, 10% per day, 4% per game); E6 and E4 are the references if a correlated-bets or drawdown-constrained version is wanted later. Registered as a new strategy so the old bankroll stays comparable.
4. **Control for multiple comparisons in the candidate lab.** The lab picks the best of 40 Elo configurations plus `margin_features`; the hold-out gate is a single threshold. A Reality-Check or SPA test over the candidates (E5) turns "passed the gate" into a statement about selection bias. For promotion, the Diebold-Mariano test with the HLN correction is the right paired comparison for small n; e-values (E5) are an alternative to the current look budget, not an obvious improvement, so keep the look budget unless it proves too conservative.
5. **Injuries and lineups (ROADMAP 1) remain the main modelling gain.** Rest and back-to-back are already features (E3), so schedule density is not the missing piece; player availability is. Travel distance is not in the model but the supporting evidence found was not verified (section 5).
6. **Experiment with lineups before depending on them.** E9 shows the fields exist; the timing is unknown. Log the live `boxscore` for one week, in the tick's closing window, and measure how many games have `starter` filled 30 and 15 minutes before tip-off. Cheap and decides whether a lineup feature is feasible.
7. **Totals and props (ROADMAP 2): evidence is thin.** This pass found no verified source on closing-total error or prop efficiency (section 5). Before building models, measure it on our own data: the standard deviation of (final total minus closing total) per game, and the vig of the stored prop quotes. Treat props as a hypothesis, not a plan.

## 4. Open question that needs the owner

The injury-report PDFs are the best free source, and the page carries "No portion of NBA.com may be duplicated, redistributed or manipulated". The NBA terms of use that were retrievable (nba.com/termsofuse) do **not** contain an explicit ban on automated access; they restrict commercial use, redistribution and building databases of statistics (section 9 of the terms). That is neither a clear yes nor a clear no for personal, low-frequency research use. Following `AGENTS.md` rule 9 and ROADMAP item 1, the owner has to decide. If allowed: a few requests a day, an honest User-Agent, no redistribution of the PDFs or derived raw data. `balldontlie` (E8) is a cleaner alternative if its free key exposes injuries; that has to be tested with a key.

## 5. Rejected or unverified (do not rely on these)

| Claim from the Gemini pass | Status |
|---|---|
| "CLV vs profit R-squared of 0.99 over 100,000 wagers" (Pinnacle article) | Not found; a search returned only vendor marketing. The general principle (CLV is the fastest skill signal) is widely stated but this number is **unverified** |
| FiveThirtyEight Elo: ~48-49 Elo for a back-to-back, 4 Elo per 1,000 miles | Source page now redirects away and the archive is blocked; **unverified**. Our model's home advantage 60 and 28 Elo per point come from the project's own docs |
| "Rest asymmetry costs 1.5-2.0 points" (DOI 10.2202/1559-0410.1105) and "500 km flown costs 4% win probability, p = 0.038" (DOI 10.5664/jcsm.9512) | **Rejected**: the first DOI is a women's volleyball paper, the second a shift-work guideline. The numbers have no source |
| EPM out-of-sample RMSE 2.48 vs RPM 2.60 vs RAPTOR 2.63 vs BPM 2.71 | **Not on the cited page.** What the page does show: EPM's game-margin average miss is 9.6 points over 24,425 games (2005-06 to 2023-24) against a team-rating baseline |
| Hubáček (IJF), Gandar, Paul and Weinbach, Berkowitz, Borghesi, Whitrow, Whelan, Kaunitz-in-RSOS: DOIs as cited | **Wrong DOIs.** Real: Hubáček and Whitrow (corrected above), Gandar *J. Finance* 1998 (10.1111/0022-1082.155346). Not found: Borghesi, Whelan, the quoted Berkowitz and Paul-Weinbach papers. Kaunitz et al. exist only as arXiv 1710.02824 (the preprint's title contains "how the online sports betting market is rigged"); the journal DOI Gemini gave belongs to an unrelated paper. Their conclusions as summarised by Gemini were **not verified** |
| Closing totals RMSE "12-15 points", attributed to Manner (2016) | Manner's paper (JQAS, DOI verified) models game outcomes, not totals; **unverified** |
| Props: "7-10% hold", "limits $100-$500", "1 second of court time" void rule, minutes/usage framework, negative-binomial approach | Sources were blogs, a Medium post, an NFL article and a vendor site; the sportsbook rule page was not read. **Unverified.** Check each book's own rules before writing settlement |
| Pinnacle's own article URLs given by Gemini | Two different URLs for the same article; neither was opened. **Unverified** |
| NBA terms "explicitly prohibit scraping" | **Not supported** by the text retrieved (see section 4) |
| `nba_api` "starters populate ~30 minutes before tip-off" and ESPN / Rotowire / Basketball-Reference access rules | **Unverified** (the docs do not state the timing; the other terms pages were not read) |

## 5b. Follow-up measurements (2026-10-28)

- **Pinnacle-referenced CLV, first real reading** (database copy of 2026-10-28, 23 games with a comparable close): mean +0.34%, standard error 1.27%, t 0.27, observed sd 6.11%; about 231 independent bets are needed to detect +1%. The same-book figure over 40 bets was +4.10%, so the optimism warned about in section 1 is real. The h2h part was recomputed independently with SQL (21 games, maximum difference 0.0002 in log units).
- **Closing totals** (39 settled games): mean error (final total minus closing total) -5.05 points, sd 17.69; far too few games to say anything about bias, but the sd is the scale any totals model has to beat.
- **`balldontlie` injuries are not free**: its API page lists `GET /v1/player_injuries` for the ALL-STAR and GOAT tiers only and `GET /v1/lineups` for GOAT only, with starters available only once the game begins. The free tier cannot supply either, so the only free injury source remains the NBA PDFs (owner decision pending).

## 6. Suggested order

1. Item 1 (Pinnacle CLV with clustering) and item 3 groundwork: no external dependency, makes every later result readable.
2. Item 6 (lineup logging) in parallel: a week of passive data.
3. Item 2 (market-only arm) once item 1 exists to compare it.
4. The owner's decision in section 4, then ROADMAP 1.
5. Items 4 and 7 when the sample (about 150 paired games per challenger) is closer.

Process note for future research with Gemini: verify DOIs against Crossref before reading any claim; in this pass that single mechanical check removed more than half of the academic citations.
