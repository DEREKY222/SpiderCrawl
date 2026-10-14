"""
spider.py - a small, polite web crawler that extracts page information.

Usage examples:
    python spider.py https://example.com
    python spider.py https://quotes.toscrape.com --max-pages 50 --depth 3 --out results.json
    python spider.py https://example.com --select "price=.product .price" --select "name=h1"
    python spider.py https://example.com --format csv --out pages.csv
    python spider.py https://quotes.toscrape.com --live      # animated view in your browser
    python spider.py "https://finance.yahoo.com/quote/SPCX/history/" --depth 0 --table "history=table"

What it does:
  * Breadth-first crawl starting from one or more URLs
  * Stays on the starting domain(s) unless --allow-external is given
  * Respects robots.txt (disable with --ignore-robots only for sites you own)
  * Waits --delay seconds between requests
  * For each HTML page extracts: url, status, title, meta description,
    h1/h2 headings, visible text snippet, word count, links, images,
    plus any custom CSS-selector fields you pass with --select, and HTML tables
    you pass with --table (each also saved to its own CSV)
  * Writes JSON (default), JSONL, or CSV
  * --live opens a browser page showing an animated spider crawling the
    site in real time, with extracted data streaming into a side panel
"""

import argparse
import csv
import json
import re
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urldefrag, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

DEFAULT_UA = "SimpleSpider/1.0 (+personal research crawler)"
SKIP_EXTENSIONS = re.compile(
    r"\.(jpg|jpeg|png|gif|webp|svg|ico|pdf|zip|rar|7z|gz|tar|mp3|mp4|avi|mov|wmv|"
    r"exe|msi|dmg|css|js|woff2?|ttf|eot|xml|json)$",
    re.IGNORECASE,
)


def normalize(url):
    url, _ = urldefrag(url)
    parsed = urlparse(url)
    path = parsed.path.rstrip("/") or "/"
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(),
                           path=path).geturl()


def parse_table(table):
    """Turn an HTML table into a list of {header: cell} dicts.

    Header text is the first text in each <th>, so tooltips and icons inside headers are
    ignored. Rows whose cell count doesn't match the header (e.g. a dividend note spanning
    the whole row) are skipped.
    """
    if table is None:
        return []
    rows = table.find_all("tr")
    header_row = next((r for r in rows if r.find("th")), None)
    if header_row is None:
        return []
    headers = [next(th.stripped_strings, "") for th in header_row.find_all(["th", "td"])]
    out = []
    for tr in rows:
        if tr is header_row:
            continue
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        if len(cells) == len(headers):
            out.append(dict(zip(headers, cells)))
    return out


def summarize_table(rows):
    if not rows:
        return "no rows found"
    first = ", ".join(f"{k} {v}" for k, v in rows[0].items())
    return f"{len(rows)} rows. First: {first}"


