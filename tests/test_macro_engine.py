"""
Pruebas de macro_engine.py / macro_database.py, SIN red: se prueban el
parseo, el calculo de percentil, la logica de cache/expiracion y el
filtrado del calendario usando payloads sinteticos (fixtures) o mockeando
las funciones que hacen la llamada HTTP real. No sustituyen a
`python macro_engine.py --check`, que si golpea las APIs reales.
"""
import json
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import macro_config
import macro_database
import macro_engine
from macro_engine import CalendarEvent, MacroDataError


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload

    @property
    def text(self):
        return self._payload if isinstance(self._payload, str) else json.dumps(self._payload)


# ---------------------------------------------------------------------------
# FRED parsing
# ---------------------------------------------------------------------------

class TestParseFredLatestObservation:
    def test_skips_trailing_dots(self):
        payload = {"observations": [
            {"date": "2024-01-01", "value": "1.80"},
            {"date": "2024-01-02", "value": "."},
            {"date": "2024-01-03", "value": "."},
        ]}
        assert macro_engine.parse_fred_latest_observation(payload, "DFII10") == 1.80

    def test_picks_last_real_value(self):
        payload = {"observations": [
            {"date": "2024-01-01", "value": "1.80"},
            {"date": "2024-01-02", "value": "1.85"},
        ]}
        assert macro_engine.parse_fred_latest_observation(payload, "DFII10") == 1.85

    def test_all_dots_returns_none(self):
        payload = {"observations": [{"date": "2024-01-01", "value": "."}]}
        assert macro_engine.parse_fred_latest_observation(payload, "DFII10") is None

    def test_missing_observations_key_raises(self):
        with pytest.raises(MacroDataError):
            macro_engine.parse_fred_latest_observation({}, "DFII10")

    def test_empty_observations_raises(self):
        with pytest.raises(MacroDataError):
            macro_engine.parse_fred_latest_observation({"observations": []}, "DFII10")


# ---------------------------------------------------------------------------
# Stooq CSV parsing (fallback de DXY)
# ---------------------------------------------------------------------------

class TestParseStooqCsv:
    def test_valid_csv(self):
        text = "Date,Open,High,Low,Close,Volume\n2024-01-02,102.1,102.5,101.9,102.34,0\n"
        snap = macro_engine.parse_stooq_csv(text)
        assert snap.close == 102.34
        assert snap.date == "2024-01-02"
        assert snap.source == "stooq"

    def test_multiple_rows_takes_last(self):
        text = (
            "Date,Open,High,Low,Close,Volume\n"
            "2024-01-01,100,101,99,100.5,0\n"
            "2024-01-02,100.5,102,100,101.7,0\n"
        )
        snap = macro_engine.parse_stooq_csv(text)
        assert snap.close == 101.7
        assert snap.date == "2024-01-02"

    def test_bad_header_raises(self):
        with pytest.raises(MacroDataError):
            macro_engine.parse_stooq_csv("oops,not,a,valid,header\n1,2,3,4,5\n")

    def test_no_data_rows_returns_none(self):
        assert macro_engine.parse_stooq_csv("Date,Open,High,Low,Close,Volume\n") is None

    def test_empty_text_returns_none(self):
        assert macro_engine.parse_stooq_csv("") is None


# ---------------------------------------------------------------------------
# CFTC field extraction / percentil COT
# ---------------------------------------------------------------------------

class TestExtractCftcField:
    def test_primary_field_present(self):
        row = {"m_money_positions_long_all": "12345"}
        assert macro_engine.extract_cftc_field(row, macro_engine._MM_LONG_FIELD_CANDIDATES) == 12345

    def test_falls_back_to_old_variant(self):
        row = {"m_money_positions_long_old": "999"}
        assert macro_engine.extract_cftc_field(row, macro_engine._MM_LONG_FIELD_CANDIDATES) == 999

    def test_missing_field_raises_with_available_keys_listed(self):
        row = {"some_other_field": "1"}
        with pytest.raises(MacroDataError, match="some_other_field"):
            macro_engine.extract_cftc_field(row, macro_engine._MM_LONG_FIELD_CANDIDATES)

    def test_empty_string_value_is_treated_as_missing(self):
        row = {"m_money_positions_long_all": "", "m_money_positions_long_old": "42"}
        assert macro_engine.extract_cftc_field(row, macro_engine._MM_LONG_FIELD_CANDIDATES) == 42


