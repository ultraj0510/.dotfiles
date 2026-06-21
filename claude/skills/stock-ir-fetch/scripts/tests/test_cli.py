import json
import sys

import fetch_stock_ir as module


def test_main_prints_json_only_to_stdout(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        module,
        "fetch_stock_ir",
        lambda ticker, data_dir, now=None, refresh=False,
               approve_candidate=None, approve_url=None, dependencies=None: {
            "status": "success",
            "ticker": ticker,
        },
    )

    exit_code = module.main(["285A", "--data-dir", str(tmp_path)])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert json.loads(captured.out) == {"status": "success", "ticker": "285A"}
    assert captured.err == ""


def test_main_returns_one_for_failed(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        module,
        "fetch_stock_ir",
        lambda ticker, data_dir, now=None, refresh=False,
               approve_candidate=None, approve_url=None, dependencies=None: {
            "status": "failed",
            "ticker": "",
        },
    )

    exit_code = module.main(["bad", "--data-dir", str(tmp_path)])

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
