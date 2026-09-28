import pytest

from tooling.build.reporting import (
    BuildReport,
    BuildReportEntry,
    BuildReportState,
    SummaryModel,
    build_summary_model,
    format_telegram_summary,
    render_failure_summary_markdown,
    render_failure_summary_telegram_html,
    render_summary_markdown,
    render_summary_telegram_html,
)


def test_build_report_round_trips_through_dict_payload() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(
                    version="1.0.0",
                    components={
                        "github_sha:repo=upstream/telegram": "abc123",
                    },
                ),
                new_state=BuildReportState(
                    version="1.1.0",
                    components={
                        "github_sha:repo=upstream/telegram": "def456",
                    },
                ),
                docker_tags=[
                    "ignimutos/telegram:release-latest",
                    "ignimutos/telegram:release-1.1.0",
                ],
                version_source={"resolver": "github_tag", "repo": "upstream/telegram"},
                component_sources={
                    "github_sha:repo=upstream/telegram": {
                        "resolver": "github_sha",
                        "repos": ["upstream/telegram"],
                    }
                },
            )
        ]
    )

    payload = report.to_dict()

    assert payload == {
        "entries": [
            {
                "image_key": "telegram",
                "image_name": "telegram",
                "target_name": "release",
                "old_state": {
                    "version": "1.0.0",
                    "components": {
                        "github_sha:repo=upstream/telegram": "abc123",
                    },
                },
                "new_state": {
                    "version": "1.1.0",
                    "components": {
                        "github_sha:repo=upstream/telegram": "def456",
                    },
                },
                "docker_tags": [
                    "ignimutos/telegram:release-latest",
                    "ignimutos/telegram:release-1.1.0",
                ],
                "version_source": {"resolver": "github_tag", "repo": "upstream/telegram"},
                "component_sources": {
                    "github_sha:repo=upstream/telegram": {
                        "resolver": "github_sha",
                        "repos": ["upstream/telegram"],
                    }
                },
            }
        ]
    }
    assert BuildReport.from_dict(payload) == report


def test_build_report_entry_from_dict_requires_source_metadata_keys() -> None:
    with pytest.raises(
        ValueError,
        match="report entry requires version_source and component_sources",
    ):
        BuildReportEntry.from_dict(
            {
                "image_name": "telegram",
                "target_name": "release",
                "old_state": {"version": "1.0.0", "components": {}},
                "new_state": {"version": "1.1.0", "components": {}},
                "docker_tags": ["ignimutos/telegram:release-latest"],
            }
        )


def test_build_report_entry_from_dict_requires_mapping_version_source() -> None:
    with pytest.raises(ValueError, match="report entry version_source must be a mapping"):
        BuildReportEntry.from_dict(
            {
                "image_name": "telegram",
                "target_name": "release",
                "old_state": {"version": "1.0.0", "components": {}},
                "new_state": {"version": "1.1.0", "components": {}},
                "docker_tags": ["ignimutos/telegram:release-latest"],
                "version_source": ["github_tag"],
                "component_sources": {},
            }
        )


def test_build_report_entry_from_dict_requires_mapping_component_sources() -> None:
    with pytest.raises(ValueError, match="report entry component_sources must be a mapping"):
        BuildReportEntry.from_dict(
            {
                "image_name": "telegram",
                "target_name": "release",
                "old_state": {"version": "1.0.0", "components": {}},
                "new_state": {"version": "1.1.0", "components": {}},
                "docker_tags": ["ignimutos/telegram:release-latest"],
                "version_source": {"resolver": "github_tag"},
                "component_sources": ["github_sha"],
            }
        )


def test_build_report_entry_from_dict_requires_mapping_component_source_values() -> None:
    with pytest.raises(ValueError, match="report entry component_sources values must be mappings"):
        BuildReportEntry.from_dict(
            {
                "image_name": "telegram",
                "target_name": "release",
                "old_state": {"version": "1.0.0", "components": {}},
                "new_state": {"version": "1.1.0", "components": {}},
                "docker_tags": ["ignimutos/telegram:release-latest"],
                "version_source": {"resolver": "github_tag"},
                "component_sources": {
                    "github_sha:repo=upstream/telegram": "not-a-mapping",
                },
            }
        )


