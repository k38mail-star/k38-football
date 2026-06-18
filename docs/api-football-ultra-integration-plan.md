# API-Football Ultra Data Analysis and Integration Plan

## Executive Summary

API-Football Ultra has enough quota for richer match pages and a stronger pre-match prediction layer. The highest-value additions are Head to Head, Injuries, Teams/Venue, and Coach. Squad/player data is also useful, but it should be handled carefully: the `players/squads` endpoint gives season roster depth, while actual starting XI and bench data should come from fixture lineups when available.

The recommended first phase is:

1. Add cached Head to Head data to prediction cards and match detail pages.
2. Add injury alerts for upcoming fixtures.
3. Add coach names and venue/team metadata to the match header.
4. Store raw API payloads with TTL-based refresh rules before adding deeper model features.

At 10 matches per day, the estimated extra API cost is about 40 calls/day without cache. With stable-data caching, the normal daily cost should fall close to zero after the first fetch for each fixture/team pair.

## Current System Context

The current app already collects fixture lists, live fixtures, fixture detail, events, statistics, scores, referee, and venue name through API-Football. Data is persisted mainly in `football_matches`, and predictions are generated from local completed matches with same-league head-to-head derived from already stored fixtures.

This means the next integration should avoid repeatedly calling expensive detail endpoints during page views. The collector should prefetch and cache enrichment data by fixture/team/season, while the Flask API should only read from SQLite.

## Data Value Assessment

| Data source | Rating | Prediction impact | User experience | Quota cost | Development complexity | Recommendation |
| --- | --- | --- | --- | --- | --- | --- |
| Head to Head | ⭐⭐⭐⭐⭐ | High: direct matchup history improves priors and confidence explanations | High: users expect historical meetings before a match | Low: 1 call per fixture pair, cacheable for days | Medium: needs normalization and display | Integrate first |
| Injuries | ⭐⭐⭐⭐⭐ | High when key players are unavailable; strongest short-term signal among listed sources | High: concise injury warnings add real context | Medium: fixture/league/team scoped calls, cache for match day | Medium: requires key-player heuristic | Integrate first |
| Teams/Venue | ⭐⭐⭐⭐ | Medium: home venue, country, founded, capacity, surface, neutral-site checks can improve context | High: richer team and stadium display | Low: team/venue metadata is stable and heavily cacheable | Low to medium | Integrate first |
| Coach | ⭐⭐⭐⭐ | Medium: useful for style continuity and recent coach changes | Medium: adds credibility to detail page | Low: team/season scoped and cacheable | Low | Integrate first |
| Players/Squads | ⭐⭐⭐ | Medium: roster strength helps, but season squad is not the same as confirmed lineup | Medium-high: roster display is useful, true lineup display is better | Medium: 2 team calls per season; actual lineups may be fixture scoped | Medium-high: player identity, positions, starters vs bench | Integrate after base cache; use fixture lineups for starters |

### Rating Rationale

#### 1. Players/Squads - ⭐⭐⭐

Squad data improves team context by exposing squad depth, positions, ages, and player IDs. It is most useful as a foundation for later player-level modeling, such as missing-player impact, captain/goalkeeper availability, and roster strength.

The main limitation is semantic: season squads are not confirmed match lineups. For the requested "首发+替补" display, the implementation should prefer API-Football fixture lineups when available. `players/squads` can fill the broader squad page or act as fallback when lineup data is missing.

Recommended use:

- Cache `players/squads?team={team_id}` by team and season.
- Add a team roster module behind the match detail page or team profile.
- For match detail "首发+替补", add a separate fixture lineup fetch/cache when available.
- Link player IDs to injuries and events so users can see whether injured players are important.

#### 2. Teams - ⭐⭐⭐⭐

Team metadata is stable, cheap to cache, and improves many screens. It can supply logo, country, founded year, national/team flag context, and venue relationship. Venue details can add stadium name, city, address, capacity, and surface.

Prediction impact is not as direct as H2H or injuries, but the data helps identify neutral venues, travel context, and home-field assumptions. It also makes match pages feel more complete with very low ongoing quota cost.

Recommended use:

