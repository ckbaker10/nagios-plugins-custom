"""Synthetic monitoring contracts; no external mail, DNS or HTTP requests."""

import contextlib
import copy
import datetime as dt
import importlib.util
import io
import json
import os
import pathlib
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

PATH = pathlib.Path(os.environ.get("NPC_MAIL_REPORT_PLUGIN",
                    pathlib.Path(__file__).resolve().parents[1] / "check_mail_report.py"))
SPEC = importlib.util.spec_from_file_location("check_mail_report", PATH)
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)
NOW = dt.datetime(2026, 10, 8, 12, tzinfo=dt.timezone.utc)
TOKEN = "A" * 32


def report(now=NOW):
    return {
        "schema_version": 1, "validator_version": "1.1.0",
        "created_at": now.isoformat(), "expires_at": (now + dt.timedelta(hours=1)).isoformat(),
        "status": "ohne_festgestellte_probleme",
        "checks": [
            {"name": "SPF", "code": "spf_pass", "result": "pass", "level": "ok", "detail": "private test text"},
            {"name": "DKIM", "code": "unsigned", "result": "none", "level": "hinweis"},
            {"name": "DMARC", "code": "aligned", "result": "pass", "level": "ok"},
            {"name": "Metadaten", "code": "metadata_observed", "result": "observed", "level": "ok"},
        ],
        "rating": {"version": 1, "state": "complete", "scope": "message_and_last_hop", "score": 90, "grade": "A", "missing": []},
    }


@contextlib.contextmanager
def http_peer(status=200, body=None, headers=None, trickle=False):
    requests, stopped = [], threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            requests.append(self.path)
            data = body if body is not None else json.dumps(report(dt.datetime.now(dt.timezone.utc))).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            try:
                if trickle:
                    for byte in data:
                        self.wfile.write(bytes([byte]))
                        self.wfile.flush()
                        if stopped.wait(0.03):
                            break
                else:
                    self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        stopped.set()
        server.shutdown()
        server.server_close()
        thread.join()


def cli(cfg, *args, config_mode=0o600):
    with tempfile.TemporaryDirectory() as directory:
        path = pathlib.Path(directory) / "config.json"
        path.write_text(json.dumps(cfg))
        path.chmod(config_mode)
        return subprocess.run([sys.executable, str(PATH), "--config", str(path), *args],
                              capture_output=True, text=True, timeout=5, check=False)