def test_build_report_metadata_round_trips_with_current_payload(tmp_path) -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
            )
        ],
        metadata={
            "trigger": "workflow_dispatch",
            "selection_mode": "manual-selectors",
            "requested_tokens_raw": "all,-alpha:release,+beta:worker",
            "requested_tokens_normalized": ["all", "-alpha:release", "+beta:worker"],
            "resolved_image_keys": ["alpha", "beta"],
            "resolved_entries_count": 2,
            "built_entries_count": 1,
            "force": True,
        },
    )

    payload = report.to_dict()
    assert payload["metadata"] == report.metadata
    assert BuildReport.from_dict(payload) == report

    report_file = tmp_path / "reports" / "build-report.json"
    report.write_json(report_file)
    assert BuildReport.read_json(report_file) == report


def test_build_report_metadata_round_trips_with_failure_payload(tmp_path) -> None:
    failure_metadata = {
        "result": "failure",
        "failure": {
            "stage": "build",
            "image_name": "caddy",
            "target_name": "naive",
            "message": "docker build failed",
            "exit_code": 1,
            "command": "docker buildx build ...",
        },
    }
    report = BuildReport(metadata=failure_metadata)

    payload = report.to_dict()

    assert payload == {
        "entries": [],
        "metadata": failure_metadata,
    }
    assert BuildReport.from_dict(payload) == report

    report_file = tmp_path / "reports" / "build-report-failure.json"
    report.write_json(report_file)
    assert BuildReport.read_json(report_file) == report


def test_render_failure_summary_markdown_renders_failure_details() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
            )
        ],
        metadata={
            "result": "failure",
            "failure": {
                "stage": "build",
                "image_name": "caddy",
                "target_name": "naive",
                "message": "docker build failed",
                "exit_code": 1,
                "command": "docker buildx build ...",
            },
        },
    )

    summary = render_failure_summary_markdown(report)

    assert summary.splitlines() == [
        "Build failed",
        "Stage: build",
        "Target: caddy/naive",
        "Message: docker build failed",
        "Exit code: 1",
        "Command: docker buildx build ...",
        "Successful entries: 1",
    ]


def test_render_failure_summary_telegram_html_renders_failure_details_with_escaping() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
            )
        ],
        metadata={
            "result": "failure",
            "failure": {
                "stage": "bu<ild>",
                "image_name": "ca&ddy",
                "target_name": 'na"ive',
                "message": "docker <build> failed & retry",
                "exit_code": 1,
                "command": 'docker buildx build --label "a&b" <ctx>',
            },
        },
    )

    summary = render_failure_summary_telegram_html(report)

    assert summary.splitlines() == [
        "Build failed",
        "Stage: bu&lt;ild&gt;",
        "Target: ca&amp;ddy/na&quot;ive",
        "Message: docker &lt;build&gt; failed &amp; retry",
        "Exit code: 1",
        "Command: docker buildx build --label &quot;a&amp;b&quot; &lt;ctx&gt;",
        "Successful entries: 1",
    ]


@pytest.mark.parametrize(
    ("renderer", "expected"),
    [
        (
            render_failure_summary_markdown,
            [
                "Build failed",
                "Stage: N/A",
                "Target: N/A",
                "Message: N/A",
            ],
        ),
        (
            render_failure_summary_telegram_html,
            [
                "Build failed",
                "Stage: N/A",
                "Target: N/A",
                "Message: N/A",
            ],
        ),
    ],
)
def test_render_failure_summary_handles_non_mapping_failure_metadata(
    renderer,
    expected,
) -> None:
    report = BuildReport(metadata={"result": "failure", "failure": "boom"})

    assert renderer(report).splitlines() == expected


