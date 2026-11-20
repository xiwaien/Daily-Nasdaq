"""Fetch daily Nasdaq indices and core technology stock metrics from Yahoo Finance."""

from datetime import datetime, timezone
import json
import math
import statistics
import urllib.parse
import urllib.request

SYMBOLS = {
    "Indices": [
        ("^IXIC", "Nasdaq Composite"),
        ("^NDX", "Nasdaq-100"),
        ("^SOX", "PHLX Semiconductor"),
        ("^GSPC", "S&P 500"),
    ],
    "Mega-Cap Tech": [
        ("AAPL", "Apple"),
        ("MSFT", "Microsoft"),
        ("NVDA", "NVIDIA"),
        ("AMZN", "Amazon"),
        ("GOOGL", "Alphabet"),
        ("META", "Meta Platforms"),
        ("TSLA", "Tesla"),
    ],
    "Semiconductors": [
        ("AVGO", "Broadcom"),
        ("AMD", "AMD"),
        ("QCOM", "Qualcomm"),
        ("MU", "Micron Technology"),
        ("ASML", "ASML Holding"),
        ("INTC", "Intel"),
    ],
    "Software & Growth": [
        ("NFLX", "Netflix"),
        ("ADBE", "Adobe"),
        ("PANW", "Palo Alto Networks"),
        ("CRWD", "CrowdStrike"),
        ("PLTR", "Palantir"),
        ("SNPS", "Synopsys"),
    ],
}


def fetch_symbol(symbol: str, name: str, category: str) -> dict:
    """Fetch 6mo daily OHLCV from Yahoo Finance chart API and compute metrics."""
    encoded = urllib.parse.quote(symbol, safe="")
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}?range=6mo&interval=1d"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    result = payload["chart"]["result"][0]
    meta = result["meta"]
    timestamps = result["timestamp"]
    quote = result["indicators"]["quote"][0]
    closes_raw = quote["close"]
    volumes_raw = quote["volume"]

    # Filter out any trailing/intermediate None entries
    rows = [
        (ts, c, v)
        for ts, c, v in zip(timestamps, closes_raw, volumes_raw)
        if c is not None
    ]
    closes = [r[1] for r in rows]
    volumes = [r[2] if r[2] is not None else 0 for r in rows]
    last_ts = rows[-1][0]
    last_date = datetime.fromtimestamp(last_ts, tz=timezone.utc).strftime("%Y-%m-%d")

    last_close = closes[-1]
    prev_close = closes[-2]
    chg_1d = (last_close - prev_close) / prev_close * 100.0
    chg_5d = (last_close - closes[-6]) / closes[-6] * 100.0 if len(closes) >= 6 else None
    chg_20d = (last_close - closes[-21]) / closes[-21] * 100.0 if len(closes) >= 21 else None

    ma20 = statistics.mean(closes[-20:]) if len(closes) >= 20 else None
    ma50 = statistics.mean(closes[-50:]) if len(closes) >= 50 else None
    dist_ma20 = (last_close - ma20) / ma20 * 100.0 if ma20 else None
    dist_ma50 = (last_close - ma50) / ma50 * 100.0 if ma50 else None

    avg_vol20 = statistics.mean(volumes[-21:-1]) if len(volumes) >= 21 else None
    rel_vol = (volumes[-1] / avg_vol20) if (avg_vol20 and avg_vol20 > 0) else None

    # 20-day annualized volatility (%)
    vol_20d = None
    if len(closes) >= 21:
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(-20, 0)]
        vol_20d = statistics.stdev(rets) * math.sqrt(252) * 100.0

    high_52w = meta.get("fiftyTwoWeekHigh")
    low_52w = meta.get("fiftyTwoWeekLow")
    dist_52w_high = (last_close - high_52w) / high_52w * 100.0 if high_52w else None

    return {
        "category": category,
        "symbol": symbol,
        "name": name,
        "date": last_date,
        "close": round(last_close, 2),
        "chg_1d_pct": round(chg_1d, 2),
        "chg_5d_pct": round(chg_5d, 2) if chg_5d is not None else None,
        "chg_20d_pct": round(chg_20d, 2) if chg_20d is not None else None,
        "ma20": round(ma20, 2) if ma20 is not None else None,
        "dist_ma20_pct": round(dist_ma20, 2) if dist_ma20 is not None else None,
        "ma50": round(ma50, 2) if ma50 is not None else None,
        "dist_ma50_pct": round(dist_ma50, 2) if dist_ma50 is not None else None,
        "volume": volumes[-1],
        "rel_vol_20d": round(rel_vol, 2) if rel_vol is not None else None,
        "ann_vol_20d_pct": round(vol_20d, 2) if vol_20d is not None else None,
        "high_52w": round(high_52w, 2) if high_52w else None,
        "dist_52w_high_pct": round(dist_52w_high, 2) if dist_52w_high is not None else None,
    }


def main() -> None:
    results = []
    errors = []
    for category, items in SYMBOLS.items():
        for symbol, name in items:
            try:
                results.append(fetch_symbol(symbol, name, category))
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})
    print(json.dumps({"data": results, "errors": errors}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