class AssessmentTest(unittest.TestCase):
    def evaluate(self, data=None, cfg=None, **kwargs):
        return PLUGIN.evaluate(report() if data is None else data, cfg or {}, NOW, NOW, 300, **kwargs)

    def rejects(self, data, text=None, **kwargs):
        with self.assertRaises(PLUGIN.Failure) as caught:
            self.evaluate(data, **kwargs)
        self.assertEqual(caught.exception.status, 3)
        if text:
            self.assertIn(text, str(caught.exception))

    def test_baseline_does_not_require_direct_probe_dkim_pass(self):
        self.assertEqual(self.evaluate()[0], 0)
        data = report()
        data["extra"] = {"future": 1}
        data["checks"][0]["detail"] = "Völlig anderer Text"
        data["checks"].append({"name": "Future option", "code": "future", "result": "future_result", "level": "unbekannt"})
        data.pop("rating")
        self.assertEqual(self.evaluate(data)[0], 0)

    def test_expectations_priority_and_multiple_signatures(self):
        critical = {"name": "DKIM", "codes": ["signature_valid"], "result": "pass"}
        warning = dict(critical, severity="warning")
        self.assertEqual(self.evaluate(cfg={"expect": [warning]})[0], 1)
        self.assertEqual(self.evaluate(cfg={"expect": [warning, critical]})[0], 2)
        data = report()
        data["checks"].append({"name": "DKIM", "code": "signature_valid", "result": "pass", "level": "ok"})
        self.assertEqual(self.evaluate(data, cfg={"expect": [critical]})[0], 2)
        self.assertEqual(self.evaluate(data, cfg={"expect": [dict(critical, match="any")]})[0], 0)
        self.rejects(report(), cfg={"expect": [dict(critical, name="Absent")]})
        data["checks"].append({"name": "WKD", "code": "wkd_unavailable", "result": "unknown", "level": "unbekannt"})
        self.rejects(data, cfg={"expect": [{"name": "WKD", "codes": ["wkd_found"]}]})

    def test_incomplete_or_unknown_semantics_never_succeed(self):
        changes = [
            {"schema_version": 2}, {"schema_version": True}, {"validator_version": ""},
            {"status": "future"}, {"status": "unvollstaendig"}, {"checks": []},
            {"permanent_example": True}, {"created_at": "bad"}, {"expires_at": NOW.isoformat()},
            {"created_at": (NOW - dt.timedelta(seconds=301)).isoformat()},
            {"created_at": (NOW - dt.timedelta(seconds=6)).isoformat()},
            {"created_at": (NOW + dt.timedelta(seconds=6)).isoformat()},
            {"created_at": "2026-10-08T12:00:00"},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.rejects(dict(report(), **change))
        for key, value in (("result", "future"), ("level", "future"), ("level", "unbekannt"), ("level", "problem"),
                           ("code", "spf_fail"), ("code", "future_core_code")):
            data = report()
            data["checks"][0][key] = value
            self.rejects(data)

    def test_rating_is_opt_in_but_strict_when_selected(self):
        for key, value in (("version", 2), ("version", True), ("state", "incomplete"), ("scope", "future"),
                           ("score", True), ("score", 101), ("missing", ["SPF"]), ("grade", "S")):
            data = report()
            data["rating"][key] = value
            self.assertEqual(self.evaluate(data)[0], 0)
            self.rejects(data, warning=PLUGIN.Range("95:"))
        self.assertEqual(self.evaluate(warning=PLUGIN.Range("95:"))[0], 1)
        self.assertEqual(self.evaluate(warning=PLUGIN.Range("95:"), critical=PLUGIN.Range("91:"))[0], 2)
        data = report()
        data["rating"]["grade"] = "E"  # A rating cap may lower the grade independently of score.
        self.assertEqual(self.evaluate(data, warning=PLUGIN.Range("90:"))[0], 0)

    def test_ranges_include_endpoints_and_support_inversion(self):
        for text, value, alert in (("10", 10, False), ("10", -1, True), ("90:", 89, True),
                                   ("90:", 90, False), ("~:10", -100, False), ("@10:20", 20, True),
                                   ("@10:20", 21, False), (":", 0, False), ("-2:2", -2, False)):
            self.assertEqual(PLUGIN.Range(text).alerts(value), alert)
        for text in ("", "@", "nan", "inf", "20:10", "1:2:3", "~", "90:|secret=1", "1\n"):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.Range(text)

    def test_json_limits_duplicates_and_invalid_numbers(self):
        for raw in (b"[]", b"{", b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":' + b"[" * 17 + b"0" + b"]" * 17 + b"}",
                    json.dumps({"a": list(range(16384))}).encode()):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.parse_json(raw)
        self.assertEqual(PLUGIN.parse_json(b'{"a":"[\\\"{]"}'), {"a": '["{]'})

    def test_output_only_contains_fixed_labels_and_numeric_metrics(self):
        status, metrics = self.evaluate(warning=PLUGIN.Range("95:"))
        line = PLUGIN.output(status, dict(metrics, http_time=0.012), PLUGIN.Range("95:"))
        self.assertTrue(line.startswith("WARNING - mail expectation warning | "))
        self.assertIn("score=90.000;95:;;0;100", line)
        self.assertNotIn("private", line)
        self.assertLess(len(line), 512)