@pytest.mark.parametrize(
    ("renderer", "expected"),
    [
        (
            render_failure_summary_markdown,
            [
                "Build failed",
                "Stage: build",
                "Target: N/A",
                "Message: N/A",
            ],
        ),
        (
            render_failure_summary_telegram_html,
            [
                "Build failed",
                "Stage: build",
                "Target: N/A",
                "Message: N/A",
            ],
        ),
    ],
)
def test_render_failure_summary_uses_na_for_missing_failure_fields(
    renderer,
    expected,
) -> None:
    report = BuildReport(metadata={"result": "failure", "failure": {"stage": "build"}})

    assert renderer(report).splitlines() == expected


@pytest.mark.parametrize(
    ("failure", "expected_target"),
    [
        ({"image_name": "caddy"}, "caddy"),
        ({"target_name": "naive"}, "naive"),
    ],
)
def test_render_failure_summary_target_with_single_side_present(
    failure,
    expected_target,
) -> None:
    report = BuildReport(metadata={"result": "failure", "failure": failure})

    assert render_failure_summary_markdown(report).splitlines()[2] == f"Target: {expected_target}"
    assert render_failure_summary_telegram_html(report).splitlines()[2] == f"Target: {expected_target}"


def test_build_report_entry_from_dict_requires_image_key() -> None:
    with pytest.raises(ValueError, match="report entry image_key must be a non-empty string"):
        BuildReportEntry.from_dict(
            {
                "image_name": "telegram",
                "target_name": "release",
                "old_state": {"version": "1.0.0", "components": {}},
                "new_state": {"version": "1.1.0", "components": {}},
                "docker_tags": ["ignimutos/telegram:release-latest"],
                "version_source": {"resolver": "github_tag"},
                "component_sources": {},
            }
        )


def test_summary_renderers_keep_trimmed_header_order_and_changed_targets_count() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0"),
                new_state=BuildReportState(version="1.0.1"),
                version_source={"resolver": "github_tag", "repo": "upstream/telegram"},
                component_sources={},
            )
        ],
        metadata={
            "trigger": "workflow_dispatch",
            "selection_mode": "manual-selectors",
            "requested_tokens_raw": "all,-alpha:release",
            "requested_tokens_normalized": ["all", "-alpha:release"],
            "resolved_image_keys": ["alpha", "beta"],
            "resolved_entries_count": 1,
            "built_entries_count": 1,
            "force": True,
        },
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    expected_header = [
        "Build summary",
        "Changed targets: 1",
        "Mode: workflow_dispatch",
        "Args(norm): all -alpha:release",
        "Resolved entries: 1",
    ]
    assert markdown.splitlines()[:5] == expected_header
    assert html.splitlines()[:5] == expected_header



def test_summary_renderers_hide_na_header_rows() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0"),
                new_state=BuildReportState(version="1.0.1"),
                version_source={"resolver": "literal"},
                component_sources={},
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "Mode:" not in markdown
    assert "Args(norm):" not in markdown
    assert "Resolved entries:" not in markdown
    assert "Mode:" not in html
    assert "Args(norm):" not in html
    assert "Resolved entries:" not in html
    assert "Changed targets: 1" in markdown
    assert "Changed targets: 1" in html


def test_render_summary_telegram_html_escapes_header_rows() -> None:
    model = SummaryModel(
        changed_targets=0,
        header_rows=[
            ("<b>Selectors</b>", "<img src=x onerror=alert(1)>&\"'"),
        ],
        entries=[],
    )

    html = render_summary_telegram_html(model)

    assert '&lt;b&gt;Selectors&lt;/b&gt;: &lt;img src=x onerror=alert(1)&gt;&amp;&quot;' in html


