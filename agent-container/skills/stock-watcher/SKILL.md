---
name: stock-watcher
description: "Manage and monitor a personal stock watchlist. Use when a user asks about stock prices, wants to add/remove stocks from their watchlist, or get a portfolio summary."
metadata: { "openclaw": { "emoji": "📈", "requires": { "bins": ["curl", "python3"] } } }
---

# Stock Watcher

Personal stock watchlist with real-time quotes via Yahoo Finance API (no key needed).

## When to Use

✅ **USE this skill when:**

- User asks about stock prices or quotes
- User asks to add/remove stocks from watchlist
- User asks for a watchlist summary
- User says "how's the market?", "check my stocks", "what's AAPL at?"

❌ **DON'T use this skill when:**

- User wants to execute trades (this is read-only)
- User needs deep financial analysis (use Tavily search instead)

## Storage

Watchlist stored at `/openclaw-app/data/stocks/watchlist.json`

## Commands

### Get a stock quote
```bash
curl -s "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=1d&interval=1d" | python3 -c "
import json, sys
data = json.load(sys.stdin)
result = data['chart']['result'][0]
meta = result['meta']
price = meta['regularMarketPrice']
prev = meta['chartPreviousClose']
change = price - prev
pct = (change / prev) * 100
symbol = meta['symbol']
currency = meta['currency']
arrow = '🟢' if change >= 0 else '🔴'
print(f'{arrow} {symbol}: {currency} {price:.2f} ({change:+.2f} / {pct:+.2f}%)')
"
```

### Get multiple quotes
```bash
for ticker in AAPL MSFT GOOGL AMZN; do
  curl -s "https://query1.finance.yahoo.com/v8/finance/chart/${ticker}?range=1d&interval=1d" | python3 -c "
import json, sys
data = json.load(sys.stdin)
r = data['chart']['result'][0]['meta']
p, c = r['regularMarketPrice'], r['chartPreviousClose']
ch = p - c; pct = (ch/c)*100
arrow = '🟢' if ch >= 0 else '🔴'
print(f'{arrow} {r[\"symbol\"]:6s} {r[\"currency\"]} {p:>10.2f} ({ch:+.2f} / {pct:+.2f}%)')
" 2>/dev/null
done
```

### Add to watchlist
```bash
mkdir -p /openclaw-app/data/stocks
python3 -c "
import json, os
path = '/openclaw-app/data/stocks/watchlist.json'
wl = json.load(open(path)) if os.path.exists(path) else {'stocks': []}
ticker = 'AAPL'  # replace with actual ticker
if ticker not in wl['stocks']:
    wl['stocks'].append(ticker)
    json.dump(wl, open(path, 'w'), indent=2)
    print(f'Added {ticker} to watchlist')
else:
    print(f'{ticker} already in watchlist')
"
```

### Remove from watchlist
```bash
python3 -c "
import json, os
path = '/openclaw-app/data/stocks/watchlist.json'
wl = json.load(open(path)) if os.path.exists(path) else {'stocks': []}
ticker = 'AAPL'  # replace with actual ticker
if ticker in wl['stocks']:
    wl['stocks'].remove(ticker)
    json.dump(wl, open(path, 'w'), indent=2)
    print(f'Removed {ticker}')
else:
    print(f'{ticker} not in watchlist')
"
```

### Show watchlist with live prices
```bash
python3 -c "
import json, os, subprocess
path = '/openclaw-app/data/stocks/watchlist.json'
if not os.path.exists(path):
    print('Watchlist is empty. Add stocks first.')
else:
    wl = json.load(open(path))
    for ticker in wl.get('stocks', []):
        result = subprocess.run(
            ['curl', '-s', f'https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d'],
            capture_output=True, text=True
        )
        try:
            data = json.loads(result.stdout)
            r = data['chart']['result'][0]['meta']
            p, c = r['regularMarketPrice'], r['chartPreviousClose']
            ch = p - c; pct = (ch/c)*100
            arrow = '🟢' if ch >= 0 else '🔴'
            print(f'{arrow} {r[\"symbol\"]:6s} {r[\"currency\"]} {p:>10.2f} ({ch:+.2f} / {pct:+.2f}%)')
        except:
            print(f'⚠️  {ticker}: failed to fetch')
"
```

### List watchlist tickers
```bash
cat /openclaw-app/data/stocks/watchlist.json 2>/dev/null || echo "No watchlist configured"
```

## Common Tickers

| Ticker | Company |
|--------|---------|
| AAPL   | Apple |
| MSFT   | Microsoft |
| GOOGL  | Alphabet |
| AMZN   | Amazon |
| NVDA   | NVIDIA |
| PETR4.SA | Petrobras |
| VALE3.SA | Vale |
| ITUB4.SA | Itaú Unibanco |

## Notes

- Yahoo Finance API is free, no key needed
- Brazilian stocks use `.SA` suffix (e.g., `PETR4.SA`)
- Watchlist persists in `/openclaw-app/data/stocks/`
- Rate limit: be reasonable, don't hammer the API
- Prices are delayed ~15 minutes for most exchanges