class TransportTest(unittest.TestCase):
    def settings(self, base):
        return {"origin": base, "allow_loopback_http": True, "report_url": base + "/r/" + TOKEN}

    def assert_result(self, result, status):
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertTrue(result.stdout.startswith(PLUGIN.STATUSES[status] + " - "))
        self.assertEqual(result.stdout.count("\n"), 1)
        self.assertNotIn(TOKEN, result.stdout)
        self.assertNotIn("private test text", result.stdout)
        self.assertNotIn("proxy", result.stdout)
        self.assertNotIn("secret", result.stdout)

    def test_real_get_and_no_smtp_in_report_mode(self):
        with http_peer() as (base, requests):
            result = cli(self.settings(base), "--mode", "report")
            self.assert_result(result, 0)
            self.assertEqual(requests, ["/api/v1/reports/" + TOKEN])

    def test_http_status_redirect_type_size_and_json_failures(self):
        cases = [
            (404, b"secret proxy body", {}, 3), (410, b"private", {}, 3),
            (503, b"private proxy HTML", {}, 2), (403, b"private", {}, 2),
            (302, b"", {"Location": "http://outside.invalid/r/" + TOKEN}, 3),
            (200, b"{", {}, 3), (200, b"x" * (PLUGIN.MAX_BODY + 1), {}, 3),
            (200, b"{}", {"Content-Type": "text/html"}, 3),
            (200, b"{}", {"Content-Encoding": "gzip"}, 3),
        ]
        for status, body, headers, expected in cases:
            with self.subTest(status=status, expected=expected), http_peer(status, body, headers) as (base, requests):
                self.assert_result(cli(self.settings(base), "--mode", "report"), expected)
                self.assertEqual(len(requests), 1)

    def test_trickling_body_obeys_whole_run_deadline(self):
        with http_peer(trickle=True) as (base, _requests):
            started = time.monotonic()
            self.assert_result(cli(self.settings(base), "--mode", "report", "--timeout", "0.2"), 2)
            self.assertLess(time.monotonic() - started, 1.5)

    def test_dns_wait_is_inside_deadline(self):
        def blocked_resolver(*_args, **_kwargs):
            # Simulate a native resolver that never runs Python's alarm handler.
            signal.signal(signal.SIGALRM, signal.SIG_IGN)
            time.sleep(5)

        cfg = {"origin": "https://mail.invalid", "report_url": "https://mail.invalid/r/" + TOKEN}
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "config.json"
            path.write_text(json.dumps(cfg))
            path.chmod(0o600)
            started = time.monotonic()
            with mock.patch.object(socket, "getaddrinfo", side_effect=blocked_resolver), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(PLUGIN.main(["--config", str(path), "--mode", "report", "--timeout", "0.1"]), 2)
            self.assertIn("deadline", out.getvalue())
            self.assertLess(time.monotonic() - started, 1)
            with self.assertRaises(ChildProcessError):
                os.waitpid(-1, os.WNOHANG)

    def test_cancel_handler_and_timer_are_restored(self):
        old = signal.getsignal(signal.SIGTERM)
        with self.assertRaises(PLUGIN.Failure):
            with PLUGIN.deadline(1):
                os.kill(os.getpid(), signal.SIGTERM)
        self.assertEqual(signal.getsignal(signal.SIGTERM), old)
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_origin_and_reference_boundaries(self):
        for base in ("http://outside.invalid", "https://user:secret@valid.invalid", "https://valid.invalid/path",
                     "https://valid.invalid?query", "https://valid.invalid#fragment", "https://valid.invalid\\outside", "https://valid.invalid:bad"):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.origin(base, True)
        base = "https://valid.invalid"
        for url in (base + "/r/" + TOKEN + "?secret=1", base + "/r/" + TOKEN + "#fragment",
                    base + ".outside/r/" + TOKEN, base + "/api/v1/reports/" + TOKEN, base + "/r/%41" + TOKEN[1:]):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.report_token(url, base)

    def test_config_and_cli_errors_do_not_expose_values(self):
        cfg = self.settings("http://127.0.0.1:1")
        self.assert_result(cli(cfg, "--mode", "report", config_mode=0o644), 3)
        self.assert_result(cli(cfg, "--mode", "report", "--unknown-secret", TOKEN), 3)
        self.assert_result(cli(cfg, "--mode", "report", "--timeout", "nan"), 3)
        self.assert_result(cli(cfg, "--mode", "report", "--warning", ""), 3)
        with self.assertRaises(PLUGIN.Failure):
            PLUGIN.configuration(dict(cfg, expect=[{"name": "DKIM", "codes": [], "severity": "warning"}]), "report")
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "file"
            path.write_text(json.dumps(cfg))
            path.chmod(0o600)
            link = pathlib.Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                PLUGIN.protected_config(link)

    def test_network_refusal_is_critical(self):
        with socket.socket() as peer:
            peer.bind(("127.0.0.1", 0))
            base = "http://127.0.0.1:" + str(peer.getsockname()[1])
            self.assert_result(cli(self.settings(base), "--mode", "report"), 2)

    def test_smtp_response_is_bounded_and_transport_failure_is_critical(self):
        class Peer(socketserver.BaseRequestHandler):
            def handle(self):
                try:
                    self.request.sendall(b"220-private\r\n" * 2000 + b"220 ready\r\n")
                except (BrokenPipeError, ConnectionResetError):
                    pass

        with socketserver.TCPServer(("127.0.0.1", 0), Peer) as server:
            thread = threading.Thread(target=server.handle_request)
            thread.start()
            cfg = dict(self.settings("http://127.0.0.1:1"), smtp_host="127.0.0.1", smtp_port=server.server_address[1],
                       smtp_tls="loopback_plain", sender="monitor@example.test", recipient="check@example.test", helo="monitor.example.test")
            self.assert_result(cli(cfg), 3)
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assert_result(cli(cfg), 2)
        for updates in ({"recipient": "reply@example.test"}, {"smtp_tls": "loopback_plain", "smtp_host": "outside.invalid"},
                        {"smtp_user": "secret", "smtp_password": "secret"}):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.configuration(copy.deepcopy(dict(cfg, **updates)), "probe")

    def test_direct_data_response_and_fresh_report_are_both_required(self):
        with http_peer() as (base, requests):
            cases = [
                (b"250 complete\r\n", 2),
                (b"451 temporary private failure\r\n", 2),
                (b"550 private rejection\r\n", 2),
                (b"250 https://outside.invalid/r/" + TOKEN.encode() + b"\r\n", 3),
                (b"250 " + base.encode() + b"/r/" + TOKEN.encode() + b"?secret=1\r\n", 3),
                (b"250 " + base.encode() + b"/r/" + TOKEN.encode() + b"\r\n", 0),
            ]
            for response, expected in cases:
                class Peer(socketserver.StreamRequestHandler):
                    def handle(self):
                        self.wfile.write(b"220 fixture\r\n")
                        while line := self.rfile.readline(8192):
                            if line.upper().startswith(b"DATA"):
                                self.wfile.write(b"354 continue\r\n")
                                while self.rfile.readline(8192) != b".\r\n":
                                    pass
                                self.wfile.write(response)
                                return
                            self.wfile.write(b"250 fixture\r\n")

                with self.subTest(expected=expected), socketserver.TCPServer(("127.0.0.1", 0), Peer) as server:
                    thread = threading.Thread(target=server.handle_request)
                    thread.start()
                    cfg = dict(self.settings(base), smtp_host="127.0.0.1", smtp_port=server.server_address[1],
                               smtp_tls="loopback_plain", sender="monitor@example.test", recipient="check@example.test", helo="monitor.example.test")
                    self.assert_result(cli(cfg), expected)
                    thread.join(timeout=2)
                    self.assertFalse(thread.is_alive())
            self.assertEqual(requests, ["/api/v1/reports/" + TOKEN])


if __name__ == "__main__":
    unittest.main()
