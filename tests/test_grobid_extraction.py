import requests

from refcheck.benchmark import grobid_client
from refcheck.extraction import grobid
from refcheck.extraction.grobid import GrobidUnavailableError, extract_references_via_grobid, is_grobid_available


def test_grobid_url_defaults_to_local_container(monkeypatch):
    monkeypatch.delenv("GROBID_URL", raising=False)
    assert grobid.grobid_url() == "http://localhost:8070"


def test_grobid_url_reads_env_override(monkeypatch):
    monkeypatch.setenv("GROBID_URL", "http://grobid.internal:8070")
    assert grobid.grobid_url() == "http://grobid.internal:8070"


def test_is_grobid_available_true_on_ok_response(monkeypatch):
    captured = {}

    class FakeResponse:
        ok = True

    def fake_get(url, timeout, headers):
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(grobid.requests, "get", fake_get)
    assert is_grobid_available("http://localhost:8070") is True
    assert captured["timeout"] == 60


def test_is_grobid_available_false_on_connection_error(monkeypatch):
    def raise_connection_error(url, timeout, headers):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(grobid.requests, "get", raise_connection_error)
    assert is_grobid_available("http://localhost:8070") is False


def test_is_grobid_available_skips_auth_header_for_localhost(monkeypatch):
    """No Google credentials are available/needed for a local dev GROBID container."""
    captured = {}

    class FakeResponse:
        ok = True

    def fake_get(url, timeout, headers):
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(grobid.requests, "get", fake_get)
    assert is_grobid_available("http://localhost:8070") is True
    assert captured["headers"] == {}


def test_is_grobid_available_attaches_identity_token_for_remote_url(monkeypatch):
    captured = {}

    class FakeResponse:
        ok = True

    def fake_get(url, timeout, headers):
        captured["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr(grobid.requests, "get", fake_get)
    monkeypatch.setattr(grobid, "_identity_token_header", lambda url: {"Authorization": "Bearer fake-token"})
    assert is_grobid_available("https://refcheck-grobid-xyz.a.run.app") is True
    assert captured["headers"] == {"Authorization": "Bearer fake-token"}


def test_identity_token_header_best_effort_on_fetch_failure(monkeypatch):
    """A remote URL with no usable Google credentials (e.g. running outside GCP) should
    degrade to no header rather than raise — GROBID is a best-effort upgrade."""
    assert grobid._identity_token_header("https://refcheck-grobid-xyz.a.run.app") == {}


def test_extract_references_via_grobid_converts_structured_fields(monkeypatch, tmp_path):
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    tei = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
      <biblStruct xml:id="b0">
        <analytic>
          <title level="a">A Great Title</title>
          <author><persName><surname>Doe</surname></persName></author>
        </analytic>
        <monogr>
          <imprint>
            <date type="published" when="2020" />
            <idno type="DOI">10.1000/xyz</idno>
          </imprint>
        </monogr>
      </biblStruct>
    </TEI>"""
    monkeypatch.setattr(grobid, "call_grobid", lambda path, grobid_url=None, headers=None: tei)

    entries = extract_references_via_grobid(pdf_path)

    assert len(entries) == 1
    assert entries[0].title == "A Great Title"
    assert "A Great Title" in entries[0].raw_text
    assert "Doe" in entries[0].raw_text
    assert "10.1000/xyz" in entries[0].raw_text


def test_the_printed_entry_is_carried_alongside_the_structured_parse(monkeypatch, tmp_path):
    """GROBID's structured fields are a lossy reading of the string the document printed,
    and `source_text` is that string. This entry is the shape the live measurement found
    costing five citations: the parse kept the original work's year and dropped the date
    slot the manuscript actually cites."""
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    tei = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
      <biblStruct xml:id="b0">
        <analytic>
          <title level="a">The protestant ethic</title>
          <author><persName><surname>Weber</surname></persName></author>
        </analytic>
        <monogr><imprint><date type="published" when="1905" /></imprint></monogr>
        <note type="raw_reference">Weber, M. (1930). The protestant ethic
        [Original work published 1905]. Allen &amp; Unwin.</note>
      </biblStruct>
    </TEI>"""
    monkeypatch.setattr(grobid, "call_grobid", lambda path, grobid_url=None, headers=None: tei)

    entry = extract_references_via_grobid(pdf_path)[0]

    # Whitespace-folded, so an entry broken across lines in the PDF reads as one string.
    assert entry.source_text == (
        "Weber, M. (1930). The protestant ethic [Original work published 1905]. Allen & Unwin."
    )
    assert "1930" not in entry.raw_text  # the reconstruction still has only GROBID's year


def test_an_entry_without_a_raw_reference_note_has_no_source_text(monkeypatch, tmp_path):
    """A GROBID that was not asked for raw citations, or that supplied none for an entry,
    leaves source_text None rather than an empty string — matching falls back to the
    reconstruction, and "" would read as an entry with nothing in it."""
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    tei = """<TEI xmlns="http://www.tei-c.org/ns/1.0">
      <biblStruct xml:id="b0">
        <analytic><title level="a">A Great Title</title></analytic>
      </biblStruct>
    </TEI>"""
    monkeypatch.setattr(grobid, "call_grobid", lambda path, grobid_url=None, headers=None: tei)

    assert extract_references_via_grobid(pdf_path)[0].source_text is None


def test_the_grobid_request_asks_for_raw_citations(monkeypatch, tmp_path):
    """The note above only exists if it was requested — without this parameter the whole
    source_text path is dead code against a real instance."""
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")
    sent = {}

    class _Response:
        text = '<TEI xmlns="http://www.tei-c.org/ns/1.0"></TEI>'

        def raise_for_status(self):
            return None

    def _post(url, files=None, data=None, timeout=None, headers=None):
        sent.update(data or {})
        return _Response()

    monkeypatch.setattr(grobid_client.requests, "post", _post)
    grobid_client.call_grobid(pdf_path)

    assert sent.get("includeRawCitations") == "1"


def test_extract_references_via_grobid_raises_on_connection_error(monkeypatch, tmp_path):
    pdf_path = tmp_path / "manuscript.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    def raise_connection_error(path, grobid_url=None, headers=None):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr(grobid, "call_grobid", raise_connection_error)

    try:
        extract_references_via_grobid(pdf_path)
        assert False, "expected GrobidUnavailableError"
    except GrobidUnavailableError:
        pass
