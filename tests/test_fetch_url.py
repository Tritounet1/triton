"""fetch_url: real content extraction (trafilatura, falling back to a
blunt tag-strip when it finds nothing extractable), pagination over long
pages, and a warning when a page looks JS-rendered (large raw HTML, almost
no extracted text). No real network access - requests.get is faked."""

from types import SimpleNamespace

from triton.tools import web


def _html_response(html: str, content_type: str = "text/html; charset=utf-8"):
    return SimpleNamespace(
        text=html, headers={"content-type": content_type}, raise_for_status=lambda: None
    )


def test_rejects_a_non_http_url():
    assert web.fetch_url("ftp://example.com") == "error: url must start with http:// or https://"


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
