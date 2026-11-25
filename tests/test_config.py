"""Tests for CSV loading, saving, legacy compatibility, and strict validation."""

from __future__ import annotations

import pytest

from udplinksim.config import (
    ConfigValidationError,
    Rule,
    load_rules_csv,
    save_rules_csv,
    validate_rules,
)


def test_load_legacy_8col_csv_defaults_loss_zero(tmp_path):
    csv_file = tmp_path / "legacy.csv"
    csv_file.write_text(
        "\ufefflisten_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms\n"
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,22001,20,3.5\n"
        "127.0.0.1,20001,127.0.0.1,0,127.0.0.1,21001,15,0\n",
        encoding="utf-8",
    )
    rules = load_rules_csv(csv_file)
    assert len(rules) == 2
    assert rules[0].loss_pct == 0.0
    assert rules[0].base_ms == 20.0
    assert rules[0].sigma_ms == 3.5
    assert rules[1].source_port == 0
    assert rules[1].loss_pct == 0.0


def test_load_9col_csv_with_loss_and_save_roundtrip(tmp_path):
    csv_file = tmp_path / "rules.csv"
    csv_file.write_text(
        "listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms,loss_pct\n"
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,22001,25.5,1.25,12.5\n"
        "127.0.0.1,20001,127.0.0.1,22001,127.0.0.1,21001,25.5,1.25,\n",
        encoding="utf-8",
    )
    rules = load_rules_csv(csv_file)
    assert rules[0].loss_pct == 12.5
    assert rules[1].loss_pct == 0.0

    out_file = tmp_path / "saved.csv"
    save_rules_csv(out_file, rules)
    reloaded = load_rules_csv(out_file)
    assert reloaded == rules


@pytest.mark.parametrize(
    "bad_row",
    [
        # 0.0.0.0 listen_ip
        "0.0.0.0,20001,127.0.0.1,21001,127.0.0.1,22001,20,0,0",
        # 0.0.0.0 target_ip
        "127.0.0.1,20001,127.0.0.1,21001,0.0.0.0,22001,20,0,0",
        # listen_port == 0
        "127.0.0.1,0,127.0.0.1,21001,127.0.0.1,22001,20,0,0",
        # target_port == 0
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,0,20,0,0",
        # port out of range
        "127.0.0.1,70000,127.0.0.1,21001,127.0.0.1,22001,20,0,0",
        # listen == target
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,20001,20,0,0",
        # listen == source
        "127.0.0.1,20001,127.0.0.1,20001,127.0.0.1,22001,20,0,0",
        # source == target
        "127.0.0.1,20001,127.0.0.1,22001,127.0.0.1,22001,20,0,0",
        # negative delay
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,22001,-1,0,0",
        # NaN sigma
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,22001,20,nan,0",
        # inf base_ms
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,22001,inf,0,0",
        # loss < 0
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,22001,20,0,-0.1",
        # loss > 100
        "127.0.0.1,20001,127.0.0.1,21001,127.0.0.1,22001,20,0,100.1",
        # invalid IPv4
        "999.1.1.1,20001,127.0.0.1,21001,127.0.0.1,22001,20,0,0",
    ],
)
def test_reject_invalid_rows(tmp_path, bad_row):
    csv_file = tmp_path / "bad.csv"
    csv_file.write_text(
        "listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms,loss_pct\n"
        + bad_row
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError):
        load_rules_csv(csv_file)


def test_reject_ambiguous_duplicates_allow_exact_plus_wildcard():
    exact = Rule("127.0.0.1", 20001, "127.0.0.1", 21001, "127.0.0.1", 22001, 10, 0, 0)
    wild = Rule("127.0.0.1", 20001, "127.0.0.1", 0, "127.0.0.1", 22002, 10, 0, 0)
    # Exact + wildcard on same listener and IP is valid
    assert len(validate_rules([exact, wild])) == 2

    # Duplicate exact is rejected
    dup_exact = Rule("127.0.0.1", 20001, "127.0.0.1", 21001, "127.0.0.1", 22003, 5, 0, 0)
    with pytest.raises(ConfigValidationError):
        validate_rules([exact, dup_exact])

    # Duplicate wildcard is rejected
    dup_wild = Rule("127.0.0.1", 20001, "127.0.0.1", 0, "127.0.0.1", 22004, 5, 0, 0)
    with pytest.raises(ConfigValidationError):
        validate_rules([wild, dup_wild])


def test_reject_empty_csv_and_missing_columns(tmp_path):
    empty_csv = tmp_path / "empty.csv"
    empty_csv.write_text(
        "listen_ip,listen_port,source_ip,source_port,target_ip,target_port,base_ms,sigma_ms\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError):
        load_rules_csv(empty_csv, require_non_empty=True)

    bad_hdr = tmp_path / "bad_hdr.csv"
    bad_hdr.write_text("listen_ip,listen_port\n127.0.0.1,20001\n", encoding="utf-8")
    with pytest.raises(ConfigValidationError):
        load_rules_csv(bad_hdr)