class TestPercentileOfLast:
    def test_max_value_is_100th_percentile(self):
        assert macro_engine.percentile_of_last([1, 2, 3, 4, 5]) == 100.0

    def test_min_value_is_lowest_percentile(self):
        # solo el propio valor es <= a si mismo -> 1/5 = 20%
        assert macro_engine.percentile_of_last([5, 4, 3, 2, 1]) == 20.0

    def test_middle_value(self):
        # ultimo valor de la lista es 25; hay 3 valores <= 25 (10, 20, 25) de 6 totales
        assert macro_engine.percentile_of_last([10, 20, 30, 40, 50, 25]) == round(3 / 6 * 100, 1)

    def test_ties_count_towards_percentile(self):
        assert macro_engine.percentile_of_last([5, 5, 5]) == 100.0

    def test_empty_raises(self):
        with pytest.raises(MacroDataError):
            macro_engine.percentile_of_last([])


# ---------------------------------------------------------------------------
# Calendario: conversion de zona horaria (sin red, lista estatica FOMC)
# ---------------------------------------------------------------------------

class TestFomcEvents:
    def test_offsets_reflect_dst(self, monkeypatch):
        # Enero (EST, UTC-5) vs Junio (EDT, UTC-4): la hora UTC del mismo
        # horario local (14:00 ET) debe diferir en 1 hora entre ambos.
        monkeypatch.setattr(macro_config, "FOMC_MEETING_DATES", ["2026-01-28", "2026-06-17"])
        events = macro_engine._fomc_events()
        jan_utc = datetime.fromisoformat(events[0].datetime_utc)
        jun_utc = datetime.fromisoformat(events[1].datetime_utc)
        assert jan_utc.hour == 19  # 14:00 EST -> 19:00 UTC
        assert jun_utc.hour == 18  # 14:00 EDT -> 18:00 UTC

    def test_all_events_are_fomc(self, monkeypatch):
        monkeypatch.setattr(macro_config, "FOMC_MEETING_DATES", ["2026-03-18"])
        events = macro_engine._fomc_events()
        assert all(e.name == "FOMC" for e in events)


# ---------------------------------------------------------------------------
# Cache (macro_database.py)
# ---------------------------------------------------------------------------

class TestMacroDatabase:
    def test_save_and_get_latest(self, tmp_path):
        db_path = str(tmp_path / "macro.db")
        with macro_database.connect(db_path) as conn:
            macro_database.save_snapshot(conn, "dxy", "2024-01-02", {"close": 102.3})
            snap = macro_database.get_latest_snapshot(conn, "dxy")
            assert snap.payload == {"close": 102.3}
            assert snap.as_of == "2024-01-02"

    def test_upsert_same_source_as_of_overwrites(self, tmp_path):
        db_path = str(tmp_path / "macro.db")
        with macro_database.connect(db_path) as conn:
            macro_database.save_snapshot(conn, "dxy", "2024-01-02", {"close": 100.0})
            macro_database.save_snapshot(conn, "dxy", "2024-01-02", {"close": 101.0})
            rows = conn.execute("SELECT COUNT(*) AS n FROM macro_snapshots").fetchone()
            assert rows["n"] == 1
            assert macro_database.get_latest_snapshot(conn, "dxy").payload == {"close": 101.0}

    def test_get_fresh_snapshot_respects_max_age(self, tmp_path):
        db_path = str(tmp_path / "macro.db")
        with macro_database.connect(db_path) as conn:
            old_fetched_at = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
            conn.execute(
                "INSERT INTO macro_snapshots (source, as_of, fetched_at, payload_json) VALUES (?, ?, ?, ?)",
                ("dxy", "2024-01-02", old_fetched_at, json.dumps({"close": 100.0})),
            )
            conn.commit()
            assert macro_database.get_fresh_snapshot(conn, "dxy", max_age_hours=20) is None
            assert macro_database.get_fresh_snapshot(conn, "dxy", max_age_hours=72) is not None

    def test_get_fresh_snapshot_missing_source_returns_none(self, tmp_path):
        db_path = str(tmp_path / "macro.db")
        with macro_database.connect(db_path) as conn:
            assert macro_database.get_fresh_snapshot(conn, "nope", max_age_hours=100) is None

    def test_get_history_orders_most_recent_first(self, tmp_path):
        db_path = str(tmp_path / "macro.db")
        with macro_database.connect(db_path) as conn:
            macro_database.save_snapshot(conn, "cot_gold", "2024-01-02", {"net": 1})
            macro_database.save_snapshot(conn, "cot_gold", "2024-01-09", {"net": 2})
            history = macro_database.get_history(conn, "cot_gold")
            assert [h.as_of for h in history] == ["2024-01-09", "2024-01-02"]