- Cache `teams?id={team_id}` or `teams?league={league_id}&season={season}`.
- Persist team logo/country/founded/national plus venue fields.
- Use venue capacity/city/surface in match detail.
- Add a neutral-site flag if fixture venue does not match the home team's cached home venue.

#### 3. Coach - ⭐⭐⭐⭐

Coach data is useful for both presentation and modeling. In the UI it gives users immediate context. In prediction it can later support features like new-manager effect, coach tenure, and style continuity, although those require historical coach changes to be reliable.

Recommended use:

- Cache coach by `team_id` with season-aware refresh.
- Show home and away head coaches in the match header or a small staff row.
- Store coach ID, name, nationality, age, photo, start date if available.
- Refresh weekly, plus manually refresh on match day for high-interest fixtures.

#### 4. Head to Head - ⭐⭐⭐⭐⭐

Head to Head is the best immediate prediction upgrade because the current system only derives H2H from locally stored completed matches. API-Football can fill gaps across competitions and older seasons that are missing from the local fixture table.

Recommended use:

- Fetch `fixtures/headtohead?h2h={home_id}-{away_id}` once per fixture pair.
- Cache by canonical team-pair key, for example `min_team_id:max_team_id`.
- Store normalized matches with date, league, teams, score, venue, and status.
- Use the last 5-10 completed H2H matches in prediction factors.
- Display a compact "历史交锋" section on match detail and prediction pages.

Prediction features:

- H2H win/draw/loss rate.
- Goal average and both-teams-scored rate.
- Home-vs-away matchup split.
- Recency weighting, with recent 3-5 meetings carrying more weight.

#### 5. Injuries - ⭐⭐⭐⭐⭐

Injuries are high-value because they change a team's true strength near match time. The biggest product risk is noisy alerts: a long list of low-impact absences can reduce trust. The UI should only elevate "key player" absences and keep the full list secondary.

Recommended use:

- Fetch injuries for upcoming fixtures or by league/season/date where available.
- Cache by fixture or team/date with short TTL on match day.
- Match injured players against squad/player IDs, recent events, and available statistics.
- Show a red/amber injury warning only for likely key players.

Key-player heuristic for phase one:

- Player appears in recent lineups/events when lineup data exists.
- Player position is goalkeeper, defender, midfielder, or forward and is present in official squad data.
- Player has recent goals/cards/substitution events in local data.
- Manual override list for stars can be added later.

## Recommended Integration Design

### Data Collection Pattern

Add a dedicated enrichment collector instead of fetching this data from request handlers.

Suggested flow:

1. Existing schedule collector saves fixtures.
2. For each fixture in the next 3 days, enqueue enrichment jobs.
3. Enrichment collector checks cache freshness.
4. API calls are made only if missing or expired.
5. Match API returns enrichment fields from SQLite.

### Suggested SQLite Tables

Keep the first version simple and cache-oriented:

| Table | Key | Purpose | Refresh policy |
| --- | --- | --- | --- |
| `football_api_cache` | `cache_key` | Raw response cache for safe rollout/debugging | TTL per endpoint |
| `football_teams` | `team_id` | Team profile and home venue metadata | 7-30 days |
| `football_coaches` | `team_id, season` | Current coach display and future coach features | 7 days |
| `football_h2h` | `pair_key` | Normalized historical meetings | 7 days before match, 30 days after |
| `football_injuries` | `fixture_id/player_id` or `team_id/date/player_id` | Injury alerts | 6-12 hours on match day |
| `football_squads` | `team_id, season, player_id` | Player roster foundation | 7-30 days |
| `football_lineups` | `fixture_id, team_id` | Actual starters/substitutes when available | Refresh until lineup appears, then freeze |

### API Endpoint Mapping

| Feature | API-Football source | Parameters | Cache key | UI target |
| --- | --- | --- | --- | --- |
| Squad/player roster | `players/squads` | `team` | `squad:{team_id}:{season}` | Team roster, lineup fallback |
| Actual starters/subs | fixture lineups endpoint or fixture detail lineups field when available | `fixture` | `lineups:{fixture_id}` | Match detail lineups |
| Team profile | `teams` | `id` or `league + season` | `team:{team_id}` | Match header, team pages |
| Venue profile | `venues` or team venue fields | `id`, `team`, or city/name depending on available IDs | `venue:{venue_id}` | Match header and venue block |
| Coach | `coachs` / coaches endpoint | `team` | `coach:{team_id}:{season}` | Match header |
| Head to Head | `fixtures/headtohead` | `h2h={home_id}-{away_id}` | `h2h:{min_id}:{max_id}` | Prediction and match detail |
| Injuries | `injuries` | `fixture`, or `league + season + date/team` | `injuries:{fixture_id}` | Match alert and prediction factors |

