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


# ---------------------------------------------------------------------------
# Auditoria: manejo de HTTP 429 (rate limit) y throttling del lado del
# cliente. time.sleep/time.monotonic mockeados para no ralentizar los tests.
# ---------------------------------------------------------------------------

def _sequence_post(responses):
    """requests.post falso que devuelve una respuesta distinta por llamada,
    en orden, y cuenta cuantas veces se llamo."""
    calls = {"n": 0}

    def fake_post(*args, **kwargs):
        r = responses[calls["n"]]
        calls["n"] += 1
        return r

    return fake_post, calls


class TestRetryAfter429:
    def test_extract_retry_after_reads_body_field(self):
        resp = _FakeResponse(status_code=429, payload={"ok": False, "parameters": {"retry_after": 7}})
        assert telegram_notifier._extract_retry_after(resp) == 7.0

    def test_extract_retry_after_falls_back_when_missing(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "DEFAULT_RETRY_AFTER_SECONDS", 2.5)
        resp = _FakeResponse(status_code=429, payload={"ok": False})
        assert telegram_notifier._extract_retry_after(resp) == 2.5

    def test_429_then_200_retries_once_and_succeeds(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_notifier.time, "sleep", lambda s: None)
        monkeypatch.setattr(telegram_notifier.time, "monotonic", lambda: 0.0)

        responses = [
            _FakeResponse(status_code=429, payload={"ok": False, "parameters": {"retry_after": 3}}),
            _FakeResponse(),  # 200 OK en el reintento
        ]
        fake_post, calls = _sequence_post(responses)
        monkeypatch.setattr(telegram_notifier.requests, "post", fake_post)

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is True
        assert calls["n"] == 2

    def test_429_then_429_fails_after_single_retry_no_loop(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_notifier.time, "sleep", lambda s: None)
        monkeypatch.setattr(telegram_notifier.time, "monotonic", lambda: 0.0)

        responses = [
            _FakeResponse(status_code=429, payload={"ok": False, "parameters": {"retry_after": 2}}),
            _FakeResponse(status_code=429, payload={"ok": False, "parameters": {"retry_after": 2}}),
        ]
        fake_post, calls = _sequence_post(responses)
        monkeypatch.setattr(telegram_notifier.requests, "post", fake_post)

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is False
        assert calls["n"] == 2  # exactamente 2 intentos, nunca mas

    def test_429_retry_sleeps_for_retry_after_value(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_notifier.time, "monotonic", lambda: 0.0)
        sleep_calls = []
        monkeypatch.setattr(telegram_notifier.time, "sleep", lambda s: sleep_calls.append(s))

        responses = [
            _FakeResponse(status_code=429, payload={"ok": False, "parameters": {"retry_after": 5}}),
            _FakeResponse(),
        ]
        fake_post, _ = _sequence_post(responses)
        monkeypatch.setattr(telegram_notifier.requests, "post", fake_post)

        TelegramNotifier().send_message("hola")
        assert 5.0 in sleep_calls

    def test_network_error_on_retry_returns_false(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_notifier.time, "sleep", lambda s: None)
        monkeypatch.setattr(telegram_notifier.time, "monotonic", lambda: 0.0)

        calls = {"n": 0}

        def fake_post(*a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse(status_code=429, payload={"ok": False, "parameters": {"retry_after": 1}})
            raise telegram_notifier.requests.ConnectionError("caida en el reintento")

        monkeypatch.setattr(telegram_notifier.requests, "post", fake_post)

        notifier = TelegramNotifier()
        assert notifier.send_message("hola") is False
        assert calls["n"] == 2


class TestClientSideThrottle:
    def test_second_call_waits_remaining_time(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_config, "MIN_SECONDS_BETWEEN_MESSAGES", 1.0)
        monkeypatch.setattr(telegram_notifier.requests, "post", lambda *a, **k: _FakeResponse())

        clock = {"t": 1000.0}
        monkeypatch.setattr(telegram_notifier.time, "monotonic", lambda: clock["t"])

        sleep_calls = []

        def fake_sleep(seconds):
            sleep_calls.append(seconds)
            clock["t"] += seconds  # simula que el tiempo avanza mientras "duerme"

        monkeypatch.setattr(telegram_notifier.time, "sleep", fake_sleep)

        notifier = TelegramNotifier()
        notifier.send_message("uno")

        clock["t"] += 0.1  # la siguiente llamada ocurre 0.1s despues
        notifier.send_message("dos")

        assert sleep_calls == [pytest.approx(0.9)]

    def test_no_wait_if_enough_time_already_passed(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_config, "MIN_SECONDS_BETWEEN_MESSAGES", 1.0)
        monkeypatch.setattr(telegram_notifier.requests, "post", lambda *a, **k: _FakeResponse())

        clock = {"t": 1000.0}
        monkeypatch.setattr(telegram_notifier.time, "monotonic", lambda: clock["t"])
        sleep_calls = []
        monkeypatch.setattr(telegram_notifier.time, "sleep", lambda s: sleep_calls.append(s))

        notifier = TelegramNotifier()
        notifier.send_message("uno")

        clock["t"] += 2.0  # bastante mas que MIN_SECONDS_BETWEEN_MESSAGES
        notifier.send_message("dos")

        assert sleep_calls == []

    def test_first_call_never_throttles(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_notifier.requests, "post", lambda *a, **k: _FakeResponse())
        monkeypatch.setattr(telegram_notifier.time, "monotonic", lambda: 1000.0)
        sleep_calls = []
        monkeypatch.setattr(telegram_notifier.time, "sleep", lambda s: sleep_calls.append(s))

        notifier = TelegramNotifier()
        notifier.send_message("uno")
        assert sleep_calls == []

    def test_throttle_applies_across_multiple_signal_sends(self, monkeypatch):
        monkeypatch.setattr(telegram_config, "TELEGRAM_BOT_TOKEN", "dummy-token")
        monkeypatch.setattr(telegram_config, "TELEGRAM_CHAT_ID", "12345")
        monkeypatch.setattr(telegram_config, "MIN_SECONDS_BETWEEN_MESSAGES", 1.0)
        monkeypatch.setattr(telegram_notifier.requests, "post", lambda *a, **k: _FakeResponse())

        clock = {"t": 1000.0}
        monkeypatch.setattr(telegram_notifier.time, "monotonic", lambda: clock["t"])
        sleep_calls = []
        monkeypatch.setattr(telegram_notifier.time, "sleep", lambda s: sleep_calls.append(s))

        notifier = TelegramNotifier()
        notifier.send_signal_message(EXAMPLE_SIGNAL)
        notifier.send_signal_message(EXAMPLE_SIGNAL)  # mismo instante simulado -> deberia esperar ~1s

        assert sleep_calls == [pytest.approx(1.0)]
