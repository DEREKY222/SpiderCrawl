"""
spider.py - a small, polite web crawler that extracts page information.

Usage examples:
    python spider.py https://example.com
    python spider.py https://quotes.toscrape.com --max-pages 50 --depth 3 --out results.json
    python spider.py https://example.com --select "price=.product .price" --select "name=h1"
    python spider.py https://example.com --format csv --out pages.csv

What it does:
  * Breadth-first crawl starting from one or more URLs
  * Stays on the starting domain(s) unless --allow-external is given
  * Respects robots.txt (disable with --ignore-robots only for sites you own)
  * Waits --delay seconds between requests
  * For each HTML page extracts: url, status, title, meta description,
    h1/h2 headings, visible text snippet, word count, links, images,
    plus any custom CSS-selector fields you pass with --select
  * Writes JSON (default), JSONL, or CSV
"""

import argparse
import csv
import json
import re
import sys
import time
from collections import deque
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


class Spider:
    def __init__(self, start_urls, max_pages, max_depth, delay, allow_external,
                 ignore_robots, include, exclude, selectors, timeout, user_agent):
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
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.robots = {}
        self.seen = set()
        self.results = []

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


        return record, links

    # ---------- main loop ----------
    def crawl(self):
        queue = deque((u, 0) for u in self.start_urls)
        self.seen.update(self.start_urls)

        while queue and len(self.results) < self.max_pages:
            url, depth = queue.popleft()

            if not self.can_fetch(url):
                print(f"[robots] skip {url}", file=sys.stderr)
                continue

            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as e:
                print(f"[error] {url}: {e}", file=sys.stderr)
                self.results.append({"url": url, "status": None, "error": str(e)})
                continue

            ctype = resp.headers.get("Content-Type", "")
            if "html" not in ctype:
                print(f"[skip]  {url} ({ctype})", file=sys.stderr)
                continue

            record, links = self.extract(resp.url, resp)
            record["depth"] = depth
            self.results.append(record)
            print(f"[{len(self.results):>4}] d={depth} {resp.status_code} {url} - {record['title'][:60]}",
                  file=sys.stderr)

            if depth < self.max_depth:
                for link in links:
                    if link not in self.seen and self.should_follow(link):
                        self.seen.add(link)
                        queue.append((link, depth + 1))

            time.sleep(self.delay)

        return self.results


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


def parse_selectors(items):
    out = {}
    for item in items or []:
        if "=" not in item:
            sys.exit(f"--select must look like name=css-selector, got: {item}")
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
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--user-agent", default=DEFAULT_UA)
    p.add_argument("--format", choices=["json", "jsonl", "csv"], default="json")
    p.add_argument("--out", default=None, help="Output file (default results.<format>)")
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
    )
    results = spider.crawl()
    out = args.out or f"results.{args.format}"
    save(results, out, args.format)
    print(f"\nDone: {len(results)} pages -> {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
