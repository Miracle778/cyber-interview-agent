from hashlib import sha256

from app.review.curation_sections import (
    DiscoveryUnit,
    SourceSection,
    pack_discovery_units,
    section_sources,
)


def test_sectioner_recognizes_chinese_and_markdown_boundaries_without_prefix_copy():
    source = (
        "source-1:mybatis.md\n"
        "前置说明\n\u200b\n补充说明\n\n"
        "# 插件原理\n正文 A\n"
        "**如何创建拦截器？**\n正文 B\n"
        "1、正向代理\n正文 C\n"
        "2) 反向代理\n正文 D\n"
        "缓存为什么失效？\n正文 E"
    )

    sections = section_sources((source,))

    assert [item.ref for item in sections] == [
        "source-1#section-0001",
        "source-1#section-0002",
        "source-1#section-0003",
        "source-1#section-0004",
        "source-1#section-0005",
        "source-1#section-0006",
        "source-1#section-0007",
    ]
    assert sum("前置说明" in item.text for item in sections) == 1
    assert any(item.text.startswith("1、正向代理") for item in sections)
    assert all(len(item.text) <= 2_000 for item in sections)


def test_sectioner_normalizes_empty_html_and_zero_width_blank_lines():
    sections = section_sources(
        (
            "s1:notes.md\nfirst\n&nbsp;\n<br/>\n<p>&nbsp;</p>\n\ufeff\nsecond",
        )
    )

    assert [section.text for section in sections] == ["first", "second"]


def test_long_section_has_stable_continuations_and_digest():
    first = section_sources(("s1:long.md\n# 标题\n" + "x" * 4_501,))
    second = section_sources(("s1:long.md\r\n# 标题\r\n" + "x" * 4_501,))

    assert [item.ref for item in first] == [
        "s1#section-0001",
        "s1#section-0002",
        "s1#section-0003",
    ]
    assert [(item.ref, item.digest) for item in first] == [
        (item.ref, item.digest) for item in second
    ]
    assert "".join(item.text for item in first).replace("# 标题\n", "", 1) == "x" * 4_501
    assert all(len(item.text) <= 2_000 for item in first)


def test_discovery_units_enforce_section_and_character_limits():
    sections = tuple(
        SourceSection(
            "s1",
            f"s1#section-{index:04d}",
            index,
            "x" * 1_100,
            sha256(str(index).encode("utf-8")).hexdigest(),
        )
        for index in range(1, 9)
    )

    units = pack_discovery_units(sections)

    assert all(len(unit.sections) <= 6 for unit in units)
    assert all(
        sum(len(section.text) for section in unit.sections) <= 6_000
        for unit in units
    )
    assert [unit.unit_index for unit in units] == [0, 1]
    assert all(isinstance(unit, DiscoveryUnit) for unit in units)
    assert [unit.input_digest for unit in units] == [
        unit.input_digest for unit in pack_discovery_units(sections)
    ]


def test_irregular_notes_keep_each_atomic_piece_in_exactly_one_bounded_section():
    atoms = (
        "Redis, TTL, eviction",
        "How does cache penetration work",
        "Answer: cache null values briefly.",
        "1. This is numbered prose, not a question.",
        "```python\n# Why does this retry?\nlogger.info('retry')\n```",
        "2026-07-22 INFO retry exhausted request_id=abc",
        "Kafka consumer groups, offset commits, rebalance risks.",
        "x" * 4_100,
    )
    source = "s1:irregular.md\n" + "\n\n".join(atoms)

    sections = section_sources((source,))

    rendered = "\n".join(section.text for section in sections)
    for atom in atoms[:-1]:
        assert rendered.count(atom) == 1
    assert rendered.count("x" * 100) == 41
    assert all(len(section.text) <= 2_000 for section in sections)
    assert [section.ref for section in sections] == [
        f"s1#section-{index:04d}" for index in range(1, len(sections) + 1)
    ]
