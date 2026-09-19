"""fetch_url: extraction, pagination, unsafe-destination blocking and redirects.

No real network access: requests and DNS are faked."""

from types import SimpleNamespace

import pytest

from triton.tools import web


@pytest.fixture(autouse=True)
def _public_dns(monkeypatch):
    def public_address(*_args, **_kwargs):
        return [(web.socket.AF_INET, web.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(
        web.socket,
        "getaddrinfo",
        public_address,
    )


def _html_response(
    html: str,
    content_type: str = "text/html; charset=utf-8",
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
):
    return SimpleNamespace(
        text=html,
        status_code=status_code,
        headers={"content-type": content_type, **(headers or {})},
        raise_for_status=lambda: None,
    )


def test_rejects_a_non_http_url():
    assert "url must start with http:// or https://" in web.fetch_url("ftp://example.com")


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/private",
        "http://[::1]/private",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.1/private",
    ],
)
def test_rejects_non_public_literal_addresses(monkeypatch, url):
    monkeypatch.setattr(
        web.requests, "get", lambda *_args, **_kwargs: pytest.fail("must not fetch")
    )

    assert web.fetch_url(url).startswith("error: blocked unsafe URL")


def test_rejects_hostname_resolving_to_loopback(monkeypatch):
    def loopback_address(*_args, **_kwargs):
        return [(web.socket.AF_INET, web.socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(
        web.socket,
        "getaddrinfo",
        loopback_address,
    )
    monkeypatch.setattr(
        web.requests, "get", lambda *_args, **_kwargs: pytest.fail("must not fetch")
    )

    assert web.fetch_url("http://localhost:8000/private").startswith("error: blocked unsafe URL")


def test_rejects_a_redirect_to_a_private_address(monkeypatch):
    calls: list[str] = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        return _html_response("", status_code=302, headers={"location": "http://127.0.0.1/private"})

    monkeypatch.setattr(web.requests, "get", fake_get)

    assert web.fetch_url("https://example.com/start").startswith("error: blocked unsafe URL")
    assert calls == ["https://example.com/start"]


def test_follows_a_public_redirect_with_redirects_disabled_on_requests(monkeypatch):
    calls: list[tuple[str, bool]] = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs["allow_redirects"]))
        if url.endswith("/start"):
            return _html_response("", status_code=302, headers={"location": "/article"})
        return _html_response("the article")

    monkeypatch.setattr(web.requests, "get", fake_get)

    assert web.fetch_url("https://example.com/start") == "the article"
    assert calls == [("https://example.com/start", False), ("https://example.com/article", False)]


def test_extracts_the_article_body_and_drops_boilerplate(monkeypatch):
    html = (
        "<html><body><nav>Home About Contact</nav>"
        "<article><h1>Title</h1><p>" + "Real article content. " * 20 + "</p></article>"
        "<footer>copyright 2024</footer></body></html>"
    )
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response(html))

    result = web.fetch_url("https://example.com/article")

    assert "Real article content." in result
    assert "Home About Contact" not in result
    assert "copyright 2024" not in result


def test_falls_back_to_tag_stripping_when_trafilatura_extracts_nothing(monkeypatch):
    # short enough to also stay under the JS-rendered warning threshold
    html = "<html><body><div>just a little bit of plain text here</div></body></html>"
    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: None)
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response(html))

    result = web.fetch_url("https://example.com/tiny")

    assert "just a little bit of plain text here" in result
    assert "<div>" not in result


def test_non_html_content_type_is_returned_as_is(monkeypatch):
    monkeypatch.setattr(
        web.requests, "get", lambda *a, **k: _html_response('{"a": 1}', "application/json")
    )
    assert web.fetch_url("https://example.com/data.json") == '{"a": 1}'


def test_request_failure_is_reported_as_an_error(monkeypatch):
    def _raise(*_a, **_k):
        raise web.requests.RequestException("boom")

    monkeypatch.setattr(web.requests, "get", _raise)
    result = web.fetch_url("https://example.com")
    assert result.startswith("error: could not fetch")
    assert "boom" in result


# --- pagination ---


def test_short_page_needs_no_pagination_footer(monkeypatch):
    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: "short text")
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response("<html></html>"))

    result = web.fetch_url("https://example.com")

    assert result == "short text"


def test_long_page_is_chunked_with_a_next_offset_hint(monkeypatch):
    long_text = "x" * (web.FETCH_CHUNK_SIZE + 500)
    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: long_text)
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response("<html></html>"))

    first = web.fetch_url("https://example.com")

    assert len(first) > web.FETCH_CHUNK_SIZE  # chunk + footer note
    assert f"offset={web.FETCH_CHUNK_SIZE}" in first

    second = web.fetch_url("https://example.com", offset=web.FETCH_CHUNK_SIZE)
    assert second == long_text[web.FETCH_CHUNK_SIZE :]


def test_offset_past_the_end_says_so_instead_of_returning_empty(monkeypatch):
    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: "short text")
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response("<html></html>"))

    result = web.fetch_url("https://example.com", offset=9999)

    assert result == "(nothing left to show: offset 9999 is past the end - 10 characters total)"


def test_negative_offset_is_clamped_to_zero(monkeypatch):
    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: "short text")
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response("<html></html>"))

    assert web.fetch_url("https://example.com", offset=-50) == "short text"


# --- JS-rendered detection ---


def test_warns_when_a_large_page_extracts_almost_nothing(monkeypatch):
    raw_html = "<html><body><div id='root'></div>" + "<!-- padding -->" * 300 + "</body></html>"
    assert len(raw_html) >= web.JS_RENDERED_MIN_RAW_SIZE
    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: None)
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response(raw_html))

    result = web.fetch_url("https://example.com/spa")

    assert "likely renders its content with JavaScript" in result


def test_no_warning_for_a_small_page_with_little_text(monkeypatch):
    html = "<html><body>hi</body></html>"
    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: None)
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response(html))

    result = web.fetch_url("https://example.com/small")

    assert "JavaScript" not in result


def test_no_warning_when_extraction_succeeds_normally(monkeypatch):
    long_html = "<html><body><article>" + "real content here. " * 50 + "</article></body></html>"
    monkeypatch.setattr(web.trafilatura, "extract", lambda *a, **k: "real content here. " * 50)
    monkeypatch.setattr(web.requests, "get", lambda *a, **k: _html_response(long_html))

    result = web.fetch_url("https://example.com/normal")

    assert "JavaScript" not in result
