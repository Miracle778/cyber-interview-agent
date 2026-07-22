from pathlib import Path


def test_prepare_curation_sources_keeps_low_signal_text_and_warns_per_source(
    tmp_path: Path,
) -> None:
    from app.review.curation_sources import prepare_curation_sources

    usable = tmp_path / "usable.md"
    usable.write_text("Explain cache penetration and its mitigation.", encoding="utf-8")
    low_signal = tmp_path / "keywords.md"
    low_signal.write_text("Redis TTL", encoding="utf-8")
    empty = tmp_path / "empty.md"
    empty.write_text(" \n\t", encoding="utf-8")
    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff\xfe")

    prepared = prepare_curation_sources(
        (("usable", usable), ("keywords", low_signal), ("empty", empty), ("bad", invalid))
    )

    assert prepared.excerpts == (
        ("usable", "Explain cache penetration and its mitigation."),
        ("keywords", "Redis TTL"),
    )
    assert prepared.warnings == (
        {"sourceId": "keywords", "code": "low_signal"},
        {"sourceId": "empty", "code": "no_extractable_text"},
        {"sourceId": "bad", "code": "unsupported_encoding"},
    )
    assert prepared.has_usable_text is True


def test_prepare_curation_sources_returns_safe_warnings_when_every_source_is_unusable(
    tmp_path: Path,
) -> None:
    from app.review.curation_sources import prepare_curation_sources

    whitespace = tmp_path / "whitespace.md"
    whitespace.write_text("\n  ", encoding="utf-8")
    invalid = tmp_path / "invalid.md"
    invalid.write_bytes(b"\xff\xfe")

    prepared = prepare_curation_sources((("empty", whitespace), ("bad", invalid)))

    assert prepared.excerpts == ()
    assert prepared.has_usable_text is False
    assert prepared.warnings == (
        {"sourceId": "empty", "code": "no_extractable_text"},
        {"sourceId": "bad", "code": "unsupported_encoding"},
    )
