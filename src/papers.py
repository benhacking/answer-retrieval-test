"""Shared helpers for getting research papers from arXiv as clean plain text.

arXiv publishes most recent papers as a web page as well as a PDF. We use
the web page, because its structure tells us what is a paragraph, what is
a heading, and what is a reference list, figure or table.

The cleaning rules below define "the document" for this experiment. Every
model is sent exactly the string that clean_text() returns, and every quote
is checked against that same string.
"""

import hashlib
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "cant-make-it-up/0.1 (small research script; python-requests)"}
API = "https://export.arxiv.org/api/query"
PAUSE = 3.0  # arXiv asks automated clients for about one request every 3 seconds
HTML_CACHE = Path(".cache/arxiv_html")
ATOM = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}

# Parts of the page that are not the paper's own prose.
DROP = (
    ".ltx_bibliography, .ltx_authors, .ltx_figure, .ltx_table, .ltx_note, "
    ".ltx_appendix, .ltx_acknowledgements, .ltx_dates, .ltx_equation, "
    ".ltx_equationgroup, .ltx_listing, .ltx_pagination, .ltx_float, "
    ".ltx_classification, .ltx_keywords, script, style, nav, footer"
)


def _get(url: str, params: dict | None = None) -> requests.Response:
    """One polite request, with waits and retries if the server is busy."""
    for attempt in range(5):
        time.sleep(PAUSE)
        r = requests.get(url, params=params, headers=HEADERS, timeout=60)
        if r.status_code in (429, 500, 502, 503):
            wait = min(float(r.headers.get("Retry-After", 10 * (attempt + 1))), 120)
            print(f"  (server busy, waiting {wait:.0f}s)", flush=True)
            time.sleep(wait)
            continue
        return r
    raise RuntimeError(f"arXiv kept refusing {url}")


def list_papers(category: str, start_date: str, end_date: str) -> list[dict]:
    """Papers in one subject area first submitted between two dates (YYYYMMDD)."""
    papers, start = [], 0
    while True:
        r = _get(
            API,
            {
                "search_query": f"cat:{category} AND submittedDate:[{start_date}0000 TO {end_date}2359]",
                "start": start,
                "max_results": 200,
                "sortBy": "submittedDate",
                "sortOrder": "ascending",
            },
        )
        r.raise_for_status()
        root = ET.fromstring(r.text)
        entries = root.findall("a:entry", ATOM)
        for e in entries:
            full_id = e.findtext("a:id", namespaces=ATOM).rsplit("/", 1)[-1]  # e.g. 2610.00947v1
            arxiv_id, version = full_id.rsplit("v", 1)
            papers.append(
                {
                    "arxiv_id": arxiv_id,
                    "version": int(version),
                    "title": " ".join(e.findtext("a:title", namespaces=ATOM).split()),
                    "abstract": " ".join(e.findtext("a:summary", namespaces=ATOM).split()),
                    "published": e.findtext("a:published", namespaces=ATOM),
                    "primary": e.find("x:primary_category", ATOM).get("term"),
                }
            )
        total = int(root.findtext("{http://a9.com/-/spec/opensearch/1.1/}totalResults"))
        start += 200
        if start >= total or not entries:
            return papers


def fetch_html(arxiv_id: str, version: int) -> str | None:
    """The paper's web-page version, or None if arXiv has not made one."""
    HTML_CACHE.mkdir(parents=True, exist_ok=True)
    path = HTML_CACHE / f"{arxiv_id}v{version}.html"
    missing = HTML_CACHE / f"{arxiv_id}v{version}.missing"
    if path.exists():
        return path.read_text()
    if missing.exists():
        return None
    r = _get(f"https://arxiv.org/html/{arxiv_id}v{version}")
    if r.status_code != 200 or "ltx_document" not in r.text:
        missing.write_text(str(r.status_code))
        return None
    path.write_text(r.text)
    return r.text


def clean_text(html: str) -> tuple[str, dict]:
    """Turn the web page into plain text. Returns the text and some counts."""
    soup = BeautifulSoup(html, "lxml")
    article = soup.find("article")
    if article is None:
        return "", {"math": 0, "blocks": 0}

    for el in article.select(DROP):
        el.decompose()

    # Inline maths becomes its LaTeX source, so it is at least readable.
    maths = article.find_all("math")
    for m in maths:
        m.replace_with(m.get("alttext") or "")

    blocks = []
    for el in article.select(".ltx_title, .ltx_para, .ltx_abstract > .ltx_p"):
        if "ltx_para" in el.get("class", []) and el.select_one(".ltx_para"):
            continue  # a wrapper around smaller paragraphs; the inner ones carry the text
        text = re.sub(r"\s+", " ", el.get_text("")).strip()
        if text:
            blocks.append(text)

    text = unicodedata.normalize("NFC", "\n\n".join(blocks))
    return text, {"math": len(maths), "blocks": len(blocks)}


def prose_share(text: str) -> float:
    """Share of the text that sits in paragraphs of at least 200 characters."""
    paras = [p for p in text.split("\n") if p.strip()]
    return sum(len(p) for p in paras if len(p) >= 200) / max(len(text), 1)


def fingerprint(text: str) -> str:
    """A short code that changes if even one character of the text changes."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