Note: API-Football naming differs across docs and wrappers, especially around `coach/coachs/coaches`. Use the exact endpoint name already accepted by the configured API host during implementation and wrap it behind one local helper.

## Page-Level Integration

### Match Detail Page

Recommended layout additions:

1. Header enrichment:
   - Home coach and away coach.
   - Stadium city/capacity/surface.
   - Team logos if available.

2. Injury alert:
   - Show only if at least one important player is out/doubtful.
   - Example: "伤病提示: Team A 缺少主力门将 X；Team B 前锋 Y 出战成疑。"
   - Full injury list can sit in a collapsible section.

3. Head to Head:
   - Last 5 meetings with date, competition, score.
   - Summary: home wins/draws/away wins, average goals.
   - Use the current home/away orientation in labels.

4. Lineups:
   - When fixture lineup exists: show starters and substitutes.
   - Before lineup exists: show likely squad/roster with a clear "预计/名单" label, not "首发".

### Prediction Pages

Prediction should consume normalized enrichment instead of raw payloads:

- Add H2H weighted score into existing prediction strength calculation.
- Add injury penalty for key missing players.
- Add venue adjustment only when neutral venue or unusual away travel is detected.
- Add coach-change factor later after enough coach history is stored.

Suggested first scoring changes:

| Feature | Adjustment |
| --- | --- |
| H2H advantage in last 5 completed meetings | +/- 3 to 8 strength points |
| Key goalkeeper/central forward injury | -4 to -8 strength points |
| Multiple likely starters unavailable | -5 to -12 strength points |
| Neutral venue for home team | Remove or reduce current home +5 boost |
| Coach metadata only | Display first; do not score until tenure/history exists |

## API Quota Budget

Ultra quota: 75,000 requests/day.

Current usage estimate: about 8,045 requests/day.

Remaining estimate: about 66,955 requests/day.

### No-Cache Estimate

| Scope | Calls per match | Matches/day | Extra calls/day | Notes |
| --- | ---: | ---: | ---: | --- |
| Squad/player | 1-2 | 10 | 10-20 | Team-level data, not required daily after cached |
| Coach | 1-2 | 10 | 10-20 | Can be fetched per team/season |
| Teams/Venue | 1 | 10 | 10 | Mostly stable |
| Head to Head | 1 | 10 | 10 | Pair-level cache |
| Injuries | 1 | 10 | 10 | Short TTL near kickoff |
| Baseline requested estimate | 4 | 10 | 40 | Excludes optional injury/lineup refreshes |

Even a broader first version of 50-70 extra calls/day is far below the remaining daily budget.

### Cached Estimate

| Data source | Cache TTL | First-day cost for 10 matches | Normal repeated cost |
| --- | --- | ---: | ---: |
| Teams/Venue | 7-30 days | Up to 20 team calls plus venue calls | Near 0 |
| Coach | 7 days | Up to 20 team calls | Near 0 |
| Squad/player | 7-30 days | Up to 20 team calls | Near 0 |
| Head to Head | 7-30 days | 10 pair calls | Near 0 until matchup changes |
| Injuries | 6-12 hours on match day | 10-30 calls depending refresh frequency | Low but not zero |
| Actual lineups | 15-30 minutes before kickoff until found | 10-40 calls on active match days | Low after lineup is published |

Recommended quota guardrails:

- Set a daily enrichment budget, for example 2,000 calls/day.
- Deduplicate by fixture/team/pair before calling API.
- Never fetch enrichment synchronously from a user page view.
- Store response headers and request count if the provider exposes quota metadata.
- Use stale cached data for display when the API fails.

## OpenFootball + API-Football Merge Plan

OpenFootball and API-Football should have different responsibilities:

