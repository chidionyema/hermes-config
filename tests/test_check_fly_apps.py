"""Tests for scripts/check_fly_apps.py — the estate probe's Fly coverage.

Every case runs the real grading code against fixture JSON, so this exercises what ships
rather than a copy of it. The two directions are asserted throughout:

  too lax  -> the regression returns: production moves to Fly and the probe keeps grading the
              laptop, reporting green while the daemon is somewhere else entirely.
  too strict -> a permanently red section. Five tie-* apps are suspended ON PURPOSE and must
              not colour the estate.

The third verdict matters as much as the other two: when the probe cannot reach Fly it must
exit 2, never 0. A measuring instrument that reports "all clear" when it is the thing that is
broken is the failure this file exists to prevent.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

SCRIPT = Path.home() / ".hermes" / "scripts" / "check_fly_apps.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_fly_apps", SCRIPT)
    assert spec and spec.loader, f"cannot load {SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_fly_apps"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    assert SCRIPT.exists(), f"{SCRIPT} is missing; this test grades nothing without it"
    return _load()


def _fixtures(tmp_path: Path, apps: list[dict], machines: dict[str, list[dict]]) -> Path:
    d = tmp_path / "fx"
    d.mkdir()
    (d / "apps.json").write_text(json.dumps(apps))
    for name, ms in machines.items():
        (d / f"machines-{name}.json").write_text(json.dumps(ms))
    return d


def _declare(tmp_path: Path, rows: str) -> Path:
    p = tmp_path / "decl.tsv"
    p.write_text(rows)
    return p


def _run(mod, monkeypatch, decl: Path, fx: Path):
    monkeypatch.setenv("FLY_DECLARATION", str(decl))
    monkeypatch.setenv("FLY_FIXTURES", str(fx))
    return mod.main()


STARTED = [{"id": "m1", "state": "started"}]


def test_a_declared_running_app_with_started_machines_is_green(mod, monkeypatch, tmp_path, capsys):
    fx = _fixtures(tmp_path, [{"Name": "a", "Status": "deployed"}], {"a": STARTED})
    decl = _declare(tmp_path, "a\trunning\t0\tthe engine\n")
    assert _run(mod, monkeypatch, decl, fx) == 0
    assert "\u2705 a" in capsys.readouterr().out


def test_an_app_on_the_account_that_nothing_declares_is_a_fault(mod, monkeypatch, tmp_path, capsys):
    """The failure being caught is a thing running in production that nobody wrote down."""
    fx = _fixtures(tmp_path, [{"Name": "a", "Status": "deployed"},
                              {"Name": "ghost", "Status": "deployed"}],
                   {"a": STARTED, "ghost": STARTED})
    decl = _declare(tmp_path, "a\trunning\t0\tthe engine\n")
    assert _run(mod, monkeypatch, decl, fx) == 1
    assert "ghost is running on the account and nothing declares it" in capsys.readouterr().out


def test_a_declared_app_that_does_not_exist_is_a_fault(mod, monkeypatch, tmp_path, capsys):
    fx = _fixtures(tmp_path, [], {})
    decl = _declare(tmp_path, "a\trunning\t0\tthe engine\n")
    assert _run(mod, monkeypatch, decl, fx) == 1
    assert "a is declared but does not exist" in capsys.readouterr().out


def test_a_suspended_app_is_not_a_fault(mod, monkeypatch, tmp_path, capsys):
    """Five tie-* apps are parked. If parking read as a fault this section would be red
    forever, and a section that is always red is one nobody reads."""
    fx = _fixtures(tmp_path, [{"Name": "tie-api", "Status": "suspended"}], {})
    decl = _declare(tmp_path, "tie-api\tsuspended\t0\tparked since June\n")
    assert _run(mod, monkeypatch, decl, fx) == 0
    assert "tie-api suspended, on purpose" in capsys.readouterr().out


def test_a_parked_app_that_woke_up_is_a_fault(mod, monkeypatch, tmp_path, capsys):
    """It is spending money nobody decided to spend."""
    fx = _fixtures(tmp_path, [{"Name": "tie-api", "Status": "deployed"}], {"tie-api": STARTED})
    decl = _declare(tmp_path, "tie-api\tsuspended\t0\tparked since June\n")
    assert _run(mod, monkeypatch, decl, fx) == 1
    assert "declared suspended but reads" in capsys.readouterr().out


def test_a_stopped_machine_is_a_fault(mod, monkeypatch, tmp_path, capsys):
    """`fly apps list` said prospector-ci was 'deployed' while one of its three runners was
    stopped. Status alone is not liveness — the app object is deployed either way."""
    fx = _fixtures(tmp_path, [{"Name": "ci", "Status": "deployed"}],
                   {"ci": [{"id": "m1", "state": "started"}, {"id": "m2", "state": "stopped"}]})
    decl = _declare(tmp_path, "ci\trunning\t0\tthe runners\n")
    assert _run(mod, monkeypatch, decl, fx) == 1
    out = capsys.readouterr().out
    assert "1 of 2 machines not started" in out and "m2=stopped" in out


def test_a_deployed_app_with_no_machines_at_all_is_a_fault(mod, monkeypatch, tmp_path, capsys):
    fx = _fixtures(tmp_path, [{"Name": "a", "Status": "deployed"}], {"a": []})
    decl = _declare(tmp_path, "a\trunning\t0\tthe engine\n")
    assert _run(mod, monkeypatch, decl, fx) == 1
    assert "deployed but has no machines" in capsys.readouterr().out


def test_a_deploy_age_ceiling_that_cannot_be_measured_does_not_pass(mod, monkeypatch, tmp_path, capsys):
    """`fly apps list --json` returns Release: null for most apps. A ceiling set against a
    listing with no timestamp would be a check that never fires, and never firing reads exactly
    like passing."""
    fx = _fixtures(tmp_path, [{"Name": "a", "Status": "deployed"}], {"a": STARTED})
    decl = _declare(tmp_path, "a\trunning\t24\tredeployed by CI on every merge\n")
    assert _run(mod, monkeypatch, decl, fx) == 2
    assert "would be a check that never fires" in capsys.readouterr().out


def test_a_breached_deploy_age_ceiling_is_a_fault(mod, monkeypatch, tmp_path, capsys):
    fx = _fixtures(tmp_path, [{"Name": "a", "Status": "deployed",
                               "Release": {"CreatedAt": "2020-01-01T00:00:00Z"}}], {"a": STARTED})
    decl = _declare(tmp_path, "a\trunning\t24\tredeployed by CI on every merge\n")
    assert _run(mod, monkeypatch, decl, fx) == 1
    assert "the pipeline that redeploys it has stopped" in capsys.readouterr().out


def test_a_row_with_no_reason_is_not_a_declaration(mod, monkeypatch, tmp_path, capsys):
    """Same rule as the launchd allow file: one person typing a name is not a decision."""
    fx = _fixtures(tmp_path, [{"Name": "a", "Status": "deployed"}], {"a": STARTED})
    decl = _declare(tmp_path, "a\trunning\t0\t\n")
    assert _run(mod, monkeypatch, decl, fx) == 2
    assert "needs app, expect, max_deploy_h and a reason" in capsys.readouterr().out


def test_an_empty_declaration_does_not_pass(mod, monkeypatch, tmp_path, capsys):
    """A guard that iterates an empty list passes. This one must not."""
    fx = _fixtures(tmp_path, [{"Name": "a", "Status": "deployed"}], {"a": STARTED})
    decl = _declare(tmp_path, "# only comments\n")
    assert _run(mod, monkeypatch, decl, fx) == 2
    assert "declares no apps" in capsys.readouterr().out


def test_a_missing_declaration_does_not_pass(mod, monkeypatch, tmp_path, capsys):
    fx = _fixtures(tmp_path, [], {})
    assert _run(mod, monkeypatch, tmp_path / "nope.tsv", fx) == 2
    assert "no declaration at" in capsys.readouterr().out


def test_an_unreachable_fly_does_not_pass(mod, monkeypatch, tmp_path, capsys):
    """No network, no login, no CLI: exit 2, and say nothing was measured. Reporting green
    here is the outage hiding itself."""
    decl = _declare(tmp_path, "a\trunning\t0\tthe engine\n")
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _run(mod, monkeypatch, decl, empty) == 2
    out = capsys.readouterr().out
    assert "cannot establish" in out and "This is not a pass" in out


def test_the_shipped_declaration_parses(mod):
    """The real file, not a fixture. A declaration that does not parse makes the whole section
    exit 2, so a typo there silently removes Fly coverage from the estate probe."""
    decl = Path.home() / ".hermes" / "config" / "fly_apps_expected.tsv"
    assert decl.exists(), f"{decl} is missing; the FLY section grades nothing without it"
    parsed = mod.load_declaration(decl)
    for name in ("prospector-engine", "prospector-store-api", "prospector-hermes"):
        assert name in parsed, f"{name} is production and must be declared"
        assert parsed[name]["expect"] == "running"
