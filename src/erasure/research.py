"""Bounded official-page research; never receives a user's identity or mailbox."""

import http.client
import ipaddress
import re
import socket
import ssl
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlsplit

MAX_BYTES = 1_000_000


class ResearchBlocked(ValueError):
    pass


def official_url(url, domain):
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if (
        p.scheme != "https"
        or not host
        or not domain
        or p.username
        or p.password
        or p.port not in (None, 443)
        or p.query
        or p.fragment
        or not (host == domain or host.endswith("." + domain))
    ):
        raise ResearchBlocked("Not a plain HTTPS page on the catalogued broker domain")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return p
    raise ResearchBlocked("IP-address URLs are not allowed")


def public_addresses(host):
    addresses = list(
        dict.fromkeys(x[4][0] for x in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM))
    )
    if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
        raise ResearchBlocked("Destination does not resolve exclusively to public IPs")
    return addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=6, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        # Connect to the checked numeric address, but verify TLS for the original host.
        # Never resolve the hostname again after the public-address check.
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def fetch_public_page(url, domain):
    current = url
    deadline = time.monotonic() + 20
    for _ in range(3):
        if time.monotonic() > deadline:
            raise ResearchBlocked("Official page exceeded the time limit")
        parsed = official_url(current, domain)
        addresses = public_addresses(parsed.hostname)
        connection = _PinnedHTTPS(parsed.hostname, addresses[0])
        try:
            connection.request(
                "GET",
                parsed.path or "/",
                headers={
                    "User-Agent": "Personal-Erasure/0.1 (privacy-contact verification)",
                    "Accept": "text/html, text/plain",
                    "Accept-Encoding": "identity",
                },
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ResearchBlocked("Redirect has no destination")
                current = urljoin(current, location)
                continue
            if response.status != 200:
                raise ResearchBlocked(f"Official page returned HTTP {response.status}")
            if not any(
                t in response.getheader("Content-Type", "").lower()
                for t in ("text/html", "text/plain")
            ):
                raise ResearchBlocked("Official page is not HTML or plain text")
            if response.getheader("Content-Encoding", "identity") != "identity":
                raise ResearchBlocked("Compressed responses are not accepted")
            chunks, size = [], 0
            while True:
                if time.monotonic() > deadline:
                    raise ResearchBlocked("Official page exceeded the time limit")
                chunk = response.read1(min(65_536, MAX_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ResearchBlocked("Official page exceeds the size limit")
            data = b"".join(chunks)
            return current, data.decode("utf-8", errors="replace")
        finally:
            connection.close()
    raise ResearchBlocked("Too many redirects")


class PolicyText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.links = [], []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if self.hidden:
            return
        if tag in {"p", "div", "li", "br", "h1", "h2", "h3", "section"}:
            self.parts.append("\n")
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith("mailto:"):
                self.parts.append(" " + unquote(href[7:].split("?")[0]) + " ")
            elif href:
                self.links.append(href)

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        if not self.hidden and tag in {"p", "div", "li", "section"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


@dataclass
class ResearchResult:
    status: str
    reason: str
    source_url: str = ""
    evidence: str = ""


def policy_urls(broker):
    urls = []
    for candidate in [*re.split(r"[;\s]+", broker.policy_url), f"https://{broker.domain}/"]:
        if candidate and "://" not in candidate:
            candidate = "https://" + candidate
        try:
            official_url(candidate, broker.domain)
            if candidate not in urls:
                urls.append(candidate)
        except ValueError:
            pass
    return urls


def inspect_route(broker, fetch=None):
    fetch = fetch or fetch_public_page
    domain, email = broker.domain.lower(), broker.contact.strip().lower()
    queue = policy_urls(broker)
    source = queue[0] if queue else ""
    if not re.fullmatch(r"[^\s@]+@[^\s@]+", email):
        return ResearchResult("needs_review", "No single catalogued email destination", source)
    local, host = email.rsplit("@", 1)
    if not domain or not (host == domain or host.endswith("." + domain)):
        return ResearchResult(
            "needs_review",
            "Catalog inbox uses another domain; review the entity relationship",
            source,
        )
    if not re.search(r"privacy|datenschutz|gdpr|dpo|data[._-]?protection", local):
        return ResearchResult(
            "needs_review",
            "Generic or personal inbox; not automatically approved for disclosure",
            source,
        )
    seen, last_reason, last_url = set(), "No explicit email route found", ""
    deadline = time.monotonic() + 45
    while queue and len(seen) < 3 and time.monotonic() < deadline:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            final_url, html = fetch(url, domain)
            official_url(final_url, domain)
        except (OSError, ValueError, http.client.HTTPException) as exc:
            last_reason = (
                str(exc)[:200]
                if isinstance(exc, ResearchBlocked)
                else "Official page could not be reached securely"
            )
            continue
        last_url = final_url
        parser = PolicyText()
        parser.feed(html)
        text = "\n".join(
            " ".join(block.split())
            for block in " ".join(parser.parts).splitlines()
            if block.strip()
        )
        lower = text.lower()
        # Do not silently use fallback email when the page mandates a form or other identity.
        if re.search(
            r"\bmust (?:use|complete|submit)\b.{0,80}\b(?:form|portal)\b|"
            r"\brequests? (?:must|can only)\b.{0,80}\b(?:form|portal)\b",
            lower,
        ):
            return ResearchResult(
                "needs_review", "Form or conditional route requires review", final_url
            )
        for match in re.finditer(r"(?<![\w.+-])" + re.escape(email) + r"(?![\w.-])", lower):
            # Keep the email and its instructions in the same visible block. Footer
            # links or nearby cookie/newsletter opt-outs are not deletion routes.
            start = max(text.rfind("\n", 0, match.start()) + 1, match.start() - 300)
            end = text.find("\n", match.end())
            end = min(end if end >= 0 else len(text), match.end() + 180)
            excerpt = text[start:end]
            normalized = excerpt.lower()
            rights = re.search(
                r"delet|erasur|exercise.{0,40}rights|rights.{0,40}request", normalized
            )
            invitation = re.search(r"contact|e.?mail|send|write|submit", normalized)
            conditional = re.search(
                r"\b(?:unable|cannot|can't|do not|does not|no longer)\b.{0,80}\b(?:request|requests|email|e-mail|process|form)\b",
                normalized,
            )
            regional = "california" in normalized and not re.search(
                r"europe|gdpr|eea|regardless|all (?:users|individuals)", lower
            )
            if rights and invitation and not regional and not conditional:
                return ResearchResult(
                    "verified",
                    "Existing privacy inbox explicitly offered for rights requests",
                    final_url,
                    excerpt,
                )
        for link in parser.links:
            candidate = urljoin(final_url, link).split("#")[0]
            if re.search(r"privacy|datenschutz|data.protection", urlsplit(candidate).path, re.I):
                try:
                    official_url(candidate, domain)
                    if candidate not in seen and candidate not in queue:
                        queue.append(candidate)
                except (ValueError, ResearchBlocked):
                    pass
    return ResearchResult("needs_review", last_reason, last_url)
