"""
The synthetic generator plants a known set of problems and writes them to
data/injected_anomalies.csv. If the reconciliation is right, it finds exactly
that set: nothing missed, nothing invented.
"""

import sys
from pathlib import Path

import duckdb
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import generate_data  # noqa: E402
import reconcile  # noqa: E402


@pytest.fixture(scope="module")
def results():
    generate_data.main()
    return reconcile.run()


@pytest.fixture(scope="module")
def truth():
    return pd.read_csv(ROOT / "data" / "injected_anomalies.csv", dtype=str)


def as_set(df):
    return set(zip(df["vat"], df["anomaly_type"]))


def test_every_planted_anomaly_is_found(results, truth):
    missed = as_set(truth) - as_set(results["anomalies"])
    assert not missed, f"Missed: {sorted(missed)}"


def test_no_false_positives(results, truth):
    extra = as_set(results["anomalies"]) - as_set(truth)
    assert not extra, f"Flagged but not planted: {sorted(extra)}"


def test_rounding_noise_is_not_flagged(results):
    mismatches = results["anomalies"].query("anomaly_type == 'amount_mismatch'")
    assert len(mismatches) == 12


@pytest.mark.parametrize("raw, expected", [
    ("Rossi Logistica S.r.l.", "ROSSI LOGISTICA"),
    ("ROSSI  LOGISTICA SRL", "ROSSI LOGISTICA"),
    ("rossi logistica s.r.l.s.", "ROSSI LOGISTICA"),
    ("Bianchi Energia S.p.A.", "BIANCHI ENERGIA"),
    ("Foà  Trasporti S.n.c.", "FOA TRASPORTI"),
])
def test_name_key(raw, expected):
    con = duckdb.connect()
    reconcile.run_sql(con, "01_staging.sql", data_dir=(ROOT / "data").as_posix())
    assert con.execute("SELECT name_key(?)", [raw]).fetchone()[0] == expected


@pytest.mark.parametrize("raw, expected", [
    ("IT 01234567890", "01234567890"),
    ("01234 567890", "01234567890"),
    ("12345", None),
    ("", None),
])
def test_vat_key(raw, expected):
    con = duckdb.connect()
    reconcile.run_sql(con, "01_staging.sql", data_dir=(ROOT / "data").as_posix())
    assert con.execute("SELECT vat_key(?)", [raw]).fetchone()[0] == expected


@pytest.mark.parametrize("deal_name, valid", [
    ("ROSSI LOGISTICA | FLEX | 2025", True),
    ("FOÀ TRASPORTI | CORE | 2025", True),
    ("rossi logistica | flex | 2025", False),
    ("ROSSI LOGISTICA - FLEX - 2025", False),
    ("ROSSI LOGISTICA | FLEX", False),
])
def test_deal_name_pattern(deal_name, valid):
    pattern = reconcile.load_rules()["deal_name_pattern"]
    con = duckdb.connect()
    assert con.execute("SELECT regexp_full_match(?, ?)", [deal_name, pattern]).fetchone()[0] is valid
