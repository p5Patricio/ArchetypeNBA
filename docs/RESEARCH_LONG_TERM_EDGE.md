# ArchetypeNBA: can a Mexico-based individual build a multi-season edge in NBA betting? (research, 2026-11-01)

Scope: paper-trading research project. Nothing here recommends placing real bets. Every factual claim has a URL. "UNVERIFIED" = could not confirm from a primary source in this pass. Method notes: I read primary pages directly with `curl`/WebFetch where the sites allowed it, used the Internet Archive copy of the SEGOB PDF (the live DGJS site did not respond), checked academic metadata against Crossref/arXiv, and treated affiliate/review sites as weak evidence. WebFetch summaries paraphrase; where I quote a clause in quotation marks it was read from the raw page text via `curl` (Caliente, Betcris, Pinnacle archive copy, Codere PDF).

Disclosure: to find how far back the NBA injury PDF archive goes I sent about 60 HTTP HEAD requests (one per probed date/time, 1 s apart) to `ak-static.cms.nba.com`. No PDF was downloaded. AGENTS.md rule 9 asks to read terms before touching NBA content; the owner's decision on NBA terms is still pending, so treat that probe as a one-off.

---

## A. Mexican sportsbooks the owner can use legally

### A.1 Legal frame
- Online sports betting in Mexico is allowed only through SEGOB's Dirección General de Juegos y Sorteos (DGJS); each website is authorized individually. Base law: Ley Federal de Juegos y Sorteos (DOF 1947). Source (aggregator, secondary): https://gamblingmaps.org/es/regulacion/mexico . Official law text: https://dof.gob.mx/nota_detalle_popup.php?codigo=5107323
- The authoritative list is the DGJS PDF "Páginas web autorizadas" (June 2026, 135 websites). The live DGJS site did not respond from this machine; I read the PDF through the Internet Archive snapshot of 2026-08-18: https://web.archive.org/web/20260818041316if_/http://www.juegosysorteos.gob.mx/work/models/Juegos_y_Sorteos/Resource/298/1/images/VF_Web_autorizadas_jun2026.pdf (index page: https://web.archive.org/web/2026/http://www.juegosysorteos.gob.mx/es/Juegos_y_Sorteos/Salas_de_Sorteos_de_Numeros ). Re-check the live list before relying on any status; statuses change.
- Is it legal for the *player* to use an offshore (non-SEGOB) book such as Pinnacle? Secondary sources say the law burdens the operator, not the bettor, and that foreign licences (Malta, Curaçao) do not make an operator legal in Mexico, but I found no official statement and no lawyer's opinion: https://www.elcontribuyente.mx/2025/12/la-licencia-segob-y-su-papel-en-las-apuestas-de-futbol-en-mexico/ (does not address bettor liability). Treat as UNVERIFIED; get legal advice if it matters. Loss of consumer protection is the practical risk.

### A.2 Status of the books you named (official DGJS list, June 2026)

| Brand | DGJS status (June 2026) | Permisionaria / operator on the list |
|---|---|---|
| caliente.mx | Operando | Impulsora Géminis / Tecnología en Entretenimiento Caliplay (also winner.mx) |
| codere.mx | Operando | Libros Foráneos |
| betcris.mx | Operando | Producciones Móviles / Paradise Riviera Gaming |
| betway.mx | Operando | Espectáculos Deportivos Frontón México / FM Operadora Profesional en Apuestas |
| strendus.com.mx | Operando | Atracciones y Emociones Vallarta / New Ads |
| playdoit.mx | Operando | Súper Juegos Robín / Atracciones América (merged company) |
| winpot.mx | Operando | Pur Umazal Tov / Winpot Online América |
| bigbola.mx, onlinebigbola.mx | "Baja temporal", "Procedimiento administrativo" | Comercial de Juegos de la Frontera |
| bet365.mx | **Suspensión DGJS** | Ganador Azteca |
| betano.mx | Suspensión DGJS | Ganador Azteca / Operadora Ganador TV Azteca |
| 1xbet.mx | Suspensión DGJS | Espectáculos Deportivos de Occidente |
| williamhill.mx, stake.mx | Baja temporal | Producciones Móviles group |
| bwin.mx, betsson.mx, coolbet.mx, rushbet.mx, sportiumbet.mx | Operando | various |

