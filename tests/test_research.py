from types import SimpleNamespace

import pytest

from erasure.research import (
    ResearchBlocked,
    _PinnedHTTPS,
    fetch_public_page,
    inspect_route,
    official_url,
    public_addresses,
)


def broker(contact="privacy@broker.test"):
    return SimpleNamespace(
        domain="broker.test", contact=contact, policy_url="https://broker.test/privacy"
    )


def test_explicit_existing_privacy_route_is_verified():
    result = inspect_route(
        broker(),
        lambda url, domain: (
            url,
            '<p>To exercise your deletion rights, email <a href="mailto:privacy@broker.test">our privacy team</a>.</p>',
        ),
    )
    assert result.status == "verified"
    assert "privacy@broker.test" in result.evidence


@pytest.mark.parametrize(
    "body",
    [
        "<script>To request deletion email privacy@broker.test</script>",
        "<p>Contact privacy@broker.test with general questions.</p>",
        "<p>For deletion email privacy@somewhere-else.test.</p>",
        "<p>You must use our request form for deletion. Email privacy@broker.test with questions.</p>",
        "<p>California residents may request deletion by emailing privacy@broker.test.</p>",
        "<p>Do not send deletion requests to privacy@broker.test.</p>",
        "<p>If unable to complete the form, email privacy@broker.test for deletion.</p>",
        "<p>For deletion email notprivacy@broker.test.</p>",
        "<p>For deletion email privacy@broker.test.evil.test.</p>",
        "<p>For privacy related information, contact privacy@broker.test or use our Opt Out page.</p><footer>Delete my information</footer>",
        "<p>To opt out of cookie placement, send a request to privacy@broker.test.</p>",
        "<p>To opt out of marketing messages contact privacy@broker.test.</p>",
    ],
)
def test_ambiguous_or_conditional_pages_are_not_promoted(body):
    assert inspect_route(broker(), lambda url, domain: (url, body)).status == "needs_review"


@pytest.mark.parametrize(
    "contact",
    [
        "contact@broker.test",
        "jane@broker.test",
        "privacy@other.test",
        "privacy@broker.test\ncc@evil.test",
    ],
)
def test_generic_and_different_domain_contacts_are_not_automatically_trusted(contact):
    assert (
        inspect_route(broker(contact), lambda *a: pytest.fail("Should not fetch")).status
        == "needs_review"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://broker.test/privacy",
        "https://broker.test.evil.test/privacy",
        "https://127.0.0.1/",
        "https://broker.test:8080/privacy",
        "https://user:pass@broker.test/privacy",
        "https://broker.test/privacy?token=x",
    ],
)
def test_official_fetch_rejects_unsafe_destinations(url):
    with pytest.raises(ResearchBlocked):
        official_url(url, "broker.test")


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "100.64.0.1"]
)
def test_dns_private_addresses_are_blocked(monkeypatch, address):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", (address, 443))])
    with pytest.raises(ResearchBlocked):
        public_addresses("broker.test")


def test_only_three_pages_are_fetched_and_external_links_are_ignored():
    visited = []

    def fetch(url, domain):
        visited.append(url)
        return url, '<a href="https://evil.test/privacy">External</a>' + "".join(
            f'<a href="/privacy-{i}">Privacy</a>' for i in range(10)
        )

    assert inspect_route(broker(), fetch).status == "needs_review"
    assert len(visited) == 3 and all(url.startswith("https://broker.test/") for url in visited)


def test_https_connect_is_pinned_but_certificate_uses_original_hostname(monkeypatch):
    connection = _PinnedHTTPS("broker.test", "8.8.8.8")
    connected, tls_hosts = [], []
    raw = object()
    monkeypatch.setattr(
        "socket.create_connection", lambda address, **kw: connected.append(address) or raw
    )
    monkeypatch.setattr(
        connection._context,
        "wrap_socket",
        lambda sock, server_hostname: tls_hosts.append(server_hostname) or raw,
    )
    connection.connect()
    assert connected == [("8.8.8.8", 443)]
    assert tls_hosts == ["broker.test"]


def test_redirect_is_checked_before_following_and_download_is_bounded(monkeypatch):
    visited = []
    response = SimpleNamespace(
        status=302, getheader=lambda name, default=None: "https://127.0.0.1/"
    )

    class Connection:
        def __init__(self, host, address):
            visited.append(host)

        def request(self, *args, **kwargs):
            pass

        def getresponse(self):
            return response

        def close(self):
            pass

    monkeypatch.setattr("erasure.research.public_addresses", lambda host: ["8.8.8.8"])
    monkeypatch.setattr("erasure.research._PinnedHTTPS", Connection)
    with pytest.raises(ResearchBlocked):
        fetch_public_page("https://broker.test/privacy", "broker.test")
    assert visited == ["broker.test"]
    monkeypatch.setattr("erasure.research.MAX_BYTES", 5)
    response.status = 200
    response.getheader = lambda name, default=None: (
        "text/html" if name == "Content-Type" else default
    )
    response.read1 = lambda size: b"123456"
    with pytest.raises(ResearchBlocked, match="size limit"):
        fetch_public_page("https://broker.test/privacy", "broker.test")
