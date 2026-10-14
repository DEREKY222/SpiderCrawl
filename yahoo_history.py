"""
yahoo_history.py - daily closing prices for a stock from Yahoo Finance, using the spider.

Usage examples:
    python yahoo_history.py SPCX                 # last month of closes -> SPCX_close.csv
    python yahoo_history.py SPCX --months 3
    python yahoo_history.py TSLA --out tesla.csv --live

It crawls a single page, Yahoo's "Historical Data" table for the symbol, limited to the
requested window, and saves the date and closing price for each trading day (oldest first).
"""

import argparse
import calendar
import csv
import sys
import time
import webbrowser
from datetime import date, datetime, timedelta, timezone

from spider import DEFAULT_UA, LiveFeed, Spider, start_live_server


def months_ago(d, n):
    y, m = divmod(d.year * 12 + d.month - 1 - n, 12)
    m += 1
    return date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def to_epoch(d):
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


def number(text):
    try:
        return float(text.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def main():
    p = argparse.ArgumentParser(description="Daily closing prices from Yahoo Finance.")
    p.add_argument("symbol", help="Ticker symbol, e.g. SPCX")
    p.add_argument("--months", type=int, default=1, help="How many months back (default 1)")
    p.add_argument("--out", help="CSV file to write (default <SYMBOL>_close.csv)")
    p.add_argument("--live", action="store_true", help="Show the spider's live view in your browser")
    p.add_argument("--port", type=int, default=8765)
    args = p.parse_args()

    symbol = args.symbol.upper()
    end = date.today()
    start = months_ago(end, args.months)
    url = (f"https://finance.yahoo.com/quote/{symbol}/history/"
           f"?period1={to_epoch(start)}&period2={to_epoch(end + timedelta(days=1))}")

    spider = Spider(
        start_urls=[url], max_pages=1, max_depth=0, delay=0, allow_external=False,
        ignore_robots=False, include=None, exclude=None, selectors={}, timeout=20,
        user_agent=DEFAULT_UA, tables={"history": "table"},
    )
    if args.live:
        feed = LiveFeed()
        spider.emit = feed.push
        webbrowser.open(start_live_server(feed, args.port))
        time.sleep(1.5)

    results = spider.crawl()
    rows = results[0].get("history") if results else None
    if not rows:
        reason = results[0].get("error") if results else "the page was skipped (see message above)"
        sys.exit(f"No price table found for {symbol}: {reason or 'check the symbol on finance.yahoo.com'}")

    prices = []
    for row in rows:
        close = number(row.get("Close"))
        try:
            day = datetime.strptime(row.get("Date", ""), "%b %d, %Y").date()
        except ValueError:
            continue
        if close is not None and start <= day <= end:
            prices.append((day, close))
    prices.sort()
    if not prices:
        sys.exit(f"Yahoo returned a table for {symbol}, but no closing prices between {start} and {end}.")

    out = args.out or f"{symbol}_close.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "close"])
        w.writerows((d.isoformat(), f"{c:.2f}") for d, c in prices)

    for d, c in prices:
        print(f"{d}  {c:>10.2f}")
    first, last = prices[0][1], prices[-1][1]
    closes = [c for _, c in prices]
    print(f"\n{symbol}: {len(prices)} trading days, {prices[0][0]} to {prices[-1][0]}")
    print(f"Close went from {first:.2f} to {last:.2f} ({(last - first) / first:+.2%}); "
          f"high {max(closes):.2f}, low {min(closes):.2f}")
    print(f"Saved to {out}")

    if args.live:
        spider.emit({"type": "done", "pages": 1, "out": out, "stopped": False})
        print("Live view is still open. Press Ctrl+C to exit.", file=sys.stderr)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
