"""Synthetic Postfix queue correlation, rotation and deadline checks."""

import contextlib
import io
import json
import pathlib
import socketserver
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_check_mail_report import PLUGIN, TOKEN, http_peer


class PostfixTest(unittest.TestCase):
    def settings(self):
        return dict(origin="https://validator.example.test", smtp_host="127.0.0.1",
                    smtp_port=25, smtp_tls="loopback_plain", sender="monitor@example.test",
                    recipient="check@validator.example.test", helo="monitor.example.test")

    def line(self, queue="ABCDE12345", status="sent", url=None, process="smtp", code=250):
        url = url or "https://validator.example.test/r/" + TOKEN
        return f"date host postfix/{process}[123]: {queue}: to=<private>, status={status} ({code} {url})\n".encode()

    def test_postfix_profile_rejects_remote_and_credentials(self):
        self.assertEqual(PLUGIN.configuration(self.settings(), "postfix")["smtp_host"], "127.0.0.1")
        for updates in ({"smtp_host": "remote.example.test", "smtp_tls": "starttls"},
                        {"smtp_tls": "implicit"}, {"smtp_user": "private", "smtp_password": "private"}):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.configuration(dict(self.settings(), **updates), "postfix")

    def test_queue_response_does_not_require_direct_report_link(self):
        cfg = self.settings()
        with mock.patch.object(PLUGIN, "BoundedSMTP") as smtp:
            peer = smtp.return_value
            peer.ehlo.return_value = (250, b"ready")
            peer.mail.return_value = peer.rcpt.return_value = (250, b"ok")
            peer.data.return_value = (250, b"2.0.0 Ok: queued as ABCDE12345")
            self.assertEqual(PLUGIN.smtp_probe(cfg, None, 2, queued=True), "ABCDE12345")
            message = peer.data.call_args.args[0]
            self.assertIn(b"Message-ID:", message)
            self.assertIn(b"Auto-Submitted: auto-generated", message)
            for response in (b"queued", b"queued as ABCDE queued as FGHIJ"):
                peer.data.return_value = (250, response)
                with self.assertRaises(PLUGIN.Failure):
                    PLUGIN.smtp_probe(cfg, None, 2, queued=True)

    def test_matches_only_new_exact_queue_and_outgoing_smtp(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "mail.log"
            path.write_bytes(self.line())  # Old matching delivery must be ignored.
            with contextlib.closing(PLUGIN.PostfixLog(path)) as log:
                self.assertEqual(log.lines(), [])
                with path.open("ab") as stream:
                    stream.write(self.line(queue="OTHER12345"))
                    stream.write(self.line(queue="XABCDE12345"))
                    stream.write(self.line(process="smtpd"))
                    stream.write(self.line(code=251))
                    stream.write(self.line())
                self.assertEqual(log.report("ABCDE12345", self.settings()["origin"]), TOKEN)

    def test_partial_lines_rotation_and_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "mail.log"
            path.touch()
            with contextlib.closing(PLUGIN.PostfixLog(path)) as log:
                path.write_bytes(b"partial")
                self.assertEqual(log.lines(), [])
                with path.open("ab") as stream:
                    stream.write(b" line\n")
                self.assertEqual(log.lines(), [b"partial line"])
                path.rename(path.with_suffix(".old"))
                path.write_bytes(self.line())
                self.assertEqual(log.lines(), [])
                self.assertEqual(log.report("ABCDE12345", self.settings()["origin"]), TOKEN)
                path.write_bytes(b"short\n")
                self.assertEqual(log.lines(), [])
                self.assertEqual(log.lines(), [b"short"])

    def test_delivery_failure_missing_link_and_wrong_origin(self):
        for line, code in ((self.line(status="deferred", code=451), 2),
                           (self.line(status="bounced", code=550), 2),
                           (self.line(url="private"), 2),
                           (self.line(url="https://outside.invalid/r/" + TOKEN), 3),
                           (self.line(url="https://validator.example.test/r/" + TOKEN + "?x=1"), 3)):
            with tempfile.TemporaryDirectory() as directory:
                path = pathlib.Path(directory) / "mail.log"
                path.touch()
                with contextlib.closing(PLUGIN.PostfixLog(path)) as log:
                    path.write_bytes(line)
                    with self.assertRaises(PLUGIN.Failure) as caught:
                        log.report("ABCDE12345", self.settings()["origin"])
                    self.assertEqual(caught.exception.status, code)
                    self.assertNotIn(TOKEN, str(caught.exception))

    def test_wait_is_bounded_and_limits_are_enforced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "mail.log"
            path.touch()
            with contextlib.closing(PLUGIN.PostfixLog(path)) as log:
                started = time.monotonic()
                with self.assertRaises(PLUGIN.Failure), PLUGIN.deadline(0.1):
                    log.report("ABCDE12345", self.settings()["origin"])
                self.assertLess(time.monotonic() - started, 0.5)
                path.write_bytes(b"x" * 16385)
                with self.assertRaises(PLUGIN.Failure):
                    log.lines()
            path.write_bytes(b"")
            with contextlib.closing(PLUGIN.PostfixLog(path)) as log:
                log.total = PLUGIN.MAX_BODY
                path.write_bytes(b"line\n")
                with self.assertRaises(PLUGIN.Failure):
                    log.lines()
            link = pathlib.Path(directory) / "link"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                PLUGIN.PostfixLog(link)

    def test_full_postfix_submission_log_get_and_assessment(self):
        with tempfile.TemporaryDirectory() as directory, http_peer() as (base, requests):
            log_path = pathlib.Path(directory) / "mail.log"
            log_path.touch()

            class Peer(socketserver.StreamRequestHandler):
                def handle(self):
                    self.wfile.write(b"220 fixture\r\n")
                    while line := self.rfile.readline(8192):
                        if line.upper().startswith(b"DATA"):
                            self.wfile.write(b"354 continue\r\n")
                            while self.rfile.readline(8192) != b".\r\n":
                                pass
                            with log_path.open("ab") as stream:
                                stream.write(f"host postfix/smtp[123]: ABCDE12345: status=sent (250 {base}/r/{TOKEN})\n".encode())
                            self.wfile.write(b"250 queued as ABCDE12345\r\n")
                            return
                        self.wfile.write(b"250 fixture\r\n")

            with socketserver.TCPServer(("127.0.0.1", 0), Peer) as server:
                thread = threading.Thread(target=server.handle_request)
                thread.start()
                cfg = dict(self.settings(), origin=base, allow_loopback_http=True,
                           smtp_port=server.server_address[1])
                config_path = pathlib.Path(directory) / "config.json"
                config_path.write_text(json.dumps(cfg))
                config_path.chmod(0o600)
                log_type = PLUGIN.PostfixLog
                with mock.patch.object(PLUGIN, "PostfixLog", side_effect=lambda: log_type(log_path)), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    status = PLUGIN.main(["--mode", "postfix", "--config", str(config_path), "--timeout", "2"])
                thread.join(timeout=2)
                self.assertFalse(thread.is_alive())
                self.assertEqual(status, 0, output.getvalue())
                self.assertTrue(output.getvalue().startswith("OK - "))
                self.assertNotIn(TOKEN, output.getvalue())
                self.assertEqual(requests, ["/api/v1/reports/" + TOKEN])


if __name__ == "__main__":
    unittest.main()