| Source | Strength | Best use |
| --- | --- | --- |
| OpenFootball | Long-range global history from 1930-2026, transparent static data, useful for bulk offline processing | Historical team strength, tournament patterns, country-level baselines, long-term model training |
| API-Football | Current fixtures, live scores, injuries, squads, coaches, venues, detailed fixture data | Match-day context, current rosters, current competitions, UI enrichment |

### Entity Resolution

A merge layer is required because team names and competition names will not always match.

Recommended entity keys:

- API-Football team ID as the primary key for current app data.
- OpenFootball canonical team name plus country/competition as historical identity.
- Alias table for translations and renamed teams.
- Manual mapping table for high-value teams and World Cup/national teams first.

Suggested table:

| Column | Purpose |
| --- | --- |
| `api_team_id` | Current API-Football team ID |
| `openfootball_team_key` | Canonical OpenFootball identity |
| `display_name_cn` | Current Chinese display name |
| `display_name_en` | Current English display name |
| `country_code` | Disambiguation |
| `confidence` | Exact/manual/fuzzy mapping confidence |
| `updated_at` | Mapping audit |

### Combined Prediction Model

Use OpenFootball for priors and API-Football for current match adjustments:

1. Base strength:
   - Long-term team/country Elo-like rating from OpenFootball.
   - Competition and era normalization.

2. Recent form:
   - API-Football current season and recent fixture results.
   - Weight recent 5-10 matches more heavily.

3. Matchup context:
   - API-Football H2H.
   - Venue/home/neutral venue from Teams/Venue.

4. Availability:
   - Injuries and lineups from API-Football.
   - Squad depth from `players/squads`.

5. Explanation layer:
   - Show the top 3-6 factors already produced by the current app.
   - Label factors by source: historical, recent form, H2H, injury, venue.

## First-Phase Quick Wins

These changes are low-risk and high impact:

1. Add `football_api_cache` table and endpoint wrapper with TTL.
2. Fetch Head to Head for upcoming matches and use it in `build_match_prediction`.
3. Add a "历史交锋" block on `templates/match.html`.
4. Fetch injuries for upcoming fixtures and show only important alerts.
5. Cache coach and team/venue metadata, then show coach and stadium details in the match header.
6. Keep squad/player data as cached groundwork, but implement confirmed starters with fixture lineups rather than season squad data.

## Phased Delivery Plan

### Phase 1: Cached H2H and Injury Alerts

- Add cache table and helper.
- Add H2H fetch/parse/store.
- Add injuries fetch/parse/store.
- Extend `/api/match/<fixture_id>` response with `h2h` and `injury_alerts`.
- Add H2H and injury UI sections.

Expected result: better pre-match pages and more defensible prediction explanations.

### Phase 2: Coach, Team, and Venue Enrichment

- Add team and coach tables.
- Backfill teams from existing fixtures.
- Display coaches and richer venue fields.
- Detect and display neutral venue.

Expected result: match pages feel more complete with minimal quota cost.

### Phase 3: Player and Lineup Model

- Cache squad/player rosters.
- Add fixture lineup collection.
- Render starters/substitutes when official lineup is available.
- Connect injury alerts to likely starters and squad depth.

Expected result: player-level context becomes accurate enough for both UI and prediction adjustments.

### Phase 4: OpenFootball Historical Fusion

- Build team alias/mapping table.
- Import normalized OpenFootball results.
- Add historical priors and long-term trend features.
- Tune prediction scoring with backtests.

Expected result: current match data and long-term history work together instead of competing.

## Implementation Notes

- Do not block page rendering on API-Football calls.
- Keep raw API responses temporarily for debugging provider schema differences.
- Normalize only the fields used by UI and prediction in phase one.
- Use endpoint-specific TTLs rather than one global cache time.
- Treat lineup availability as time-sensitive: refresh close to kickoff, freeze after found.
- Treat injury severity conservatively in UI copy unless the source gives a clear status.

## Final Recommendation

Integrate Head to Head, Injuries, Coach, and Teams/Venue immediately through a cached enrichment collector. Add squad/player data as a foundation, but do not label season squad data as starters. For real "首发+替补", add fixture lineup collection and show it only after official lineup data is available.

This plan fits comfortably inside the Ultra quota, improves both prediction quality and match-page credibility, and creates a clean path to merge OpenFootball's long historical coverage with API-Football's real-time match context.
