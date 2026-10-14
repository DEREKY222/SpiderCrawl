# Spider Crawler

A polite web crawler that extracts page information, with an optional live
animation of a spider crawling the site in your browser.

## Files

| File | Purpose |
|---|---|
| `spider.py` | The crawler (run this) |
| `yahoo_history.py` | Daily closing prices for a stock from Yahoo Finance (uses the spider) |
| `spider_live.html` | The live animation page — keep it in the same folder as `spider.py` |
| `requirements.txt` | Python packages needed |

## 1. One-time setup

Open PowerShell and go to this folder:

```
cd E:\Py\spider_crawler
```

Install the two packages it needs (already installed on this PC, but harmless to re-run):

```
python -m pip install -r requirements.txt
```

## 2. Web scraping (results saved to a file)

Basic crawl — saves `results.json` in this folder:

```
python spider.py https://quotes.toscrape.com
```

Crawl more pages, deeper, to a named file:

```
python spider.py https://quotes.toscrape.com --max-pages 50 --depth 3 --out quotes.json
```

Save as CSV (opens in Excel):

```
python spider.py https://quotes.toscrape.com --format csv --out quotes.csv
```

### Extract specific information with `--select`

`--select name=CSS-selector` adds a column/field called `name` containing the
text of every element matching the CSS selector. Repeat it for several fields:

```
python spider.py https://quotes.toscrape.com --select "quote=.quote .text" --select "author=.quote .author" --format csv --out quotes.csv
```

To find a selector for a site: open the page in Chrome, right-click the item
you want → **Inspect**, then right-click the highlighted HTML → **Copy → Copy selector**
(or use its class, e.g. `.price`).

### Extract a table with `--table`

`--table name=CSS-selector` turns an HTML table into rows, using the table's
header cells as column names. Besides the normal output, each table is saved to
`<out>.<name>.csv`:

```
python spider.py "https://finance.yahoo.com/quote/SPCX/history/" --depth 0 --table "history=table" --out spcx.json
```

That writes `spcx.history.csv` with Date, Open, High, Low, Close, Adj Close and Volume.

### Stock closing prices from Yahoo Finance

`yahoo_history.py` crawls Yahoo's Historical Data page for one symbol and saves
the date and closing price for every trading day in the window:

```
python yahoo_history.py SPCX
```

- Default window is the last month; use `--months 3` for longer.
- Saves `SPCX_close.csv` (change with `--out prices.csv`) and prints the prices
  with the change, high and low.
- Add `--live` to watch the spider fetch the page.

## 3. Live animation

Add `--live` to any command. A browser tab opens showing the spider walking
across a web of pages while it crawls, with extracted data streaming into the
side panel:

```
python spider.py https://quotes.toscrape.com --live --select "quote=.quote .text"
```

- If the browser doesn't open by itself, go to http://127.0.0.1:8765/
- After the crawl finishes, the page stays open — press **Ctrl+C** in PowerShell to exit.
- If port 8765 is busy, add `--port 8899` (and open http://127.0.0.1:8899/).
- Hover over any dot to see that page's details.

Colors: gold = fetching, aqua = extracted (bigger = more words),
rose = error, grey = skipped, hollow = waiting in queue.

## All options

| Option | Default | Meaning |
|---|---|---|
| `--max-pages N` | 30 | Stop after N pages |
| `--depth N` | 2 | How many clicks away from the start page to go |
| `--delay S` | 1.0 | Seconds to wait between requests (be polite) |
| `--select NAME=CSS` | — | Extra field to extract; repeatable |
| `--table NAME=CSS` | — | HTML table to extract as rows, also saved to `<out>.<NAME>.csv`; repeatable |
| `--include REGEX` | — | Only follow links matching this pattern, e.g. `"/tag/"` |
| `--exclude REGEX` | — | Skip links matching this pattern, e.g. `"login\|logout"` |
| `--allow-external` | off | Also follow links to other websites |
| `--ignore-robots` | off | Ignore robots.txt (only for sites you own) |
| `--format` | json | `json`, `jsonl` or `csv` |
| `--out FILE` | results.&lt;format&gt; | Output file name |
| `--live` | off | Show the live animation |
| `--port N` | 8765 | Port for the live view |
| `--no-browser` | off | With `--live`, don't open the browser automatically |

Press **Ctrl+C** at any time to stop a crawl early; whatever was collected is still saved.

## Limitations

- Sees only the HTML the server sends; content that a site loads later with
  JavaScript won't be captured.
- Doesn't log in to sites.
- Check a site's terms of service before crawling, and keep a polite `--delay`.