class Spider:
    def __init__(self, start_urls, max_pages, max_depth, delay, allow_external,
                 ignore_robots, include, exclude, selectors, timeout, user_agent, tables=None):
        self.start_urls = [normalize(u) for u in start_urls]
        self.allowed_hosts = {urlparse(u).netloc for u in self.start_urls}
        self.max_pages = max_pages
        self.max_depth = max_depth
        self.delay = delay
        self.allow_external = allow_external
        self.ignore_robots = ignore_robots
        self.include = re.compile(include) if include else None
        self.exclude = re.compile(exclude) if exclude else None
        self.selectors = selectors
        self.tables = tables or {}
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.robots = {}
        self.seen = set()
        self.results = []
        self.emit = lambda event: None  # replaced by the live view when --live is used

    # ---------- policy ----------
    def can_fetch(self, url):
        if self.ignore_robots:
            return True
        parsed = urlparse(url)
        base = f"{parsed.scheme}://{parsed.netloc}"
        if base not in self.robots:
            rp = RobotFileParser()
            try:
                resp = self.session.get(base + "/robots.txt", timeout=self.timeout)
                rp.parse(resp.text.splitlines() if resp.status_code == 200 else [])
            except requests.RequestException:
                rp.parse([])
            self.robots[base] = rp
        return self.robots[base].can_fetch(self.session.headers["User-Agent"], url)

    def should_follow(self, url):
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False
        if not self.allow_external and parsed.netloc not in self.allowed_hosts:
            return False
        if SKIP_EXTENSIONS.search(parsed.path):
            return False
        if self.include and not self.include.search(url):
            return False
        if self.exclude and self.exclude.search(url):
            return False
        return True

    # ---------- extraction ----------
    def extract(self, url, resp):
        soup = BeautifulSoup(resp.text, "html.parser")

        links = []
        for a in soup.find_all("a", href=True):
            href = normalize(urljoin(url, a["href"].strip()))
            if href.startswith(("http://", "https://")):
                links.append(href)

        images = [urljoin(url, img["src"]) for img in soup.find_all("img", src=True)]

        meta_desc = soup.find("meta", attrs={"name": re.compile("^description$", re.I)})

        for tag in soup(["script", "style", "noscript", "template"]):
            tag.decompose()
        text = re.sub(r"\s+", " ", soup.get_text(" ")).strip()

        record = {
            "url": url,
            "status": resp.status_code,
            "title": soup.title.get_text(strip=True) if soup.title else "",
            "description": meta_desc.get("content", "").strip() if meta_desc else "",
            "h1": [h.get_text(strip=True) for h in soup.find_all("h1")],
            "h2": [h.get_text(strip=True) for h in soup.find_all("h2")],
            "word_count": len(text.split()),
            "text_snippet": text[:500],
            "links": sorted(set(links)),
            "images": sorted(set(images)),
        }

        for name, css in self.selectors.items():
            found = [el.get_text(" ", strip=True) for el in soup.select(css)]
            record[name] = found[0] if len(found) == 1 else found

        for name, css in self.tables.items():
            record[name] = parse_table(soup.select_one(css))

        return record, links

    # ---------- main loop ----------
    def crawl(self):
        queue = deque((u, 0, None) for u in self.start_urls)
        self.seen.update(self.start_urls)
        for u in self.start_urls:
            self.emit({"type": "queue", "url": u, "parent": None, "depth": 0})

        while queue and len(self.results) < self.max_pages:
            url, depth, parent = queue.popleft()
            self.emit({"type": "fetch", "url": url, "parent": parent, "depth": depth})

            if not self.can_fetch(url):
                print(f"[robots] skip {url}", file=sys.stderr)
                self.emit({"type": "skip", "url": url, "reason": "blocked by robots.txt"})
                continue

            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                print(f"[error] {url}: {e}", file=sys.stderr)
                self.results.append({"url": url, "status": None, "error": str(e)})
                self.emit({"type": "error", "url": url, "error": str(e)})
                continue

            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype:
                print(f"[skip]  {url} ({ctype})", file=sys.stderr)
                self.emit({"type": "skip", "url": url, "reason": ctype or "not HTML"})
                continue

            record, links = self.extract(resp.url, resp)
            record["depth"] = depth
            self.results.append(record)
            print(f"[{len(self.results):>4}] d={depth} {resp.status_code} {url} - {record['title'][:60]}",
                  file=sys.stderr)
            self.emit({
                "type": "visit",
                "url": url,
                "final_url": record["url"],
                "status": record["status"],
                "title": record["title"],
                "description": record["description"],
                "h1": record["h1"][:3],
                "word_count": record["word_count"],
                "links": len(record["links"]),
                "images": len(record["images"]),
                "depth": depth,
                "fields": {**{name: record[name] for name in self.selectors},
                           **{name: summarize_table(record[name]) for name in self.tables}},
            })

            if depth < self.max_depth:
                for link in links:
                    if link not in self.seen and self.should_follow(link):
                        self.seen.add(link)
                        queue.append((link, depth + 1, url))
                        self.emit({"type": "queue", "url": link, "parent": url, "depth": depth + 1})

            time.sleep(self.delay)

        return self.results


class LiveFeed:
    """Thread-safe event log that browser clients stream from."""

    def __init__(self):
        self.events = []
        self.cond = threading.Condition()

    def push(self, event):
        with self.cond:
            event["id"] = len(self.events)
            self.events.append(event)
            self.cond.notify_all()

    def wait_since(self, idx, timeout=15):
        with self.cond:
            self.cond.wait_for(lambda: len(self.events) > idx, timeout=timeout)
            return self.events[idx:]


def start_live_server(feed, port):
    page = Path(__file__).with_name("spider_live.html").read_bytes()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)
            elif self.path == "/events":
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                try:
                    idx = int(self.headers.get("Last-Event-ID", -1)) + 1
                except ValueError:
                    idx = 0
                try:
                    while True:
                        batch = feed.wait_since(idx)
                        if batch:
                            idx += len(batch)
                            chunk = "".join(f"id: {e['id']}\ndata: {json.dumps(e, ensure_ascii=False)}\n\n"
                                            for e in batch)
                        else:
                            chunk = ": ping\n\n"
                        self.wfile.write(chunk.encode("utf-8"))
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    return
            else:
                self.send_error(404)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{server.server_address[1]}/"