def test_summary_renderers_show_main_version_once_and_sort_source_rows() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(
                    version="2.0.0",
                    components={
                        "same-as-main": "2.0.0",
                        "pkg": "1.36.0-r0",
                        "sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    },
                ),
                new_state=BuildReportState(
                    version="2.1.0",
                    components={
                        "same-as-main": "2.1.0",
                        "pkg": "1.36.1-r0",
                        "sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                    },
                ),
                version_source={"resolver": "github_tag", "repo": "upstream/telegram"},
                component_sources={
                    "same-as-main": {"resolver": "literal"},
                    "pkg": {
                        "resolver": "alpine_pkg",
                        "package": "busybox",
                        "branch": "v3.21",
                        "repository": "main",
                    },
                    "sha": {
                        "resolver": "github_sha",
                        "repos": ["upstream/telegram"],
                    },
                },
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)

    assert markdown.count("version:") == 1
    assert "组件变动明细 / Component Changes" in markdown
    assert "same-as-main" not in markdown

    assert "Alpine package \\[pkg\\]" in markdown
    assert "- [upstream/telegram]" in markdown

    alpine_index = markdown.index("Alpine package \\[pkg\\]")
    github_index = markdown.index("- [upstream/telegram]")
    assert alpine_index < github_index


def test_summary_renderers_shorten_hex_and_keep_full_commit_link() -> None:
    full_old = "e17d199a40949dc9d207b211413f6dedf71213b9"
    full_new = "f88ac37b64e9f26698f6eb6324d9f4f8264f5a70"
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0", components={"sha": full_old}),
                new_state=BuildReportState(version="1.0.1", components={"sha": full_new}),
                version_source={"resolver": "literal"},
                component_sources={
                    "sha": {"resolver": "github_sha", "repos": ["upstream/telegram"]}
                },
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "[e17d199](https://github.com/upstream/telegram/commit/e17d199a40949dc9d207b211413f6dedf71213b9)" in markdown
    assert "[f88ac37](https://github.com/upstream/telegram/commit/f88ac37b64e9f26698f6eb6324d9f4f8264f5a70)" in markdown
    assert ">e17d199</a>" in html
    assert "/commit/e17d199a40949dc9d207b211413f6dedf71213b9\"" in html


def test_summary_renderers_show_na_with_source_link_for_changed_empty_values() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0", components={"feed": ""}),
                new_state=BuildReportState(version="1.0.1", components={"feed": "11"}),
                version_source={"resolver": "literal"},
                component_sources={
                    "feed": {
                        "resolver": "regex_match",
                        "url": "https://example.invalid/releases.txt",
                    }
                },
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "[N/A](https://example.invalid/releases.txt) -> [11](https://example.invalid/releases.txt)" in markdown
    assert ">N/A</a>" in html
    assert ">11</a>" in html


def test_build_summary_model_only_keeps_changed_component_rows() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(
                    version="1.0.0",
                    components={"same": "keep", "changed": "old"},
                ),
                new_state=BuildReportState(
                    version="1.0.1",
                    components={"same": "keep", "changed": "new"},
                ),
                version_source={"resolver": "literal"},
                component_sources={
                    "same": {"resolver": "literal"},
                    "changed": {"resolver": "literal"},
                },
            )
        ]
    )

    model = build_summary_model(report)

    assert [row.component_name for row in model.entries[0].detail_rows] == ["changed"]


def test_build_summary_model_keeps_added_and_removed_component_rows() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(
                    version="1.0.0",
                    components={"removed": "gone", "shared": "same"},
                ),
                new_state=BuildReportState(
                    version="1.0.1",
                    components={"added": "new", "shared": "same"},
                ),
                version_source={"resolver": "literal"},
                component_sources={
                    "removed": {"resolver": "literal"},
                    "added": {"resolver": "literal"},
                    "shared": {"resolver": "literal"},
                },
            )
        ]
    )

    model = build_summary_model(report)
    rows = {row.component_name: row for row in model.entries[0].detail_rows}

    assert set(rows) == {"added", "removed"}
    assert rows["removed"].old_value.text == "gone"
    assert rows["removed"].new_value.text == "N/A"
    assert rows["added"].old_value.text == "N/A"
    assert rows["added"].new_value.text == "new"


