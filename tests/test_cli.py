"""CLI: exit codes and output formats - what CI depends on."""

from __future__ import annotations

import json

from sheetsentry.cli import EXIT_ERROR, EXIT_FINDINGS, EXIT_OK, main


def broken(build, name="case.xlsx"):
    return build(
        name=name,
        Budget=[
            ["Item", "Amount"],
            ["rent", 100],
            ["telecom", 200],
            ["software", 300],
            ["added later", 400],
            ["Total", "=SUM(B2:B4)"],
        ]
    )


def clean(build, name="case.xlsx"):
    return build(name=name, Sheet=[["Item", "Amount"], ["rent", 100], ["telecom", 200]])


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

    def test_json_findings_have_stable_ids(self, build, capsys):
        main(["audit", str(broken(build)), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["findings"][0]["finding_id"].startswith("finding_")


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


def test_review_reconciles_resolved_finding(tmp_path, build, capsys):
    report = tmp_path / "report.json"
    report.write_text(json.dumps({"file": "clean.xlsx", "findings": []}), encoding="utf-8")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"version": 1, "items": [{
        "finding_id": "finding_demo",
        "status": "correction_required",
        "owner": "finance",
        "next_action": "rerun audit",
        "due_at": "2099-01-01T00:00:00Z",
    }]}), encoding="utf-8")

    assert main(["review", str(report), "--state", str(state), "--format", "json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["records"][0]["status"] == "resolved"
    assert payload["records"][0]["verification"] == "not_present_in_audit"


def test_unimplemented_commands_say_when(capsys):
    assert main(["test", "a.xlsx"]) == EXIT_ERROR
    assert "0.3" in capsys.readouterr().err


class TestMultiFileAudit:
    """Multi-file audit: one valid structured document, files kept apart."""

    def _dupes(self, build, name="dupes.xlsx"):
        # Same shape tests/test_checks_data.py uses for a real SD003 error:
        # a recognized key column with a duplicated value.
        rows = [[f"A{i}", "item", i] for i in range(1, 25)]
        rows[9][0] = "A1"
        return build(name=name, Price=[["SKU", "Name", "Price"]] + rows)

    def test_multi_file_json_is_one_envelope_mapping_each_file(self, build, capsys):
        good = clean(build, name="good.xlsx")
        dupes = self._dupes(build)
        assert main(["audit", str(good), str(dupes), "--format", "json"]) == EXIT_FINDINGS
        payload = json.loads(capsys.readouterr().out)  # exactly one document

        assert [r["file"] for r in payload["reports"]] == [str(good), str(dupes)]
        by_file = {r["file"]: r for r in payload["reports"]}
        assert by_file[str(good)]["summary"]["total"] == 0
        assert by_file[str(dupes)]["summary"]["error"] == 1
        assert payload["errors"] == []
        # Single-file root shape is preserved inside the envelope.
        assert by_file[str(dupes)]["findings"][0]["rule"] == "SD003"

    def test_multi_file_json_output_file_parses_once(self, tmp_path, build):
        a, b = clean(build, name="a.xlsx"), self._dupes(build)
        out = tmp_path / "out.json"
        assert main(["audit", str(a), str(b), "--format", "json", "-o", str(out)]) == EXIT_FINDINGS
        payload = json.loads(out.read_text(encoding="utf-8"))
        assert len(payload["reports"]) == 2

    def test_multi_file_sarif_is_one_document_with_file_uris(self, tmp_path, build, capsys):
        import urllib.parse

        dupes = self._dupes(build)
        subdir = tmp_path / "sub dir"          # space in directory name
        subdir.mkdir()
        (subdir / "year end.xlsx").write_bytes(dupes.read_bytes())
        good = clean(build, name="good.xlsx")

        def uri(path):
            return urllib.parse.quote(path.as_posix(), safe="/:")

        assert main(
            ["audit", str(good), str(dupes), str(subdir / "year end.xlsx"),
             "--format", "sarif"]
        ) == EXIT_FINDINGS
        payload = json.loads(capsys.readouterr().out)  # exactly one document
        assert payload["version"] == "2.1.0"
        run = payload["runs"][0]
        assert len(payload["runs"]) == 1
        result_uris = {
            loc["physicalLocation"]["artifactLocation"]["uri"]
            for res in run["results"] for loc in res["locations"]
        }
        assert uri(subdir / "year end.xlsx") in result_uris  # space encoded, dir kept
        assert uri(dupes) in result_uris
        rule_ids = {rule["id"] for rule in run["tool"]["driver"]["rules"]}
        assert rule_ids == {"SD003"}                          # deduplicated
        artifact_uris = {a["location"]["uri"] for a in run["artifacts"]}
        assert artifact_uris == {uri(good), uri(dupes), uri(subdir / "year end.xlsx")}
        assert run["tool"]["driver"]["informationUri"] == "https://github.com/HlinorAI/sheetsentry"

    def test_same_basename_in_distinct_dirs_stays_distinguishable(self, tmp_path, build, capsys):
        import urllib.parse

        def uri(path):
            return urllib.parse.quote(path.as_posix(), safe="/:")

        one = tmp_path / "a"; one.mkdir()
        two = tmp_path / "b"; two.mkdir()
        (one / "same.xlsx").write_bytes(self._dupes(build, "one.xlsx").read_bytes())
        (two / "same.xlsx").write_bytes(clean(build, "two.xlsx").read_bytes())
        assert main(["audit", str(one / "same.xlsx"), str(two / "same.xlsx"),
                     "--format", "sarif"]) == EXIT_FINDINGS
        run = json.loads(capsys.readouterr().out)["runs"][0]
        result_uris = {loc["physicalLocation"]["artifactLocation"]["uri"]
                       for res in run["results"] for loc in res["locations"]}
        assert result_uris == {uri(one / "same.xlsx")}          # only this one has findings
        artifact_uris = {a["location"]["uri"] for a in run["artifacts"]}
        assert artifact_uris == {uri(one / "same.xlsx"), uri(two / "same.xlsx")}

    def test_mixed_good_and_bad_is_exit_two_with_honest_envelope(self, tmp_path, build, capsys):
        good = clean(build, name="good.xlsx")
        bad = tmp_path / "broken.xlsx"
        bad.write_bytes(b"not a workbook")
        assert main(["audit", str(good), str(bad), "--format", "json"]) == EXIT_ERROR
        payload = json.loads(capsys.readouterr().out)
        assert [r["file"] for r in payload["reports"]] == [str(good)]
        assert len(payload["errors"]) == 1
        assert payload["errors"][0]["file"] == str(bad)
        assert payload["errors"][0]["error"]

    def test_all_bad_is_exit_two_with_valid_empty_envelope(self, tmp_path, capsys):
        bad1, bad2 = tmp_path / "x.xlsx", tmp_path / "y.xlsx"
        bad1.write_bytes(b"nope"); bad2.write_bytes(b"nope")
        assert main(["audit", str(bad1), str(bad2), "--format", "json"]) == EXIT_ERROR
        payload = json.loads(capsys.readouterr().out)
        assert payload["reports"] == []
        assert [e["file"] for e in payload["errors"]] == [str(bad1), str(bad2)]

    def test_sarif_failure_becomes_invocation_notification_not_silence(self, tmp_path, build, capsys):
        bad = tmp_path / "broken.xlsx"
        bad.write_bytes(b"nope")
        good = clean(build, name="good.xlsx")
        assert main(["audit", str(good), str(bad), "--format", "sarif"]) == EXIT_ERROR
        run = json.loads(capsys.readouterr().out)["runs"][0]
        assert run["results"] == []                       # good file is clean, not hidden
        assert len(run["artifacts"]) == 1
        # SARIF 2.1.0: notifications live under run.invocations[], never on the run.
        invocation = run["invocations"][0]
        assert invocation["executionSuccessful"] is False
        assert invocation["toolExecutionNotifications"][0]["level"] == "error"
        assert "toolExecutionNotifications" not in run    # no unsupported run-level key

    def test_sarif_clean_multifile_invocation_reports_success(self, tmp_path, build, capsys):
        a = clean(build, name="a.xlsx")
        b = clean(build, name="b.xlsx")
        assert main(["audit", str(a), str(b), "--format", "sarif"]) == EXIT_OK
        run = json.loads(capsys.readouterr().out)["runs"][0]
        invocation = run["invocations"][0]
        assert invocation["executionSuccessful"] is True
        assert invocation["toolExecutionNotifications"] == []
        assert "toolExecutionNotifications" not in run    # no unsupported run-level key
        assert len(run["artifacts"]) == 2                 # both clean files observable

    def test_fail_on_never_still_exits_two_on_unreadable_file(self, tmp_path, build):
        bad = tmp_path / "broken.xlsx"
        bad.write_bytes(b"nope")
        assert main(["audit", str(bad), "--fail-on", "never", "--format", "json"]) == EXIT_ERROR

    def test_single_file_json_keeps_root_shape(self, build, capsys):
        good = clean(build, name="good.xlsx")
        assert main(["audit", str(good), "--format", "json"]) == EXIT_OK
        payload = json.loads(capsys.readouterr().out)
        assert set(payload) == {"file", "subject", "summary", "findings"}

    def test_review_rejects_multi_file_envelope_with_clear_error(self, tmp_path, build, capsys):
        a, b = clean(build, name="a.xlsx"), self._dupes(build)
        envelope = tmp_path / "envelope.json"
        assert main(["audit", str(a), str(b), "--format", "json", "-o", str(envelope)]) == EXIT_FINDINGS
        state = tmp_path / "state.json"
        state.write_text(json.dumps({"version": 1, "items": []}), encoding="utf-8")
        assert main(["review", str(envelope), "--state", str(state)]) == EXIT_ERROR
        assert "multi-file envelope" in capsys.readouterr().err
