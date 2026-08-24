"""
Pruebas de telegram_notifier.py, SIN red: format_signal_message() con datos
sinteticos/incompletos, y TelegramNotifier.send_message() con requests.post
mockeado. No sustituyen a `python telegram_notifier.py --test-message`
contra la API real de Telegram.
"""
import sys

import pytest

import telegram_config
import telegram_notifier
from telegram_notifier import EXAMPLE_SIGNAL, TelegramNotifier, format_signal_message


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"ok": True, "result": {"message_id": 42}}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# format_signal_message
# ---------------------------------------------------------------------------

class TestFormatSignalMessage:
    def test_full_valid_signal(self):
        text = format_signal_message(EXAMPLE_SIGNAL)
        assert "XAUUSD" in text
        assert "FVG bullish" in text
        assert "M1" in text
        assert "CONFLUENTE" in text
        assert "2015.230" in text
        assert "2014.800 - 2015.100" in text

    def test_empty_dict_does_not_crash(self):
        text = format_signal_message({})
        assert isinstance(text, str)
        assert "?" in text
        assert "N/D" in text  # precio ausente
        assert "trigger desconocido" in text

    def test_unknown_trigger_type_falls_back_to_titleized_string(self):
        signal = dict(EXAMPLE_SIGNAL, trigger_type="mystery_pattern")
        text = format_signal_message(signal)
        assert "Mystery Pattern" in text

    def test_none_trigger_type_falls_back(self):
        signal = dict(EXAMPLE_SIGNAL, trigger_type=None)
        text = format_signal_message(signal)
        assert "trigger desconocido" in text

    def test_confluente_false(self):
        signal = dict(EXAMPLE_SIGNAL, confluente=False)
        text = format_signal_message(signal)
        assert "no confluente" in text
        assert "CONFLUENTE" not in text

    def test_confluente_none_is_not_treated_as_false(self):
        signal = dict(EXAMPLE_SIGNAL, confluente=None)
        text = format_signal_message(signal)
        assert "confluencia: ?" in text

    def test_missing_price_shows_nd(self):
        signal = dict(EXAMPLE_SIGNAL)
        del signal["price_at_detection"]
        text = format_signal_message(signal)
        assert "Precio: N/D" in text

    def test_non_numeric_price_does_not_crash(self):
        signal = dict(EXAMPLE_SIGNAL, price_at_detection="no-es-un-numero")
        text = format_signal_message(signal)
        assert "no-es-un-numero" in text

    def test_top_and_bottom_both_missing_omits_zona_line(self):
        signal = dict(EXAMPLE_SIGNAL)
        del signal["top"]
        del signal["bottom"]
        text = format_signal_message(signal)
        assert "Zona:" not in text

    def test_only_top_present_still_shows_zona_line(self):
        signal = dict(EXAMPLE_SIGNAL)
        del signal["bottom"]
        text = format_signal_message(signal)
        assert "Zona: N/D - 2015.100" in text

    def test_liquidity_sweep_label(self):
        signal = dict(EXAMPLE_SIGNAL, trigger_type="liquidity_sweep")
        text = format_signal_message(signal)
        assert "Liquidity Sweep" in text

    def test_order_block_label(self):
        signal = dict(EXAMPLE_SIGNAL, trigger_type="order_block")
        text = format_signal_message(signal)
        assert "Order Block" in text

    def test_notas_appended_when_present(self):
        signal = dict(EXAMPLE_SIGNAL, notas="contexto extra de la senal")
        text = format_signal_message(signal)
        assert "contexto extra de la senal" in text

    def test_returns_single_string_no_trailing_newline(self):
        text = format_signal_message(EXAMPLE_SIGNAL)
        assert not text.endswith("\n")


# ---------------------------------------------------------------------------
# TelegramNotifier.send_message
# ---------------------------------------------------------------------------

class TestTelegramNotifierSendMessage:
    def test_missing_credentials_returns_false_without_network_call(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", None)
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", None)
        called = {"n": 0}
        monkeypatch.setattr(telegram_notifier.requests, "post", lambda *a, **k: called.__setitem__("n", called["n"] + 1))

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is False
        assert called["n"] == 0

    def test_successful_send_returns_true(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_notifier.requests, "post", lambda *a, **k: _FakeResponse())

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is True

    def test_http_error_status_returns_false(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(
            telegram_notifier.requests, "post",
            lambda *a, **k: _FakeResponse(status_code=401, text="Unauthorized"),
        )

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is False

    def test_ok_false_payload_returns_false(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(
            telegram_notifier.requests, "post",
            lambda *a, **k: _FakeResponse(payload={"ok": False, "description": "chat not found"}),
        )

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is False

    def test_network_exception_returns_false(self, monkeypatch):
        import requests as real_requests

        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")

        def raise_conn_error(*a, **k):
            raise real_requests.ConnectionError("no network")

        monkeypatch.setattr(telegram_notifier.requests, "post", raise_conn_error)

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is False

    def test_non_json_response_returns_false(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")

        class _BadJsonResponse(_FakeResponse):
            def json(self):
                raise ValueError("not json")

        monkeypatch.setattr(telegram_notifier.requests, "post", lambda *a, **k: _BadJsonResponse())

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is False

    def test_explicit_token_and_chat_id_override_config(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", None)
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", None)
        captured = {}

        def fake_post(url, data=None, timeout=None):
            captured["url"] = url
            captured["data"] = data
            return _FakeResponse()

        monkeypatch.setattr(telegram_notifier.requests, "post", fake_post)

        notifier = TelegramNotifier(bot_token="explicit-token", chat_id="explicit-chat")
        assert notifier.send_message("hola") is True
        assert "explicit-token" in captured["url"]
        assert captured["data"]["chat_id"] == "explicit-chat"

    def test_send_signal_message_formats_and_sends(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        captured = {}

        def fake_post(url, data=None, timeout=None):
            captured["text"] = data["text"]
            return _FakeResponse()

        monkeypatch.setattr(telegram_notifier.requests, "post", fake_post)

        notifier = TelegramNotifier()
        assert notifier.send_signal_message(EXAMPLE_SIGNAL) is True
        assert "XAUUSD" in captured["text"]


# ---------------------------------------------------------------------------
# CLI --test-message
# ---------------------------------------------------------------------------

class TestCli:
    def test_test_message_success_exits_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(telegram_notifier.TelegramNotifier, "send_signal_message", lambda self, signal: True)
        monkeypatch.setattr(sys, "argv", ["telegram_notifier.py", "--test-message"])
        assert telegram_notifier.main() == 0
        out = capsys.readouterr().out
        assert "[OK]" in out

    def test_test_message_failure_exits_nonzero(self, monkeypatch, capsys):
        monkeypatch.setattr(telegram_notifier.TelegramNotifier, "send_signal_message", lambda self, signal: False)
        monkeypatch.setattr(sys, "argv", ["telegram_notifier.py", "--test-message"])
        assert telegram_notifier.main() == 1
        out = capsys.readouterr().out
        assert "[FALLO]" in out

    def test_no_args_prints_help_and_exits_zero(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "argv", ["telegram_notifier.py"])
        assert telegram_notifier.main() == 0
