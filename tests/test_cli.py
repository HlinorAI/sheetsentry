"""CLI: exit codes and output formats - what CI depends on."""

from __future__ import annotations

import json

from sheetsentry.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, main


def broken(build):
    return build(
        Budget=[
            ["Item", "Amount"],
            ["rent", 100],
            ["telecom", 200],
            ["software", 300],
            ["added later", 400],
            ["Total", "=SUM(B2:B4)"],
        ]
    )


def clean(build):
    return build(Sheet=[["Item", "Amount"], ["rent", 100], ["telecom", 200]])


class TestExitCodes:
    def test_findings_return_one(self, build, capsys):
        assert main(["audit", str(broken(build))]) == EXIT_FINDINGS

    def test_clean_file_returns_zero(self, build, capsys):
        assert main(["audit", str(clean(build))]) == EXIT_OK

    def test_fail_on_never_always_returns_zero(self, build, capsys):
        assert main(["audit", str(broken(build)), "--fail-on", "never"]) == EXIT_OK

    def test_missing_file_returns_two(self, capsys):
        assert main(["audit", "no-such-file.xlsx"]) == EXIT_ERROR

    def test_wrong_extension_returns_two(self, tmp_path, capsys):
        path = tmp_path / "data.csv"
        path.write_text("a,b\n1,2\n", encoding="utf-8")
        assert main(["audit", str(path)]) == EXIT_ERROR


class TestFormats:
    def test_json_is_valid_and_has_summary(self, build, capsys):
        main(["audit", str(broken(build)), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["summary"]["total"] >= 1
        assert payload["findings"][0]["rule"]

    def test_sarif_has_rules_and_results(self, build, capsys):
        main(["audit", str(broken(build)), "--format", "sarif"])
        payload = json.loads(capsys.readouterr().out)
        run = payload["runs"][0]
        assert run["tool"]["driver"]["name"] == "SheetSentry"
        assert run["results"]
        assert {r["id"] for r in run["tool"]["driver"]["rules"]} >= {
            r["ruleId"] for r in run["results"]
        }

    def test_text_report_names_the_rule(self, build, capsys):
        main(["audit", str(broken(build))])
        assert "SF003" in capsys.readouterr().out

    def test_text_report_is_ascii_only(self, build, capsys):
        # Non-ASCII glyphs turn into mojibake on a Windows console that is
        # not in UTF-8 mode, so the human-readable report stays plain.
        main(["audit", str(broken(build))])
        capsys.readouterr().out.encode("ascii")


class TestSelection:
    def test_select_narrows_to_family(self, build, capsys):
        main(["audit", str(broken(build)), "--select", "SD", "--fail-on", "never"])
        assert "SF003" not in capsys.readouterr().out

    def test_ignore_removes_rule(self, build, capsys):
        main(["audit", str(broken(build)), "--ignore", "SF003", "--fail-on", "never"])
        assert "SF003" not in capsys.readouterr().out


def test_rules_command_lists_every_check(capsys):
    assert main(["rules"]) == EXIT_OK
    out = capsys.readouterr().out
    for rule in ("SD001", "SF001", "SF003", "SW004"):
        assert rule in out


def test_unimplemented_commands_say_when(capsys):
    assert main(["diff", "a.xlsx", "b.xlsx"]) == EXIT_ERROR
    assert "0.2" in capsys.readouterr().err
