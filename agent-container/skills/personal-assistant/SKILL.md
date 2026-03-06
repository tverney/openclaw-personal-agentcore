---
name: personal-assistant
description: "Personal daily briefing and productivity assistant. Use when a user asks for a daily summary, morning briefing, or wants a productivity overview combining weather, reminders, and news."
metadata: { "openclaw": { "emoji": "🤖", "requires": { "bins": ["curl", "bash"] } } }
---

# Personal Assistant

Daily briefing and productivity assistant that combines multiple data sources.

## When to Use

✅ **USE this skill when:**

- User asks for a "daily briefing" or "morning summary"
- User asks "what's on my plate today?"
- User asks for a productivity overview
- User wants a combined summary of weather + reminders + news

❌ **DON'T use this skill when:**

- User asks about a single specific topic (use the dedicated skill instead)

## Daily Briefing Workflow

When asked for a daily briefing, combine these steps:

### 1. Weather
```bash
curl -s "wttr.in/?format=%l:+%C+%t+%h+%w"
```

### 2. Pending reminders
```bash
grep -l "Status: pending" /openclaw-app/data/notes/reminder_* 2>/dev/null | while read f; do cat "$f"; echo "---"; done
```

### 3. Recent notes (last 3 days)
```bash
find /openclaw-app/data/notes/note_* -mtime -3 2>/dev/null | while read f; do echo "=== $(basename $f) ==="; head -5 "$f"; echo; done
```

### 4. Stock watchlist summary (if configured)
```bash
cat /openclaw-app/data/stocks/watchlist.json 2>/dev/null
```

### 5. News headlines (via Tavily if available)
```bash
python3 /openclaw-app/skills/tavily/tavily_search.py "top news today" --topic news --max-results 5 2>/dev/null
```

## Response Format

Present the briefing in a friendly, concise format:

```
🌅 Good morning! Here's your briefing:

🌤️ Weather: [conditions]
📝 Reminders: [pending items]
📊 Stocks: [watchlist summary]
📰 Headlines: [top 3-5 news items]

Have a great day! 🦞
```

## Notes

- This is an orchestration skill — it calls other skills' data sources
- Adapt the briefing based on what data is available
- If a data source fails, skip it gracefully and mention the others
- Sign off as Lobby 🦞