# ---------------------------------------------------------------------------
# fetch_* respetan la cache y no repiten llamadas de red (mockeadas)
# ---------------------------------------------------------------------------

class TestCachingBehavior:
    def test_fetch_real_yields_hits_network_once_then_uses_cache(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(macro_config, "FRED_API_KEY", "dummy")
        calls = {"n": 0}

        def fake_get(url, params=None, timeout=None):
            calls["n"] += 1
            series_id = params["series_id"]
            value = "1.85" if series_id == "DFII10" else "4.10"
            return _FakeResponse({"observations": [{"date": "2024-01-02", "value": value}]})

        monkeypatch.setattr(macro_engine.requests, "get", fake_get)

        snap1 = macro_engine.fetch_real_yields(use_cache=True)
        snap2 = macro_engine.fetch_real_yields(use_cache=True)

        assert snap1 == snap2 == macro_engine.RealYieldSnapshot(date="2024-01-02", dfii10=1.85, dgs10=4.10)
        assert calls["n"] == 2  # DFII10 + DGS10, UNA sola vez en total (segunda llamada usa cache)

    def test_fetch_real_yields_no_cache_hits_network_again(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(macro_config, "FRED_API_KEY", "dummy")
        calls = {"n": 0}

        def fake_get(url, params=None, timeout=None):
            calls["n"] += 1
            return _FakeResponse({"observations": [{"date": "2024-01-02", "value": "1.85"}]})

        monkeypatch.setattr(macro_engine.requests, "get", fake_get)

        macro_engine.fetch_real_yields(use_cache=False)
        macro_engine.fetch_real_yields(use_cache=False)
        assert calls["n"] == 4  # 2 llamadas (DFII10+DGS10) x 2 corridas, sin cache

    def test_fetch_real_yields_missing_api_key_raises(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(macro_config, "FRED_API_KEY", None)
        with pytest.raises(MacroDataError, match="FRED_API_KEY"):
            macro_engine.fetch_real_yields(use_cache=False)

    def test_fetch_dxy_falls_back_to_stooq_when_yfinance_fails(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(macro_engine, "_fetch_dxy_yfinance", lambda: None)
        monkeypatch.setattr(
            macro_engine, "_fetch_dxy_stooq",
            lambda: macro_engine.DxySnapshot(date="2024-01-02", close=102.3, source="stooq"),
        )
        snap = macro_engine.fetch_dxy(use_cache=False)
        assert snap.source == "stooq"

    def test_fetch_dxy_raises_if_both_sources_fail(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(macro_engine, "_fetch_dxy_yfinance", lambda: None)
        monkeypatch.setattr(macro_engine, "_fetch_dxy_stooq", lambda: None)
        with pytest.raises(MacroDataError):
            macro_engine.fetch_dxy(use_cache=False)


# ---------------------------------------------------------------------------
# fetch_economic_calendar: filtrado + aislamiento de fallos por sub-fuente
# ---------------------------------------------------------------------------

class TestFetchEconomicCalendar:
    def test_filters_to_lookahead_window(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        now = datetime.now(timezone.utc)
        past = CalendarEvent(name="NFP", datetime_utc=(now - timedelta(days=5)).isoformat(), source="test")
        near = CalendarEvent(name="CPI", datetime_utc=(now + timedelta(days=3)).isoformat(), source="test")
        far = CalendarEvent(name="FOMC", datetime_utc=(now + timedelta(days=200)).isoformat(), source="test")

        monkeypatch.setattr(macro_engine, "_fred_release_dates", lambda rid, name: [past, near] if name == "NFP" else [])
        monkeypatch.setattr(macro_engine, "_fomc_events", lambda: [far])

        events = macro_engine.fetch_economic_calendar(use_cache=False, lookahead_days=30)
        assert near in events
        assert past not in events
        assert far not in events

    def test_one_subsource_failing_does_not_block_others(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        now = datetime.now(timezone.utc)
        cpi_event = CalendarEvent(name="CPI", datetime_utc=(now + timedelta(days=2)).isoformat(), source="test")

        def broken_nfp(rid, name):
            if name == "NFP":
                raise MacroDataError("FRED caido")
            return [cpi_event]

        monkeypatch.setattr(macro_engine, "_fred_release_dates", broken_nfp)
        monkeypatch.setattr(macro_engine, "_fomc_events", lambda: [])

        events = macro_engine.fetch_economic_calendar(use_cache=False, lookahead_days=30)
        assert events == [cpi_event]

    def test_second_call_uses_cache_not_network_fns(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        now = datetime.now(timezone.utc)
        near = CalendarEvent(name="CPI", datetime_utc=(now + timedelta(days=3)).isoformat(), source="test")
        calls = {"n": 0}

        def fake_fred(rid, name):
            calls["n"] += 1
            return [near] if name == "CPI" else []

        monkeypatch.setattr(macro_engine, "_fred_release_dates", fake_fred)
        monkeypatch.setattr(macro_engine, "_fomc_events", lambda: [])

        macro_engine.fetch_economic_calendar(use_cache=True, lookahead_days=30)
        macro_engine.fetch_economic_calendar(use_cache=True, lookahead_days=30)
        assert calls["n"] == 2  # NFP + CPI, UNA sola vez en total (segunda corrida usa cache)


# ---------------------------------------------------------------------------
# collect_all: aislamiento total entre fuentes
# ---------------------------------------------------------------------------

class TestCollectAll:
    def test_one_source_failing_does_not_affect_others(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))

        def boom(use_cache):
            raise MacroDataError("FRED caido")

        monkeypatch.setattr(macro_engine, "fetch_real_yields", boom)
        monkeypatch.setattr(macro_engine, "fetch_dxy", lambda use_cache: macro_engine.DxySnapshot("2024-01-02", 102.3, "stooq"))
        monkeypatch.setattr(
            macro_engine, "fetch_cot_gold",
            lambda use_cache: macro_engine.CotSnapshot("2024-01-02", 10, 5, 5, 80.0, 100, None),
        )
        monkeypatch.setattr(macro_engine, "fetch_economic_calendar", lambda use_cache: [])

        results = macro_engine.collect_all(use_cache=True)

        assert results["real_yields"]["ok"] is False
        assert "FRED caido" in results["real_yields"]["error"]
        assert results["dxy"]["ok"] is True
        assert results["cot_gold"]["ok"] is True
        assert results["econ_calendar"]["ok"] is True


# ---------------------------------------------------------------------------
# Auditoria: un DXY corrupto (200 OK pero fuera de rango plausible) debe
# rechazarse en el camino REAL de fetch (_fetch_dxy_yfinance / parse_stooq_csv),
# no solo en sanity_check_dxy.
# ---------------------------------------------------------------------------

class _FakeYfTicker:
    def __init__(self, hist_df):
        self._hist_df = hist_df

    def history(self, period=None, interval=None):
        return self._hist_df


def _make_yf_hist(close_value, date="2024-01-02"):
    idx = pd.DatetimeIndex([pd.Timestamp(date, tz="America/New_York")])
    return pd.DataFrame({"Close": [close_value]}, index=idx)


class TestDxyPlausibilityValidation:
    def test_is_plausible_dxy_boundaries(self):
        assert macro_engine._is_plausible_dxy(70.0) is False  # limites exclusivos
        assert macro_engine._is_plausible_dxy(130.0) is False
        assert macro_engine._is_plausible_dxy(100.0) is True

    @pytest.mark.parametrize("bad_close", [0.0, -5.0, 500.0])
    def test_yfinance_corrupt_value_returns_none_not_raise(self, bad_close, monkeypatch):
        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda ticker: _FakeYfTicker(_make_yf_hist(bad_close)))
        assert macro_engine._fetch_dxy_yfinance() is None

    def test_yfinance_valid_value_still_returns_snapshot(self, monkeypatch):
        import yfinance
        monkeypatch.setattr(yfinance, "Ticker", lambda ticker: _FakeYfTicker(_make_yf_hist(103.456)))
        snap = macro_engine._fetch_dxy_yfinance()
        assert snap is not None
        assert snap.close == pytest.approx(103.456)
        assert snap.source == "yfinance"

    @pytest.mark.parametrize("bad_close", [0.0, -5.0, 500.0])
    def test_stooq_corrupt_value_returns_none_not_raise(self, bad_close):
        text = f"Date,Open,High,Low,Close,Volume\n2024-01-02,100,101,99,{bad_close},0\n"
        assert macro_engine.parse_stooq_csv(text) is None

    def test_stooq_valid_value_still_returns_snapshot(self):
        text = "Date,Open,High,Low,Close,Volume\n2024-01-02,100,101,99,103.456,0\n"
        snap = macro_engine.parse_stooq_csv(text)
        assert snap is not None
        assert snap.close == pytest.approx(103.456)
        assert snap.source == "stooq"

    def test_fetch_dxy_falls_back_to_stooq_when_yfinance_value_is_corrupt(self, tmp_path, monkeypatch):
        # _fetch_dxy_yfinance ya habria devuelto None por el valor corrupto;
        # aqui se prueba que fetch_dxy() reacciona igual que ante un fallo de red.
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(macro_engine, "_fetch_dxy_yfinance", lambda: None)
        monkeypatch.setattr(
            macro_engine, "_fetch_dxy_stooq",
            lambda: macro_engine.DxySnapshot(date="2024-01-02", close=103.2, source="stooq"),
        )
        snap = macro_engine.fetch_dxy(use_cache=False)
        assert snap.source == "stooq"

    def test_fetch_dxy_raises_when_both_sources_corrupt(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(macro_engine, "_fetch_dxy_yfinance", lambda: None)
        monkeypatch.setattr(macro_engine, "_fetch_dxy_stooq", lambda: None)
        with pytest.raises(MacroDataError):
            macro_engine.fetch_dxy(use_cache=False)

    def test_collect_all_isolates_corrupt_dxy_from_other_sources(self, tmp_path, monkeypatch):
        # Un DXY corrupto (ambas fuentes fallan la validacion) no debe tumbar
        # collect_all() ni las otras 3 fuentes -- mismo criterio de aislamiento
        # que un fallo de red.
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(macro_engine, "_fetch_dxy_yfinance", lambda: None)
        monkeypatch.setattr(macro_engine, "_fetch_dxy_stooq", lambda: None)
        monkeypatch.setattr(
            macro_engine, "fetch_real_yields",
            lambda use_cache: macro_engine.RealYieldSnapshot(date="2024-01-02", dfii10=1.8, dgs10=4.1),
        )
        monkeypatch.setattr(
            macro_engine, "fetch_cot_gold",
            lambda use_cache: macro_engine.CotSnapshot("2024-01-02", 10, 5, 5, 80.0, 100, None),
        )
        monkeypatch.setattr(macro_engine, "fetch_economic_calendar", lambda use_cache: [])

        results = macro_engine.collect_all(use_cache=True)

        assert results["dxy"]["ok"] is False
        assert results["real_yields"]["ok"] is True
        assert results["cot_gold"]["ok"] is True
        assert results["econ_calendar"]["ok"] is True

    def test_sanity_check_dxy_uses_shared_validator(self, tmp_path, monkeypatch):
        monkeypatch.setattr(macro_config, "MACRO_DB_PATH", str(tmp_path / "macro.db"))
        monkeypatch.setattr(
            macro_engine, "fetch_dxy",
            lambda use_cache: macro_engine.DxySnapshot(date="2024-01-02", close=103.2, source="yfinance"),
        )
        macro_engine.sanity_check_dxy()  # no debe lanzar