def test_summary_renderers_link_main_version_github_tag_to_tag_pages() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0"),
                new_state=BuildReportState(version="1.1.0"),
                version_source={"resolver": "github_tag", "repo": "upstream/telegram"},
                component_sources={},
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "[1.0.0](https://github.com/upstream/telegram/releases/tag/1.0.0)" in markdown
    assert "[1.1.0](https://github.com/upstream/telegram/releases/tag/1.1.0)" in markdown
    assert "href=\"https://github.com/upstream/telegram/releases/tag/1.0.0\"" in html
    assert "href=\"https://github.com/upstream/telegram/releases/tag/1.1.0\"" in html


def test_summary_renderers_filter_non_https_links() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0", components={"feed": "10"}),
                new_state=BuildReportState(version="1.0.1", components={"feed": "11"}),
                version_source={"resolver": "literal", "url": "http://example.invalid/version"},
                component_sources={
                    "feed": {
                        "resolver": "regex_match",
                        "url": "ftp://example.invalid/releases.txt",
                    }
                },
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "version: 1.0.0 -> 1.0.1" in markdown
    assert "http://example.invalid/version" not in markdown
    assert "ftp://example.invalid/releases.txt" not in markdown
    assert "http://example.invalid/version" not in html
    assert "ftp://example.invalid/releases.txt" not in html


def test_summary_renderers_filter_links_with_quote_chars() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0", components={"feed": "10"}),
                new_state=BuildReportState(version="1.0.1", components={"feed": "11"}),
                version_source={
                    "resolver": "literal",
                    "url": 'https://example.invalid/version?x="q"',
                },
                component_sources={
                    "feed": {
                        "resolver": "regex_match",
                        "url": "https://example.invalid/releases?tag='bad'",
                    }
                },
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "version: 1.0.0 -> 1.0.1" in markdown
    assert 'https://example.invalid/version?x="q"' not in markdown
    assert "https://example.invalid/releases?tag='bad'" not in markdown
    assert 'https://example.invalid/version?x="q"' not in html
    assert "https://example.invalid/releases?tag='bad'" not in html


def test_summary_renderers_filter_links_with_control_or_whitespace_chars() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0", components={"feed": "10"}),
                new_state=BuildReportState(version="1.0.1", components={"feed": "11"}),
                version_source={
                    "resolver": "literal",
                    "url": "https://example.invalid/version\nnext",
                },
                component_sources={
                    "feed": {
                        "resolver": "regex_match",
                        "url": "https://example.invalid/releases\x01",
                    }
                },
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "version: 1.0.0 -> 1.0.1" in markdown
    assert "https://example.invalid/version" not in markdown
    assert "https://example.invalid/releases" not in markdown
    assert "https://example.invalid/version" not in html
    assert "https://example.invalid/releases" not in html


def test_summary_renderers_link_both_old_and_new_main_versions_when_resolvable() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0"),
                new_state=BuildReportState(version="1.0.1"),
                version_source={"resolver": "literal", "url": "https://example.invalid/releases.txt"},
                component_sources={},
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert (
        "version: [1.0.0](https://example.invalid/releases.txt)"
        " -> [1.0.1](https://example.invalid/releases.txt)"
    ) in markdown
    assert "href=\"https://example.invalid/releases.txt\">1.0.0</a>" in html
    assert "href=\"https://example.invalid/releases.txt\">1.0.1</a>" in html


def test_format_telegram_summary_uses_shared_telegram_renderer() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0"),
                new_state=BuildReportState(version="1.0.1"),
                version_source={"resolver": "literal"},
                component_sources={},
            )
        ],
        metadata={
            "trigger": "workflow_dispatch",
            "selection_mode": "manual-selectors",
            "requested_tokens_raw": "all",
            "requested_tokens_normalized": ["all"],
            "resolved_image_keys": ["telegram"],
            "resolved_entries_count": 1,
            "built_entries_count": 1,
            "force": False,
        },
    )

    assert format_telegram_summary(report) == render_summary_telegram_html(
        build_summary_model(report)
    )


