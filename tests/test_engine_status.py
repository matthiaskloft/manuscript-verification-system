from openrefcheck.extraction import engine_status


def test_reports_grobid_when_reachable(monkeypatch):
    monkeypatch.setattr(engine_status, "is_grobid_available", lambda: True)
    monkeypatch.setattr(engine_status, "grobid_url", lambda: "http://localhost:8070")

    status = engine_status.current_engine_status()

    assert status.name == engine_status.GROBID_ENGINE_NAME
    assert status.reachable is True


def test_falls_back_to_anchor_when_grobid_unreachable(monkeypatch):
    monkeypatch.setattr(engine_status, "is_grobid_available", lambda: False)
    monkeypatch.setattr(engine_status, "grobid_url", lambda: "http://localhost:8070")

    status = engine_status.current_engine_status()

    assert status.name == engine_status.ANCHOR_ENGINE_NAME
    assert status.reachable is False


def test_anchor_preference_skips_grobid_reachability_check(monkeypatch):
    def _fail_if_called():
        raise AssertionError("is_grobid_available should not be called when ENGINE_ANCHOR is forced")

    monkeypatch.setattr(engine_status, "is_grobid_available", _fail_if_called)

    status = engine_status.current_engine_status(engine_status.ENGINE_ANCHOR)

    assert status.name == engine_status.ANCHOR_ENGINE_NAME
    assert status.reachable is True


def test_grobid_preference_reports_grobid_when_reachable(monkeypatch):
    monkeypatch.setattr(engine_status, "is_grobid_available", lambda: True)
    monkeypatch.setattr(engine_status, "grobid_url", lambda: "http://localhost:8070")

    status = engine_status.current_engine_status(engine_status.ENGINE_GROBID)

    assert status.name == engine_status.GROBID_ENGINE_NAME
    assert status.reachable is True


def test_grobid_preference_falls_back_when_unreachable(monkeypatch):
    monkeypatch.setattr(engine_status, "is_grobid_available", lambda: False)
    monkeypatch.setattr(engine_status, "grobid_url", lambda: "http://localhost:8070")

    status = engine_status.current_engine_status(engine_status.ENGINE_GROBID)

    assert status.name == engine_status.ANCHOR_ENGINE_NAME
    assert status.reachable is False
    assert "forced" in status.detail or "GROBID selected" in status.detail
