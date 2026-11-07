# Analysis and betting modes

## Objective

Split the web app into two clearly separated product modes, NBA Analytics and Betting (paper trading), with a prominent toggle, and make `/props` honest about its lack of measured skill.

## Problem

- The sidebar mixed 16 links from two products in one list.
- `/props` showed quarter-Kelly stakes and "+EV" picks although the props negative-binomial model is measured worse than the bookmaker (shadow Brier 0.2558 vs 0.2456, 95% CI of the difference excludes zero, n = 2,563, 2026-11-01).

## Decisions

| Id | Decision |
|----|----------|
| D1 | One typed route table in `frontend/src/lib/modes.ts`, read by the sidebar, navbar, toggle and command palette |
| D2 | Mode is resolved from the pathname first, then from the persisted preference (`localStorage` key `archetype_nba_mode`, wrapped in try/catch), and synced from the route |
| D3 | Switching mode navigates to the mode's home: `/` for analysis, `/betting` for betting |
| D4 | Orange accent for analysis; emerald accent plus a "BETTING • PAPER" badge for betting |
| D5 | Analysis: `/`, `/training`, `/versus`, `/shot-zones`, `/matchups`, `/lineup`, `/doppelgangers`, `/contracts`, `/galaxy`, `/hall-of-fame`, `/teams`, `/timeline`, `/player/[name]`. Betting: `/betting`, `/week`, `/paper`, `/league`, `/props` |
| D6 | Command palette pages are grouped and badged by mode, current mode first |
| D7 | Hub numbers come only from `GET /api/v1/paper/summary`; on failure an em dash or qualitative wording, never a hardcoded figure |
| D8 | The `/props` banner reads `props_shadow` from the same endpoint with a qualitative fallback; every Kelly stake recommendation is removed; EV and edge are labelled as unvalidated model figures |
| D9 | No backend change |

## Tasks

| Id | Task | Status |
|----|------|--------|
| T1 | `lib/modes.ts` route table, `modeForPathname`, `homeForMode`, per-mode theme | done |
| T2 | Mode in `PreferencesContext` | done |
| T3 | `ModeToggle` in the navbar | done |
| T4 | Sidebar filtered by mode, toggle in the mobile drawer | done |
| T5 | Command palette pages grouped by mode | done |
| T6 | `/betting` hub with live numbers and a permanent paper-only notice | done |
| T7 | `/props` experimental banner and removal of stake advice | done |
| T8 | Checks | done |

## Acceptance criteria

1. AC1: every route is classified.
2. AC2: a deep link to `/paper` shows betting mode; `/versus` shows analysis mode.
3. AC3: toggling from `/` goes to `/betting` and back.
4. AC4: the toggle is available in the mobile drawer.
5. AC5: the hub shows the permanent notice (paper only, the model does not beat the market yet, judge by CLV against Pinnacle) with live numbers only.
6. AC6: the `/props` banner cannot be dismissed, no stakes are shown, EV is labelled unvalidated.
7. AC7: `tsc --noEmit` clean, no new lint findings, `npm run build` passes.

## Checks

- `npx tsc --noEmit`: clean.
- `npm run lint`: 30 errors and 102 warnings, identical to the baseline on `origin/main` (0 new).
- `npm run build`: passes, 19 routes including `/betting`.
- Dev server: `/`, `/betting`, `/props`, `/paper`, `/versus` return 200 with the expected mode markers. No in-browser visual pass was done.

## Progress

- 2026-11-01: plan, implementation, checks and two commits on `feat/analysis-betting-modes`; merged with `feat/calibrated-policy` on `integration/modes-and-calibrated-policy`, combined build verified.

## Follow-ups

- Revisit `/props` once `props_nb` passes the evaluation gate (n >= 200 with a CI favouring the model).
- `kelly_stake_pct` is still part of the props API type but unused in the UI.