Source for the whole table: the DGJS PDF above. Counts: aggregator reports 136 sites, 86 operating, 27 temporary, 13 no operations, 10 suspended (https://gamblingmaps.org/es/regulacion/mexico/operadores ).
Cross-checks inside operator terms: Caliente states permit "DGG/SP/404/97" (https://www.caliente.mx/mas/ayuda/terminos-y-condiciones/ ); Betcris states it is run in Mexico by permisionaria Producciones Móviles, permit "DGAJS/SCEVF/P-06/2005-TER", operator Paradise Riviera Gaming, "oficio DGJS/405/2018" (https://ayuda.betcris.mx/guia-de-usuario/legal/terminos-y-condiciones-legal/ ).
Note: bet365 is *suspended* in Mexico as of that list; do not plan around it.

### A.3 Is Pinnacle accessible from Mexico?
- Pinnacle's Curaçao-entity terms list prohibited residencies (US, UK, France, Netherlands, Spain, Germany, Australia, Italy, Brazil, Venezuela, Russia, Ontario and others). **Mexico is not on that list**, but the clause ends with "any other country which may prohibit the offering of online gambling to its residents or to any person within such country." Read from the Internet Archive copy: https://web.archive.org/web/2026/https://www.pinnacle.com/en/termsandconditions/curacao (live URL: https://www.pinnacle.com/en/termsandconditions/curacao , intermittently 502 to my fetches).
- Pinnacle is not in the DGJS list, so it is not SEGOB-authorized. Third-party guides say Mexico is accepted (https://silentbet.com/pinnacle/where-is-it-legal/ , https://bet2invest.com/blog/Pinnacle-and-Global-Regulation:-Where-You-Can-Still-Bet-Freely ); these are affiliate-style and could not be opened or confirmed. Verdict: *technically open under the listed terms, legally grey, UNVERIFIED in practice* (payment methods from Mexico also unchecked).
- Licence: Curaçao OGL/2023/105/0084 per https://www.hotbookies.com/pinnacle-review (secondary).

### A.4 NBA depth, margins, limits
- Depth: Caliente is now the NBA's official partner in Mexico (3-year deal announced 2026-10-15, with the stated aim to widen NBA-related betting options): https://www.publimetro.com.mx/deportes/2026/10/16/caliente-sella-alianza-con-la-nba-por-tres-anos-busca-ampliar-su-presencia-internacional/ . Earlier NBA partners: Codere (2018, official NBA data): https://pr.nba.com/codere-becomes-first-ever-official-gaming-partner-of-the-nba-in-mexico ; Betcris (2023, Mexico/DR/Panama): https://pr.nba.com/betcris-nba-partnership/ . A TV Azteca guide claims up to 441 markets per NBA game at Caliente (not opened; vendor-style): https://www.tvazteca.com/notas/mejores-casas-apuestas-en-mexico-2026/ . **Whether Mexican books list NBA player props at useful limits: UNVERIFIED.**
- Margin: I found **no documented NBA margin for any Mexican book**. UNVERIFIED. A cross-sport vendor blog claims player props average 7.93% margin vs 4.77% head-to-head (52 books, not NBA-specific, books unnamed): https://lowjuicesportsbooks.com/prop-market-margins-in-mlb-and-nba/ . Measure it yourself (see E).
- Stake limits: Caliente minimum is MXN 5-10 and the maximum "depends on the number of options"; if a bet is too large the system offers a smaller amount: https://www.caliente.mx/mas/ayuda/deportes/cual-es-el-importe-minimo-maximo-que-se-puede-jugar-en-una-apuesta/ . Codere: single-bet win cap MXN 1,500,000 (from a search summary of the live terms, not read in full): https://www.codere.mx/ayuda/legal/terminos-y-condiciones .
- Restriction of winning accounts (what the contracts allow):
  - Caliente 13.7: "Podemos establecer límites en las ganancias de las apuestas, diferente o adicional a los especificados"; 17.3: may "TERMINAR SU USO DE LA PLATAFORMA DE APUESTAS DEPORTIVAS Y DE BLOQUEAR SU CUENTA" without notice if it suspects breach, and states no refund of account funds "EN NINGUNA CIRCUNSTANCIA" in that case; 17.1 may refuse participation (https://www.caliente.mx/mas/ayuda/terminos-y-condiciones/ ). Also, odds "may on occasion be restricted to certain stake levels" (https://www.caliente.mx/mas/ayuda/reglas-de-apuestas/apuestas-generales/ ).
  - Betcris 1.17: may "rechazar apuestas ... y limitar las apuestas, ganancias, cuotas o riesgos en cualquier tiempo sin dar razones" (https://ayuda.betcris.mx/guia-de-usuario/legal/terminos-y-condiciones-legal/ ).
  - Codere (a 2022 policy PDF, may be outdated): "La Empresa se reserva el derecho de aceptar, negar o limitar la apuesta de acuerdo a los niveles de riesgo actual o potencial", plus a "cargo por administración de riesgo ... hasta ... veinte por ciento" on prizes: https://www.codere.mx/library/Documents/T%C3%A9rminos%20y%20Condiciones.pdf (the 20% fee looks odd; verify on the live terms before assuming it applies).
  - Strendus (search summary of its terms): may "aceptar, limitar o rechazar" users and bets: https://www.strendus.com.mx/terminos-y-condiciones/ .
  - So the *right* to limit is explicit everywhere I could read. How fast winners are actually limited at Mexican books: **UNVERIFIED** (no independent evidence found). The only hard evidence of limiting is from Europe: Kaunitz et al. (D.6).

---

## B. Data access and terms

### B.1 Odds APIs and Mexican books

| Provider | Mexican-accessible books? | Price / free tier | Source |
|---|---|---|---|
| The Odds API (current) | **None.** Regions: us, us2, us_dfs, us_ex, uk, eu, au, ca, fr, se, fi. Pinnacle appears only in `eu`. No `mx` region. | Free 500 credits/mo. Historical endpoint is paid-only, costs 10 x markets x regions, data from 2020-06-06 (10-min snapshots; 5-min from Sept 2022); props/alt lines historical only after 2023-05-03 | https://the-odds-api.com/sports-odds-data/bookmaker-apis.html ; https://the-odds-api.com/liveapi/guides/v4/ |
| SportsGameOdds | None of Caliente/Codere/Betcris/Playdoit listed; bet365 and Pinnacle are. More books "upon request through a custom (AllStar) plan" | Free: ~2,500 objects/mo, 9 books, Pinnacle **not** included; Rookie $99; Pro $299 (Pinnacle named); AllStar custom | https://sportsgameodds.com/docs/data-types/bookmakers ; https://sportsgameodds.com/pricing |
| Odds-API.io (different company from The Odds API) | Betano MX and Winpot MX pages exist (Betano MX is suspended per DGJS). Codere MX and Caliente MX were requested; reply "not yet" (year not shown) | From GBP 49/month; "New free API keys are paused" | https://odds-api.io/sportsbooks/latam ; https://odds-api.io/sportsbooks/winpot-mx ; https://feedback.odds-api.io/p/add-codere-and-caliente-mx-bookmakers |
| OddsPapi | Betano MX and Winpot MX pages; Betcris and Betway listed without an MX label; Caliente, Codere MX, Playdoit, Strendus not listed; Pinnacle listed | Vendor claims: free 250 requests/mo, 300+ books, historical odds included, rolling ~100 days per fixture, max 3 books per call, 5 s cooldown | https://oddspapi.io/sportsbooks ; https://oddspapi.io/blog/?p=5269 ; https://oddspapi.io/blog/?p=2498 (all vendor self-reporting) |
| OpticOdds / OddsJam | No evidence of Caliente/Codere; OpticOdds pricing not public (~USD 5,000/mo reported in the repo's own research); OddsJam API pricing not published | not free | https://oddspapi.io/blog/?p=2860 (vendor comparison), repo docs/RESEARCH_BETTING_IMPROVEMENTS.md |

Practical reading: **no API gives Caliente, Codere, Betcris, Playdoit or Strendus.** The only Mexican-licensed brands that appear anywhere are Winpot MX (Spread/Totals/ML, no props; NBA not named) and Betano MX (suspended). Mexican-book prices therefore need a different collection method (see B.3).
Flag for the repo: the Odds API book list marks `williamhill_us` as "paid only"; the project's free-tier request includes it. Verified 2026-11-01 against the production database: `odds_history` holds 0 rows for `williamhill_us` (bovada 4,166, draftkings 3,766, betrivers 2,468, betmgm 2,118, fanduel 2,050, pinnacle 1,380, betonlineag 414), so the free key never returns it.

### B.2 What the terms say about automation

**Pinnacle** (Curaçao terms, section "Prohibited Scraping and Automated Access", archive copy): "You may not access, use, or attempt to access or use the Service, any of its web pages, or any application programming interface ('API') we make available (whether public or private) by any automated means, including without limitation bots, crawlers, spiders, scrapers, data-mining tools, or similar technologies, for the purpose of copying, collecting, harvesting, monitoring, indexing, or otherwise obtaining data or content from the Service (including without limitation odds, prices, lines, markets, or any other betting or transactional information). ... no automated access, scraping, crawling, data extraction, or similar activity is authorized by us unless expressly permitted in a separate written agreement executed by us ..." Same page also: "You are not allowed to use any kind of robots and programmed devices to participate in gameplay with the purpose to disrupt the Service or to commit fraud." URL: https://web.archive.org/web/2026/https://www.pinnacle.com/en/termsandconditions/curacao
Pinnacle's official API: "closed for the general public since July 23rd, 2025"; select bettors and partners, requests to api@pinnacle.com, funded account needed, 2 IPs max, rate limits: https://github.com/pinnacleapi/pinnacleapi-documentation ; https://www.pinnacle.com/en/api (says access can go to academics and "loyal customers", region decided per use case).

**Caliente** (raw text, clauses in Spanish):
- 2.3.5: users may not "Introducir, acceso o tratar de entrar o acceder, o cualquier otra forma soslayar el sistema de seguridad aplicable o interferir de cualquier manera (incluyendo, pero no limitado a, robots y dispositivos similares) con ... el Sitio Web".
- 19.3: "Es posible acceder a la información (incluyendo ... resultados, estadísticas, datos deportivos y calendarios de los partidos, las probabilidades de apuestas y figuras) en, y descargar e imprimir extractos de este Sitio Web para su uso personal. ... se le prohíbe expresamente el uso de tales materiales para cualquier propósito comercial".
- 19.4: no "transferir, copiar, reproducir, distribuir, explotar o hacer cualquier otro uso de los materiales ... que no sea a los efectos de mostrarla en la pantalla del ordenador y la impresión".
- 17.3 (account block, no refund) above. URL: https://www.caliente.mx/mas/ayuda/terminos-y-condiciones/

**Betcris** (raw text): 2.19 "El uso de cualquier programa de software que facilite la inteligencia artificial está estrictamente prohibido. El software prohibido puede incluir software (por ejemplo, scripts, bots o spider) que Betcris cree, a su sola discreción, permite a los Usuarios engañar o le da a un Usuario una ventaja injusta mientras apuesta ... En caso de que Betcris identifique o tenga buenas razones para sospechar el uso de programas prohibidos, Betcris se reserva el derecho de bloquear la cuenta ..., confiscar los fondos en esa cuenta y/o suspender al Usuario ..."; 6.6 "Betcris prohíbe y toma medidas para prohibir el uso de dispositivos, como robots, por parte del Usuario, que distorsionan el uso normal de los servicios." URL: https://ayuda.betcris.mx/guia-de-usuario/legal/terminos-y-condiciones-legal/

**Codere**: the policy PDF I could parse (dated 2022) has no robot/bot/automation clause; the live terms page is a JavaScript app and returned no text, so the current terms are **UNVERIFIED**. **Strendus, Playdoit, Betway MX**: terms pages blocked my fetch (403/404); search summaries show no bot clause for Strendus or Playdoit, but I did not read the full texts. **UNVERIFIED**.

### B.3 Would your two collection methods breach terms? (my reading, not legal advice)

| Book | (1) HTTP scraping (scripts/requests/headless) | (2) AI agent driving the owner's own logged-in browser, **read-only** |
|---|---|---|
| Pinnacle | **Breach, explicit** ("bots, crawlers, ... for ... monitoring ... odds, prices, lines") | **Breach, explicit.** The clause covers any "automated means" and "monitoring"; an AI agent clicking pages is automated access. Reading-only does not help. Also you are logged in, so the remedy lands on your account. |
| Betcris | Likely breach (2.19 is tied to betting advantage, but 6.6 and the "scripts, bots or spider" wording are broad); consequence is account block and fund confiscation | **High risk.** Clause literally bans "software que facilite la inteligencia artificial". Intent (reading) is outside the stated purpose "mientras apuesta", but the operator decides "a su sola discreción", and the penalty includes confiscation. Do not do this with real funds. |
| Caliente | **Probable breach in effect**: no explicit scraping ban, but 2.3.5 (robots interfering with the site/security) and 19.4 (no copying beyond viewing) apply; Cloudflare-style blocking would turn it into "circumventing" | **Moderate/low, not zero.** 19.3 expressly lets you access "las probabilidades de apuestas" and download extracts "para su uso personal" (non-commercial research fits), and an agent that behaves like one human at human speed is hard to tell from you. Residual risks: "robots" wording in 2.3.5, 19.4 on storing copies, and 17.3's discretionary block with no refund. |
| Codere / Strendus / Playdoit / Betway | UNVERIFIED | UNVERIFIED |

Concrete conclusions:
- Breaching terms is a *contract* issue (account closure, fund forfeiture), not a crime in itself; but the account and balance are the thing you would lose, and project rule 9 says not to scrape where terms forbid or are ambiguous and to ask the owner.
- Lowest-risk route that still yields Mexican prices: **human-in-the-loop sampling** (you or a helper note/screenshot lines for a fixed list of games at fixed times, no automation). Compliant with every clause I read, and enough to estimate the margin and staleness of Caliente/Codere/Betcris vs Pinnacle on, say, 100-200 games.
- An agent reading *public* (logged-out) pages at Caliente is a separate question from a logged-in one; whether odds are visible logged-out is UNVERIFIED.
- Never use the agent where the same session could place a bet; keep a separate browser profile with no stored payment methods.

---

## C. Long-horizon data

### C.1 Historical NBA odds (free)

| Source | Coverage | Content | Licence / status |
|---|---|---|---|
| Sportsbook Reviews Online archive | NBA 2007-08 to 2022-23 (16 seasons), "NBA scores and odds archive will not be updated" | moneylines, 2nd-half lines, opening and closing spreads and totals; which book(s) is not stated on the page (UNVERIFIED) | Static, frozen; terms not stated on the page: https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba/nbaoddsarchives.htm |
| Kaggle "NBA Betting Data" (cviaxmiwnptr) | Oct 2007 to Jun 2026 in `nba_2008-2026.csv` | scores, quarter scores, spread, total, moneyline. Sources: SBRO to mid-Jan 2023, ESPN Jan 2023 to 22 Jun 2025 (no moneyline or 2H in the ESPN part), SBR median odds from 21 Oct 2025 | CC0 per the uploader; upstream rights (ESPN) unclear; project rule 9 rejects scraping ESPN, so using a CC0 compilation is a judgment call for the owner: https://www.kaggle.com/datasets/cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024 |
| Kaggle "NBA Historical Stats and Betting Data" (ehallmar) | not read | | https://www.kaggle.com/datasets/ehallmar/nba-historical-stats-and-betting-data |
| aussportsbetting.com NBA page | blocked by Cloudflare (403) for me: coverage, bookmakers and licence **UNVERIFIED** | | https://www.aussportsbetting.com/data/historical-nba-results-and-odds-data/ |
| GitHub `flancast90/sportsbookreview-scraper` | pre-scraped data 2011-2021 (README) | code MIT; data rights unstated | https://github.com/flancast90/sportsbookreview-scraper |
| Paid for reference | The Odds API from 2020-06-06; SportsDataIO since 2019 via sales; Odds Market from March 2023 | | https://the-odds-api.com/liveapi/guides/v4/ ; https://sportsdata.io/historical-odds |

Important limit: the free archives give *one* closing number per game (book unknown or a consensus), not Pinnacle's de-vigged close. They still let you measure Brier of your model against a market close over about 16 seasons (~19,000 games) instead of waiting five seasons for live data (the 6,100-game / five-season figure in docs/QUANT_MODULE.md section 13). The Pinnacle-versus-this-close difference is small but nonzero; calibrate with the 2026-27 overlap games you already store.

### C.2 NBA injury report PDF archive depth
Probed with HEAD requests on `https://ak-static.cms.nba.com/referee/injury/Injury-Report_YYYY-MM-DD_HHPM.pdf`: 2018-12-16 (05PM, 08PM) returned 403 (absent); **2018-12-17 returned 200**, and the dates I sampled from then to 2021 returned 200; sampled dates in Oct-Nov 2018 and 2016-2017 returned 403. So the archive starts around **2018-12-17** (mid 2018-19 season), roughly 8 seasons. File naming in 2018-2022 is hourly (`..._05PM`); the current page lists 15-minute versions. Current rules and timing: https://official.nba.com/nba-injury-report-2025-26-season/ . A PyPI package states pre-game reports are available from 2021-22 onward: https://pypi.org/project/nba-injury-report/ . A Substack offers downloadable injury CSVs (provenance unchecked): https://statsurge.substack.com/p/downloadable-nba-injury-datasets . Terms question unchanged: see docs/RESEARCH_BETTING_IMPROVEMENTS.md section 4. Caveat: the report timing only helps if you also have a *timestamped* price history (see E2); historical odds from SBRO/Kaggle are open/close only.
Context: the NBA and US sportsbooks agreed for 2026-27 to ban same-player under parlays and unders on players expected to play under 12 minutes, among others (US operators named; applicability to Mexican books UNVERIFIED): https://www.covers.com/industry/nba-bans-certain-bet-types-ahead-of-new-season-oct-16-2026

### C.3 Lineups, starters, tracking (free)
- `shufinskiy/nba_data` (Apache-2.0): play-by-play 1996/97 to 2024/25, shot details, on-court "matchups" 2017/18 to 2024/25, data.nba.com coordinates from 2016/17, pbpstats from 2000/01: https://github.com/shufinskiy/nba_data
- `nba_api` documents endpoints for traditional box scores (starter flags, minutes), `leaguedashptstats` (SpeedDistance, Rebounding, Possessions and other tracking types), hustle stats, and `boxscoreplayertrackv3`: https://github.com/swar/nba_api/tree/master/docs/nba_api/stats/endpoints . **First season each endpoint is populated: UNVERIFIED** (check by calling).
- balldontlie: injuries and lineups are paid tiers only (from the repo's own research).
- Basketball-Reference: bot policy page was blocked (Cloudflare) so terms are UNVERIFIED.

---

## D. Can an individual beat NBA markets long-term? Evidence

Bibliographic details below were checked against Crossref (DOI resolves to the stated title/year/venue). Findings are from the abstract unless noted.

1. Gandar, Dare, Brown, Zuber (1998), *Informed Traders and Price Variations in the Betting Market for Professional Basketball Games*, J. Finance, 10.1111/0022-1082.155346: opening-to-closing line changes in NBA spreads significantly improve accuracy and remove opening biases; evidence of informed traders. Implication: the close is the efficient benchmark; edge, if any, lives at the open or before news is priced.
2. Gandar et al. (2000), *The Search for Informed Traders in the Totals Betting Market for NBA Games*, J. Sports Economics, 10.1177/152700250000100205: same for totals; closing totals beat opening totals.
3. Brown and Sauer (1993), *Fundamentals or Noise? Evidence from the Professional Basketball Betting Market*, J. Finance, 10.1111/j.1540-6261.1993.tb04751.x: NBA spread movement is explained by unobserved fundamentals, not noise.
4. Hubáček, Šourek, Železný (2019), IJF 35(2), 10.1016/j.ijforecast.2019.01.001: a model penalized for agreeing with bookmaker odds plus portfolio sizing made positive cumulative profit on NBA 2007-2014 (verified in the repo's earlier research; single study, no accounts-limited reality check).
5. Walsh and Joshi (2024), *Machine learning for sports betting: should model selection be based on accuracy or calibration?*, Machine Learning with Applications, 10.1016/j.mlwa.2024.100539: choosing NBA models by calibration gave average ROI +34.69% vs -35.17% for accuracy selection on one test season using published odds. Treat with caution: **a Corrigendum exists (10.1016/j.mlwa.2025.100627, not read)**, one season, and a catalogue listing shows different ROI numbers for another version. Robust takeaway: calibration, not accuracy, is the selection metric. Source for numbers: https://researchportal.bath.ac.uk/en/publications/machine-learning-for-sports-betting-should-model-selection-be-bas/
6. Kaunitz, Zhong, Kreiner (2017), arXiv 1710.02824 (football, not NBA): betting where soft-book odds beat the consensus of many books returned 3.5% over 56,435 simulated bets (closing odds), 9.9% on 6,994 minute-level bets, and 8.5% on 265 real $50 bets in 5 months; "a few months after we began to place bets with actual money bookmakers started to severely limit our accounts". Source: https://arxiv.org/abs/1710.02824 (numbers from the full text). Most relevant for this project: it is the same idea as the champion's blend policy, and it shows the profit and the account-limiting side together.
7. Moskowitz (2021), *Asset Pricing and Sports Betting*, J. Finance, 10.1111/jofi.13082: momentum in betting contracts; "Returns are a fraction of those in financial markets and fail to overcome transactions costs." Sports covered include several leagues (NBA-specific numbers not read: UNVERIFIED).
8. Waggoner (2014), *"Hot Hand" in the NBA Point Spread Betting Market: A 34-Year Analysis*, IJFS, 10.3390/ijfs2040359: streak effects on spreads; momentum plus gambler's fallacy. Small, season-dependent biases.
9. Levitt (2004), *Why are Gambling Markets Organised so Differently from Financial Markets?*, Economic Journal, 10.1111/j.1468-0297.2004.00207.x: DOI verified; abstract not retrieved. From memory it argues bookmakers price against bettor biases rather than balancing the book (UNVERIFIED here).
10. Context datasets: line movement in 11.7M snapshots across 13 sports finds most price discovery happens 1-7 days before start, only ~0.33 probability points move in the final six hours (aggregate, not NBA-only, CC BY 4.0, 2026): https://data.mendeley.com/datasets/pdsxx5dgbw/1

What the literature does **not** give (honest gaps):
- **Player props**: I found no peer-reviewed test of NBA prop efficiency; "props are softer" is industry opinion (https://nbabettingsystem.com/strategy/ , blog). The only numeric hint is higher margins (above, secondary). Treat props as a hypothesis.
- **Injury-news timing**: no rigorous study found; guides say lines move within seconds to minutes of news (https://www.actionnetwork.com/education/how-injuries-affect-betting-lines-a-guide-to-market-movement ). A claimed 2-hour lag has no data. The NBA is itself tightening prop rules after the October 2025 scandal.
- **Documented profitable NBA individuals with ROI/CLV**: none found with verifiable data. Kaunitz is the best open record (football; 3.5% to 8.5% before limits). "2% yield is excellent" is a practitioner rule of thumb I could not source. Public claims about famous NBA syndicates: UNVERIFIED.

Synthesis (my judgment, not a sourced claim): closing NBA lines at sharp books are very hard to beat with public data (this project's own gap, Brier 0.242 vs 0.202, matches that). Documented edges come from (a) buying a price at a soft book above the sharp consensus (line shopping), (b) speed on information, (c) possibly props; each is eroded by limits. A model *combined with* the market and judged on calibration is the best-supported modelling approach (items 4 and 5). Your own adverse-selection numbers (model 59%, Pinnacle fair 48%, realized 42%) say the model is overconfident against the market; that is a calibration problem before it is an edge problem.

---

## E. Ranked recommendations for the next 6-24 months

1. **Make the model a correction to Pinnacle, not a rival (weeks).** Use Pinnacle's de-vigged probability as a base feature and fit a shrunk residual (logistic on log-odds with the market as offset). Select by calibration and log loss against the close (D4, D5). Expect the first honest gain to be "Brier gap shrinks from 0.040 toward ~0.00x", not positive ROI.
2. **Import the free historical odds and backtest 15+ seasons (weeks).** Kaggle CC0 + SBRO 2007-2023 + `shufinskiy/nba_data` + ingested injury PDFs from 2018-12-17 (owner decision pending). This turns the five-season power problem in docs/QUANT_MODULE.md section 13 into a one-week backtest on ~19,000 games. Walk-forward only; evaluate the gap to the close with Diebold-Mariano. Keep the home-advantage in-sample warning in mind.
3. **Accumulate a timestamped raw odds table for every book (continuous, now).** The scarce asset nobody sells free is a *timestamped* multi-book history (open, intraday, close) next to the injury-report timestamps. Store every snapshot, not only changes in your policy. Add The Odds API props at close for 1 event per tick as budget allows (cost note: 3-4 credits per tick). This is what will let you test the two best-supported mechanisms: opening-line value (D1) and news timing. Check the Odds API free-tier credit math before widening books (flag: `williamhill_us` marked paid-only).
4. **Collect Mexican-book prices by hand to test the one hypothesis that would change the project (a few hours per week, 100-200 games).** Hypothesis, UNVERIFIED: Mexican retail books reprice more slowly or with higher margin than Pinnacle/US books. Test: for each sampled game, at a fixed time before tip-off, note NBA moneyline/spread/total at Caliente, Codere, Betcris vs Pinnacle de-vigged close from your own tables; compute margin and mean edge vs the close. No scraping, no agent, no logged-in automation. If best-price edge over Pinnacle-fair is < +1% after margin, stop thinking about Mexican execution.
5. **Add signals in this order of documented value:** (a) market features (open-to-now line move, cross-book dispersion; D1, D6), (b) injuries/lineups (largest known source the market prices quickly, so value is only in being earlier or modelling replacement-level impact), (c) rest/back-to-back (already in), (d) travel and tracking data (UNVERIFIED value). Props: measure first on your own stored quotes (margin, closing error sd) before building.
6. **Keep calibration and CLV against Pinnacle's close as the only promotion currency** (the repo already does most of this); report CLV clustered by game and ignore ROI until n is in the thousands (docs/QUANT_MODULE.md section 13: ~10,000 bets for a 2% ROI at two standard errors).
7. **Optional, needs the owner:** ask Pinnacle for sanctioned API access for an academic/pregame handicapping project (api@pinnacle.com; stated eligible, but needs a funded account, which conflicts with AGENTS.md rule 1/2, so decide first): https://github.com/pinnacleapi/pinnacleapi-documentation
8. **Second free odds source for resilience:** OddsPapi free tier (250 requests/mo, Pinnacle, historical up to ~100 days) for cross-checking Pinnacle closes. Terms unreviewed (UNVERIFIED); read before use.

### Milestones: continue / stop (proposed thresholds, not sourced)

| When | Metric | Continue if | Stop or re-plan if |
|---|---|---|---|
| Jan 2027 (backtest done) | Walk-forward Brier gap vs historical close, market-offset model with injuries | gap <= 0.010 on held-out seasons and calibration slope within 0.9-1.1 | gap >= 0.020 even with market offset: no signal beyond the market; stop modelling and keep the project as a data/analytics product |
| End 2026-27 regular season (~Apr 2027, ~1,200 games) | Live Brier gap vs Pinnacle close; paired log-loss gain | gap <= 0.010 and CI of gain vs Elo above 0 | gap > 0.02 or model worse than market-only |
| After ~220 independent bets (about one season if aggressive) | Mean log-CLV vs Pinnacle close (needs +1% to be detectable, repo estimate) | lower 95% bound >= 0 | mean <= 0 with n >= 220 |
| End 2027-28 (2 seasons, ~500+ independent bets) | Same, plus adverse selection (model vs fair vs realized) | CLV vs Pinnacle > +0.5% and realized ~ fair | CLV <= 0 and realized below Pinnacle fair again: stop betting-model work |
| Any time | Human-sampled Mexican lines | best-price edge over Pinnacle-fair >= +1% net of margin on >= 100 games | < +1%: drop Mexican execution as a goal |

Realistic probability statement (my judgment): a hobbyist model beating Pinnacle's NBA close from public data is unlikely; a *positive-expectation price-shopping* strategy at soft books is plausible but capped by stake limits and account restrictions (D6). The multi-season path with real upside is the dataset: timestamped prices plus injury timestamps is something few free resources provide and a precondition for anything else.

---

## URLs most used
- DGJS authorized sites June 2026 (archive): https://web.archive.org/web/20260818041316if_/http://www.juegosysorteos.gob.mx/work/models/Juegos_y_Sorteos/Resource/298/1/images/VF_Web_autorizadas_jun2026.pdf
- Pinnacle terms (archive): https://web.archive.org/web/2026/https://www.pinnacle.com/en/termsandconditions/curacao
- Caliente terms: https://www.caliente.mx/mas/ayuda/terminos-y-condiciones/
- Betcris terms: https://ayuda.betcris.mx/guia-de-usuario/legal/terminos-y-condiciones-legal/
- The Odds API bookmakers: https://the-odds-api.com/sports-odds-data/bookmaker-apis.html
- The Odds API historical: https://the-odds-api.com/liveapi/guides/v4/
- Kaggle NBA Betting Data: https://www.kaggle.com/datasets/cviaxmiwnptr/nba-betting-data-october-2007-to-june-2024
- SBRO NBA archive: https://www.sportsbookreviewsonline.com/scoresoddsarchives/nba/nbaoddsarchives.htm
- Kaunitz et al.: https://arxiv.org/abs/1710.02824
- Gandar et al. 1998 (DOI): https://doi.org/10.1111/0022-1082.155346
- shufinskiy/nba_data: https://github.com/shufinskiy/nba_data
- Pinnacle API docs: https://github.com/pinnacleapi/pinnacleapi-documentation
