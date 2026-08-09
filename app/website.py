"""Safely collect public product-page text for AI-assisted onboarding."""

from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
import ipaddress
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_PAGE_BYTES = 600_000
MAX_TOTAL_CHARACTERS = 45_000
MAX_PAGES = 4
REQUEST_TIMEOUT_SECONDS = 10
KEY_PAGE_TERMS = (
    "product",
    "features",
    "solutions",
    "pricing",
    "about",
    "customers",
    "use-cases",
    "industries",
)


class WebsiteReadError(ValueError):
    """A public product website could not be safely read."""


@dataclass(frozen=True)
class WebsiteResearch:
    requested_url: str
    final_url: str
    title: str
    description: str
    pages: tuple[dict[str, str], ...]

    def as_prompt_text(self) -> str:
        header = (
            f"Requested URL: {self.requested_url}\n"
            f"Final URL: {self.final_url}\n"
            f"Page title: {self.title}\n"
            f"Meta description: {self.description}\n"
        )
        sections = []
        remaining = MAX_TOTAL_CHARACTERS
        for page in self.pages:
            section = f"\nSOURCE PAGE: {page['url']}\n{page['text']}\n"
            if len(section) > remaining:
                section = section[:remaining]
            sections.append(section)
            remaining -= len(section)
            if remaining <= 0:
                break
        return header + "".join(sections)


class _ProductHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.description = ""
        self.links: list[str] = []
        self._skip_depth = 0
        self._in_title = False
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.casefold(): value or "" for name, value in attrs}
        lowered = tag.casefold()
        if lowered in {"script", "style", "svg", "noscript", "template"}:
            self._skip_depth += 1
            return
        if lowered == "title":
            self._in_title = True
        if lowered == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").casefold()
            if name in {"description", "og:description", "twitter:description"}:
                self.description = self.description or attributes.get("content", "").strip()
        if lowered == "a" and attributes.get("href"):
            self.links.append(attributes["href"].strip())

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.casefold()
        if lowered in {"script", "style", "svg", "noscript", "template"}:
            self._skip_depth = max(0, self._skip_depth - 1)
        if lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = " ".join(data.split())
        if not value:
            return
        if self._in_title:
            self.title = f"{self.title} {value}".strip()
        else:
            self._text.append(value)

    @property
    def text(self) -> str:
        return "\n".join(self._text)


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def normalize_website_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise WebsiteReadError("Enter a product website URL.")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    parsed = urlparse(candidate)
    if parsed.scheme.casefold() not in {"http", "https"}:
        raise WebsiteReadError("Website URL must use http or https.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise WebsiteReadError("Enter a public website URL without embedded credentials.")
    cleaned = parsed._replace(fragment="")
    return urlunparse(cleaned)


def validate_public_url(value: str) -> str:
    normalized = normalize_website_url(value)
    host = urlparse(normalized).hostname or ""
    if host.casefold() in {"localhost", "localhost.localdomain"}:
        raise WebsiteReadError("Local and private network addresses are not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise WebsiteReadError("The website hostname could not be resolved.") from exc
    if not addresses:
        raise WebsiteReadError("The website hostname could not be resolved.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise WebsiteReadError("Local and private network addresses are not allowed.")
    return normalized


def research_product_website(value: str) -> WebsiteResearch:
    requested_url = validate_public_url(value)
    first = _read_page(requested_url)
    pages = [first]
    selected_links = _select_key_links(first["links"], first["url"])
    for link in selected_links[: MAX_PAGES - 1]:
        try:
            pages.append(_read_page(link))
        except WebsiteReadError:
            continue
    return WebsiteResearch(
        requested_url=requested_url,
        final_url=first["url"],
        title=first["title"],
        description=first["description"],
        pages=tuple(
            {"url": page["url"], "text": page["text"]}
            for page in pages
        ),
    )


def _read_page(url: str) -> dict[str, object]:
    validate_public_url(url)
    request = Request(
        url,
        headers={
            "User-Agent": "Reddit-Lead-Finder/0.5 website setup assistant",
            "Accept": "text/html,text/plain;q=0.9",
        },
    )
    opener = build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            final_url = validate_public_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "text/plain"}:
                raise WebsiteReadError("The URL did not return a readable web page.")
            raw = response.read(MAX_PAGE_BYTES + 1)
            if len(raw) > MAX_PAGE_BYTES:
                raise WebsiteReadError("The web page is too large to analyze safely.")
            charset = response.headers.get_content_charset() or "utf-8"
    except HTTPError as exc:
        raise WebsiteReadError(f"The website returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise WebsiteReadError("The website could not be reached.") from exc
    except TimeoutError as exc:
        raise WebsiteReadError("The website took too long to respond.") from exc

    text = raw.decode(charset, errors="replace")
    if content_type == "text/plain":
        cleaned = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        return {
            "url": final_url,
            "title": urlparse(final_url).hostname or "",
            "description": "",
            "text": cleaned[:MAX_TOTAL_CHARACTERS],
            "links": [],
        }
    parser = _ProductHTMLParser()
    parser.feed(text)
    if len(parser.text) < 80:
        raise WebsiteReadError(
            "The website did not expose enough readable text. Add product notes and try again."
        )
    return {
        "url": final_url,
        "title": parser.title[:300],
        "description": parser.description[:1000],
        "text": parser.text[:MAX_TOTAL_CHARACTERS],
        "links": parser.links,
    }


def _select_key_links(links: list[str], base_url: str) -> list[str]:
    base_host = (urlparse(base_url).hostname or "").casefold()
    scored: list[tuple[int, str]] = []
    seen: set[str] = {base_url.rstrip("/")}
    for raw_link in links:
        absolute = urljoin(base_url, raw_link)
        parsed = urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        if (parsed.hostname or "").casefold() != base_host:
            continue
        cleaned = urlunparse(parsed._replace(query="", fragment="")).rstrip("/")
        if not cleaned or cleaned in seen:
            continue
        path = parsed.path.casefold()
        score = next(
            (len(KEY_PAGE_TERMS) - index for index, term in enumerate(KEY_PAGE_TERMS) if term in path),
            0,
        )
        if score:
            seen.add(cleaned)
            scored.append((score, cleaned))
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return [url for _, url in scored]
