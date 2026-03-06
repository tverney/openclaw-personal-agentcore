---
name: soccer-cli
description: "Check soccer/football scores, game details, and player stats. Use when a user asks about football matches, scores, standings, or fixtures."
metadata: { "openclaw": { "emoji": "⚽", "requires": { "bins": ["curl"] } } }
---

# Soccer CLI

Check football scores, standings, and fixtures using the football-data.org free API.

## When to Use

✅ **USE this skill when:**

- User asks about football/soccer scores
- User asks about league standings or tables
- User asks about upcoming fixtures
- User asks about specific teams or competitions
- User says "how did [team] play?", "what's the score?"

❌ **DON'T use this skill when:**

- User asks about American football (NFL)
- User asks about historical stats beyond current season

## API Base

```
https://api.football-data.org/v4
```

No API key needed for basic queries (10 requests/minute rate limit).

## Commands

### Today's matches
```bash
curl -s "https://api.football-data.org/v4/matches" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for m in data.get('matches', []):
    home = m['homeTeam']['name']
    away = m['awayTeam']['name']
    status = m['status']
    score = m.get('score', {}).get('fullTime', {})
    h = score.get('home', '-')
    a = score.get('away', '-')
    comp = m['competition']['name']
    print(f'{comp}: {home} {h} x {a} {away} [{status}]')
"
```

### League standings (e.g., Premier League=PL, La Liga=PD, Serie A=SA, Bundesliga=BL1, Ligue 1=FL1, Brasileirão=BSA)
```bash
curl -s "https://api.football-data.org/v4/competitions/PL/standings" | python3 -c "
import json, sys
data = json.load(sys.stdin)
table = data['standings'][0]['table']
print(f'{'Pos':>3} {'Team':30s} {'P':>3} {'W':>3} {'D':>3} {'L':>3} {'Pts':>4}')
for t in table:
    print(f'{t[\"position\"]:3d} {t[\"team\"][\"name\"]:30s} {t[\"playedGames\"]:3d} {t[\"won\"]:3d} {t[\"draw\"]:3d} {t[\"lost\"]:3d} {t[\"points\"]:4d}')
"
```

### Upcoming fixtures for a competition
```bash
curl -s "https://api.football-data.org/v4/competitions/BSA/matches?status=SCHEDULED&limit=10" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for m in data.get('matches', []):
    home = m['homeTeam']['name']
    away = m['awayTeam']['name']
    date = m['utcDate'][:16].replace('T', ' ')
    print(f'{date} — {home} vs {away}')
"
```

### Team search
```bash
curl -s "https://api.football-data.org/v4/competitions/BSA/teams" | python3 -c "
import json, sys
data = json.load(sys.stdin)
for t in data.get('teams', []):
    print(f'{t[\"name\"]} ({t[\"shortName\"]})')
"
```

## Competition Codes

| Code | Competition |
|------|-------------|
| PL   | Premier League |
| PD   | La Liga |
| SA   | Serie A |
| BL1  | Bundesliga |
| FL1  | Ligue 1 |
| BSA  | Brasileirão Série A |
| CL   | Champions League |
| WC   | World Cup |

## Notes

- Free tier: 10 requests/minute, no API key needed
- Brasileirão code is `BSA`
- Dates are in UTC — adjust for user's timezone
- Use `status=SCHEDULED` for upcoming, `status=FINISHED` for results