def test_summary_renderers_link_each_component_to_its_own_repo() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="caddy",
                image_name="caddy",
                target_name=None,
                old_state=BuildReportState(
                    version="2.0.0",
                    components={
                        "caddy-dns/cloudflare": "aaa1111",
                        "mholt/caddy-l4": "bbb2222",
                    },
                ),
                new_state=BuildReportState(
                    version="2.1.0",
                    components={
                        "caddy-dns/cloudflare": "ccc3333",
                        "mholt/caddy-l4": "ddd4444",
                    },
                ),
                version_source={
                    "resolver": "docker_hub_tag",
                    "namespace": "library",
                    "repository": "caddy",
                },
                component_sources={
                    "caddy-dns/cloudflare": {
                        "resolver": "github_sha",
                        "repos": ["caddy-dns/cloudflare", "mholt/caddy-l4"],
                        "repo": "caddy-dns/cloudflare",
                    },
                    "mholt/caddy-l4": {
                        "resolver": "github_sha",
                        "repos": ["caddy-dns/cloudflare", "mholt/caddy-l4"],
                        "repo": "mholt/caddy-l4",
                    },
                },
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "[caddy-dns/cloudflare](https://github.com/caddy-dns/cloudflare): " in markdown
    assert "[mholt/caddy-l4](https://github.com/mholt/caddy-l4): " in markdown
    assert "[ccc3333](https://github.com/caddy-dns/cloudflare/commit/ccc3333)" in markdown
    assert "[ddd4444](https://github.com/mholt/caddy-l4/commit/ddd4444)" in markdown

    assert '<a href="https://github.com/caddy-dns/cloudflare">caddy-dns/cloudflare</a>' in html
    assert '<a href="https://github.com/mholt/caddy-l4">mholt/caddy-l4</a>' in html
    assert 'href="https://github.com/caddy-dns/cloudflare/commit/ccc3333"' in html
    assert 'href="https://github.com/mholt/caddy-l4/commit/ddd4444"' in html
    assert "caddy-dns/cloudflare/commit/ddd4444" not in html


def test_summary_renderers_use_raw_tag_for_github_tag_value_links() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="nezha-agent",
                image_name="nezha-agent",
                target_name=None,
                old_state=BuildReportState(version="2.3.4"),
                new_state=BuildReportState(version="2.3.5"),
                version_source={
                    "resolver": "github_tag",
                    "repo": "nezhahq/agent",
                    "raw_tag": "v2.3.5",
                },
                component_sources={},
            )
        ]
    )

    model = build_summary_model(report)
    markdown = render_summary_markdown(model)
    html = render_summary_telegram_html(model)

    assert "[2.3.4](https://github.com/nezhahq/agent/releases/tag/v2.3.4)" in markdown
    assert "[2.3.5](https://github.com/nezhahq/agent/releases/tag/v2.3.5)" in markdown
    assert 'href="https://github.com/nezhahq/agent/releases/tag/v2.3.5"' in html


def test_summary_renderers_apply_raw_tag_wrapper_to_previous_value() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="2.3.4"),
                new_state=BuildReportState(version="2.3.5"),
                version_source={
                    "resolver": "github_tag",
                    "repo": "upstream/telegram",
                    "raw_tag": "release-2.3.5",
                },
                component_sources={},
            )
        ]
    )

    markdown = render_summary_markdown(build_summary_model(report))

    assert "[2.3.4](https://github.com/upstream/telegram/releases/tag/release-2.3.4)" in markdown
    assert "[2.3.5](https://github.com/upstream/telegram/releases/tag/release-2.3.5)" in markdown


def test_summary_renderers_drop_unsafe_raw_tag_links() -> None:
    report = BuildReport(
        entries=[
            BuildReportEntry(
                image_key="telegram",
                image_name="telegram",
                target_name="release",
                old_state=BuildReportState(version="1.0.0"),
                new_state=BuildReportState(version="1.1.0"),
                version_source={
                    "resolver": "github_tag",
                    "repo": "upstream/telegram",
                    "raw_tag": 'v1.1.0" onclick="x',
                },
                component_sources={},
            )
        ]
    )

    model = build_summary_model(report)
    html = render_summary_telegram_html(model)

    assert "1.1.0" in html
    assert "onclick" not in html
    assert 'v1.1.0"' not in html