def save(results, path, fmt):
    if fmt == "json":
        with open(path, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
    elif fmt == "jsonl":
        with open(path, "w", encoding="utf-8") as f:
            for r in results:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    elif fmt == "csv":
        keys = []
        for r in results:
            keys.extend(k for k in r if k not in keys)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in results:
                w.writerow({k: " | ".join(map(str, v)) if isinstance(v, list) else v
                            for k, v in r.items()})


def save_tables(results, tables, out):
    """Write each --table to <out stem>.<name>.csv; adds a url column when several pages had it."""
    paths = []
    for name in tables:
        pages = [r for r in results if r.get(name)]
        rows = [({"url": r["url"]} if len(pages) > 1 else {}) | row for r in pages for row in r[name]]
        if not rows:
            continue
        path = Path(out).with_suffix(f".{name}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
        paths.append((path, len(rows)))
    return paths


def parse_selectors(items, flag="--select"):
    out = {}
    for item in items or []:
        if "=" not in item:
            sys.exit(f"{flag} must look like name=css-selector, got: {item}")
        name, css = item.split("=", 1)
        out[name.strip()] = css.strip()
    return out


def main():
    p = argparse.ArgumentParser(description="Polite web crawler that extracts page information.")
    p.add_argument("urls", nargs="+", help="Start URL(s)")
    p.add_argument("--max-pages", type=int, default=30, help="Stop after this many pages (default 30)")
    p.add_argument("--depth", type=int, default=2, help="Max link depth from start (default 2)")
    p.add_argument("--delay", type=float, default=1.0, help="Seconds between requests (default 1.0)")
    p.add_argument("--allow-external", action="store_true", help="Follow links to other domains")
    p.add_argument("--ignore-robots", action="store_true", help="Do not check robots.txt")
    p.add_argument("--include", help="Only follow URLs matching this regex")
    p.add_argument("--exclude", help="Skip URLs matching this regex")
    p.add_argument("--select", action="append", metavar="NAME=CSS",
                   help="Extra field from a CSS selector; repeatable")
    p.add_argument("--table", action="append", metavar="NAME=CSS",
                   help="Extract an HTML table as rows (also saved to <out>.<NAME>.csv); repeatable")
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--user-agent", default=DEFAULT_UA)
    p.add_argument("--format", choices=["json", "jsonl", "csv"], default="json")
    p.add_argument("--out", default=None, help="Output file (default results.<format>)")
    p.add_argument("--live", action="store_true", help="Show an animated live view in your browser")
    p.add_argument("--port", type=int, default=8765, help="Port for --live (default 8765)")
    p.add_argument("--no-browser", action="store_true", help="With --live, don't auto-open the browser")
    args = p.parse_args()

    spider = Spider(
        start_urls=args.urls,
        max_pages=args.max_pages,
        max_depth=args.depth,
        delay=args.delay,
        allow_external=args.allow_external,
        ignore_robots=args.ignore_robots,
        include=args.include,
        exclude=args.exclude,
        selectors=parse_selectors(args.select),
        timeout=args.timeout,
        user_agent=args.user_agent,
        tables=parse_selectors(args.table, "--table"),
    )
    out = args.out or f"results.{args.format}"

    if args.live:
        feed = LiveFeed()
        spider.emit = feed.push
        url = start_live_server(feed, args.port)
        print(f"Live view: {url}", file=sys.stderr)
        if not args.no_browser:
            webbrowser.open(url)
        time.sleep(1.5)  # give the page a moment to connect before the spider sets off

    stopped = False
    try:
        results = spider.crawl()
    except KeyboardInterrupt:
        stopped = True
        results = spider.results
        print("\nStopped by user - saving what was collected so far.", file=sys.stderr)

    save(results, out, args.format)
    for path, n in save_tables(results, spider.tables, out):
        print(f"Table: {n} rows -> {path}", file=sys.stderr)
    spider.emit({"type": "done", "pages": len(results), "out": out, "stopped": stopped})
    print(f"\nDone: {len(results)} pages -> {out}", file=sys.stderr)

    if args.live:
        print("Live view is still open. Press Ctrl+C to exit.", file=sys.stderr)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
