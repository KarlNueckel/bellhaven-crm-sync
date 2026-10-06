"""Crawl the Bellhaven public site and store every community detail page.

We crawl every internal link starting from the homepage and the directory,
rather than only walking the paginated directory, because at least one
community is linked only from the homepage.
"""
import json
import re
from collections import deque
from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from config import SITE_BASE
from db import connect

DETAIL_PATH = re.compile(r"^/communities/([a-z0-9-]+)/?$")
CITY_STATE_ZIP = re.compile(r"^(?P<city>.+?),\s*(?P<state>[A-Z]{2})\s+(?P<zip>\d{5}(?:-\d{4})?)$")
MAX_PAGES = 300


def crawl(session=None):
    """Breadth-first crawl of same-host pages. Returns {detail_url: [pages that linked to it]}."""
    session = session or requests.Session()
    host = urlparse(SITE_BASE).netloc
    queue = deque([f"{SITE_BASE}/", f"{SITE_BASE}/communities"])
    seen = set(queue)
    details = {}

    while queue and len(seen) < MAX_PAGES:
        page_url = queue.popleft()
        resp = session.get(page_url, timeout=20)
        if resp.status_code != 200 or "text/html" not in resp.headers.get("content-type", ""):
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        for a in soup.find_all("a", href=True):
            url = urljoin(page_url, a["href"]).split("#")[0]
            parsed = urlparse(url)
            if parsed.netloc != host or parsed.path.startswith("/api"):
                continue
            if DETAIL_PATH.match(parsed.path):
                details.setdefault(url, [])
                if page_url not in details[url]:
                    details[url].append(page_url)
            elif url not in seen:  # listing pages, pagination, about, etc.
                seen.add(url)
                queue.append(url)
    return details


def parse_detail(html, url):
    """Pull the fields out of a community detail page's <dl class="detail">."""
    soup = BeautifulSoup(html, "html.parser")
    fields = {}
    dl = soup.find("dl", class_="detail")
    for dt in dl.find_all("dt"):
        fields[dt.get_text(strip=True).lower()] = dt.find_next_sibling("dd")

    # Address is "street<br>City, ST 12345"
    street = city = state = zip_code = None
    if fields.get("address"):
        lines = [s.strip() for s in fields["address"].stripped_strings]
        street = lines[0] if lines else None
        m = CITY_STATE_ZIP.match(lines[-1]) if len(lines) > 1 else None
        if m:
            city, state, zip_code = m["city"], m["state"], m["zip"]

    care = []
    if fields.get("care offerings"):
        care = [b.get_text(strip=True) for b in fields["care offerings"].find_all(class_="badge")]

    def text(key):
        return fields[key].get_text(" ", strip=True) if fields.get(key) else None

    return {
        "slug": DETAIL_PATH.match(urlparse(url).path).group(1),
        "url": url,
        "name": soup.find("h1").get_text(strip=True),
        "street": street,
        "city": city,
        "state": state,
        "zip": zip_code,
        "care_offerings": care,
        "administrator": text("administrator"),
        "phone": text("phone"),
    }


def scrape(db_path=None):
    """Crawl, parse, and replace the site_locations snapshot. Returns the parsed rows."""
    session = requests.Session()
    details = crawl(session)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows = []
    for url, found_on in sorted(details.items()):
        resp = session.get(url, timeout=20)
        resp.raise_for_status()
        row = parse_detail(resp.text, url)
        row["found_on"] = found_on
        rows.append(row)

    conn = connect(db_path) if db_path else connect()
    with conn:
        conn.execute("DELETE FROM site_locations")
        conn.executemany(
            """INSERT INTO site_locations
               (slug, url, name, street, city, state, zip, care_offerings,
                administrator, phone, found_on, scraped_at)
               VALUES (:slug, :url, :name, :street, :city, :state, :zip, :care,
                       :administrator, :phone, :found, :scraped_at)""",
            [{**r, "care": json.dumps(r["care_offerings"]), "found": json.dumps(r["found_on"]),
              "scraped_at": now} for r in rows],
        )
    conn.close()
    return rows
