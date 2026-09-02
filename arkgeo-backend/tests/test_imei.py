"""Tests for passive IMEI / MEID intelligence."""
from __future__ import annotations

import pytest

from app.services.imei_analysis import (
    _luhn_check_digit,
    analyze_identifier,
    validate_imei,
)


def _valid_imei(prefix14: str) -> str:
    return prefix14 + str(_luhn_check_digit(prefix14))


def test_luhn_check_digit_known():
    # 49015420323751 -> check digit 8 (well-known example IMEI 490154203237518)
    assert _luhn_check_digit("49015420323751") == 8


def test_validate_imei_valid_and_invalid():
    good = _valid_imei("49015420323751")
    assert validate_imei(good)["valid"] is True
    # tamper last digit
    bad = good[:-1] + ("8" if good[-1] != "8" else "7")
    assert validate_imei(bad)["valid"] is False


def test_validate_imei_length_and_chars():
    assert validate_imei("123")["valid"] is False
    # 16 digits is a valid IMEI-SV, not invalid
    assert validate_imei("4901542032375180")["kind"] == "IMEI-SV"
    assert validate_imei("49015420323751XX")["valid"] is False


def test_analyze_identifier_imei_structure():
    good = _valid_imei("49015420323751")  # LG RBI 49, TAC 49015420 in seed (6-digit key)
    r = analyze_identifier(good)
    assert r["ok"] is True
    assert r["kind"] == "IMEI"
    assert r["structure"]["tac"] == "49015420"
    assert r["structure"]["rbi"] == "49"
    assert r["manufacturer"] == "LG"
    assert r["model"] is not None  # seed TAC db hit
    assert r["confidence"] in ("high", "medium", "low")


def test_analyze_identifier_meid():
    r = analyze_identifier("A1000000923456")
    assert r["ok"] is True
    assert r["kind"] == "MEID"


def test_analyze_identifier_unknown_is_serial():
    r = analyze_identifier("C02XX1YYFD")  # Apple-style serial, not IMEI/MEID
    assert r["ok"] is True
    assert r["kind"] == "serial_or_unknown"
    assert r["confidence"] == "low"
