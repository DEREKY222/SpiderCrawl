# Spider Crawler

A polite web crawler that extracts page information.

## Files

| File | Purpose |
|---|---|
| `spider.py` | The crawler (run this) |
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

## All options

| Option | Default | Meaning |
|---|---|---|
| `--max-pages N` | 30 | Stop after N pages |
| `--depth N` | 2 | How many clicks away from the start page to go |
| `--delay S` | 1.0 | Seconds to wait between requests (be polite) |
| `--select NAME=CSS` | — | Extra field to extract; repeatable |
| `--include REGEX` | — | Only follow links matching this pattern, e.g. `"/tag/"` |
| `--exclude REGEX` | — | Skip links matching this pattern, e.g. `"login\|logout"` |
| `--allow-external` | off | Also follow links to other websites |
| `--ignore-robots` | off | Ignore robots.txt (only for sites you own) |
| `--format` | json | `json`, `jsonl` or `csv` |
| `--out FILE` | results.&lt;format&gt; | Output file name |

Press **Ctrl+C** at any time to stop a crawl early; whatever was collected is still saved.

## Limitations

- Sees only the HTML the server sends; content that a site loads later with
  JavaScript won't be captured.
- Doesn't log in to sites.
- Check a site's terms of service before crawling, and keep a polite `--delay`.
