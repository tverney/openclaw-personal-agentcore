---
name: my-weather
description: "Get current weather using wttr.in (no API key required). Use when a user asks about weather, temperature, forecast, or conditions for any location."
metadata: { "openclaw": { "emoji": "🌤️", "requires": { "bins": ["curl"] } } }
---

# My Weather

Get current weather and forecasts using wttr.in — no API key needed.

## When to Use

✅ **USE this skill when:**

- User asks about current weather or temperature
- User asks for a weather forecast
- User asks "what's the weather in [city]?"
- User asks about rain, wind, humidity, or conditions

❌ **DON'T use this skill when:**

- User needs historical weather data
- User needs hyper-precise meteorological data

## Commands

### Current weather (concise)
```bash
curl -s "wttr.in/São Paulo?format=%l:+%C+%t+%h+%w"
```

### Full forecast (3 days)
```bash
curl -s "wttr.in/São Paulo?lang=pt"
```

### One-line summary
```bash
curl -s "wttr.in/São Paulo?format=3"
```

### Specific day forecast (today=0, tomorrow=1, day after=2)
```bash
curl -s "wttr.in/São Paulo?1"
```

### JSON format (for parsing)
```bash
curl -s "wttr.in/São Paulo?format=j1"
```

### Moon phase
```bash
curl -s "wttr.in/Moon"
```

## Format Codes

- `%C` — Weather condition text
- `%t` — Temperature
- `%f` — Feels like
- `%h` — Humidity
- `%w` — Wind
- `%p` — Precipitation
- `%P` — Pressure
- `%S` — Sunrise
- `%s` — Sunset

## Notes

- Replace spaces in city names with `+` or use URL encoding
- Add `?lang=pt` for Portuguese output
- No API key required — works out of the box
