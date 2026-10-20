"""Current report access and individually configurable finding exclusions."""

import contextlib
import io
import json
import pathlib
import signal
import tempfile
import time
import unittest
from unittest import mock

from test_check_mail_report import NOW, PLUGIN, TOKEN, cli, http_peer
from test_check_mail_report_all import full_report

CODE = "B" * 22
BASE = "https://validator.example.test"


class IgnoreTest(unittest.TestCase):
    def test_retired_message_id_history_is_ignored_present_or_absent(self):
        expectation = dict(name="Message-ID-Historie", codes=["h10_first"])
        data = self.data()
        status, metrics = self.assess(data, [], expect=[expectation])
        self.assertEqual(status, 0)
        self.assertEqual(metrics["expectations_failed"], 0)
        data["checks"].append(dict(name="Message-ID-Historie", code="h10_first",
                                   result="unknown", level="hinweis"))
        status, metrics = self.assess(data, [])
        self.assertEqual(status, 0)
        self.assertEqual(metrics["checks_ignored"], 1)
        self.assertEqual(metrics["checks_warning"], 0)
        self.assertEqual(self.assess(data, [dict(name="Message-ID-Historie", ignore=False)])[0], 1)

    def data(self):
        data = full_report()
        data["checks"][1].update(code="signature_valid", result="pass", level="ok")
        return data

    def assess(self, data, rules, **kwargs):
        cfg = dict(assess_all=True, ignore_checks=rules, **kwargs)
        return PLUGIN.evaluate(data, cfg, NOW, NOW, 300)

    def test_individual_severities_can_be_ignored_and_reenabled(self):
        for level, expected in (("problem", 2), ("unbekannt", 3), ("hinweis", 1)):
            with self.subTest(level=level):
                data = self.data()
                data["checks"].append(dict(name="DNSSEC", code="dnssec_insecure", result="insecure", level=level))
                if level == "problem":
                    data["status"] = "auffaellig"
                rule = dict(name="DNSSEC", ignore=True)
                status, metrics = self.assess(data, [rule])
                self.assertEqual(status, 0)
                self.assertEqual(metrics["checks_total"], 9)
                self.assertEqual(metrics["checks_ignored"], 1)
                self.assertEqual(metrics["score"], 90)
                rule["ignore"] = False
                self.assertEqual(self.assess(data, [rule])[0], expected)

    def test_code_filter_and_last_matching_rule_preserve_other_findings(self):
        data = self.data()
        data["checks"].extend([
            dict(name="DNSSEC", code="dnssec_insecure", result="insecure", level="hinweis"),
            dict(name="DNSSEC", code="dnssec_bogus", result="bogus", level="problem"),
        ])
        data["status"] = "auffaellig"
        rules = [dict(name="DNSSEC", codes=["dnssec_insecure"])]
        status, metrics = self.assess(data, rules)
        self.assertEqual(status, 2)
        self.assertEqual(metrics["checks_failed"], 1)
        self.assertEqual(metrics["checks_warning"], 0)
        self.assertEqual(metrics["checks_ignored"], 1)
        rules = [dict(name="DNSSEC"), dict(name="DNSSEC", codes=["dnssec_bogus"], ignore=False)]
        self.assertEqual(self.assess(data, rules)[0], 2)

    def test_ignored_expectations_and_other_required_expectations(self):
        data = self.data()
        data["checks"][1].update(code="unsigned", result="none", level="hinweis")
        expectation = dict(name="DKIM", codes=["signature_valid"])
        for rule in (dict(name="DKIM"), dict(name="DKIM", codes=["unsigned"])):
            status, metrics = self.assess(data, [rule], expect=[expectation])
            self.assertEqual(status, 0)
            self.assertEqual(metrics["expectations_failed"], 0)
        data["checks"].append(dict(name="DKIM", code="signature_invalid", result="fail", level="problem"))
        data["status"] = "auffaellig"
        self.assertEqual(self.assess(data, [dict(name="DKIM", codes=["unsigned"])], expect=[expectation])[0], 2)
        rules = [dict(name="DKIM"), dict(name="DKIM", codes=["signature_invalid"], ignore=False)]
        self.assertEqual(self.assess(data, rules, expect=[expectation])[1]["expectations_failed"], 1)
        with self.assertRaises(PLUGIN.Failure):
            self.assess(data, [dict(name="DKIM")], expect=[dict(name="Missing", codes=["pass"])])
        self.assertEqual(self.assess(self.data(), [dict(name="Missing")],
                                     expect=[dict(name="Missing", codes=["pass"])])[0], 0)

    def test_ignore_cannot_hide_stale_missing_or_invalid_report(self):
        for change in ({"status": "unvollstaendig"}, {"schema_version": 2}, {"created_at": "bad"}):
            with self.assertRaises(PLUGIN.Failure):
                self.assess(dict(self.data(), **change), [dict(name="SPF")])
        data = self.data()
        data["checks"] = [c for c in data["checks"] if c["name"] != "SPF"]
        with self.assertRaises(PLUGIN.Failure):
            self.assess(data, [dict(name="SPF")])
        data = self.data()
        data["checks"][0]["code"] = "future_code"
        with self.assertRaises(PLUGIN.Failure):
            self.assess(data, [dict(name="SPF")])

    def test_rule_configuration_is_strict(self):
        cfg = dict(origin=BASE, report_url=BASE + "/r/" + TOKEN)
        for rules in (True, {}, ["DNSSEC"], [{}], [dict(name="DNSSEC", ignore="false")],
                      [dict(name="DNSSEC", codes=[])], [dict(name="DNSSEC", codes=["bad|code"])],
                      [dict(name="DNSSEC", typo=True)], [dict(name="DNSSEC")] * 513):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.configuration(dict(cfg, ignore_checks=rules), "report")
        PLUGIN.configuration(dict(cfg, ignore_checks=[dict(name="DNSSEC", ignore=False)]), "report")


class AccessTest(unittest.TestCase):
    def test_only_valid_current_delivery_reference_and_code_are_exposed(self):
        captured = []
        response = f"Diagnostic complete. Unlock code: {CODE} Results: {BASE}/r/{TOKEN}".encode()
        self.assertEqual(PLUGIN.delivery_reference(response, BASE, lambda *ref: captured.append(ref)), TOKEN)
        self.assertEqual(captured, [(BASE + "/r/" + TOKEN, CODE)])
        for suffix in (b"|perf=1", b"<script>", b"\x00"):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.delivery_reference(response.replace(CODE.encode(), CODE.encode() + suffix), BASE)
        with self.assertRaises(PLUGIN.Failure):
            PLUGIN.delivery_reference(response + f" Unlock code: {CODE}".encode(), BASE)
        captured.clear()
        with self.assertRaises(PLUGIN.Failure):
            PLUGIN.delivery_reference(response.replace(BASE.encode(), b"https://outside.invalid"), BASE,
                                      lambda *ref: captured.append(ref))
        self.assertEqual(captured, [])

    def test_direct_smtp_extracts_access_from_final_data_response(self):
        cfg = dict(origin=BASE, smtp_host="127.0.0.1", smtp_port=25, smtp_tls="loopback_plain",
                   sender="monitor@example.test", recipient="check@example.test", helo="monitor.example.test")
        with mock.patch.object(PLUGIN, "BoundedSMTP") as smtp:
            peer = smtp.return_value
            peer.ehlo.return_value = peer.mail.return_value = peer.rcpt.return_value = (250, b"ok")
            peer.data.return_value = (250, f"Unlock code: {CODE} Results: {BASE}/r/{TOKEN}".encode())
            captured = []
            PLUGIN.smtp_probe(cfg, None, 2, access=lambda *ref: captured.append(ref))
            self.assertEqual(captured, [(BASE + "/r/" + TOKEN, CODE)])

    def test_access_is_before_perfdata_for_all_statuses_and_http_errors(self):
        for http_status, body, expected in ((200, None, 0), (503, b"private", 2), (200, b"{}", 3)):
            with http_peer(http_status, body) as (base, _requests):
                cfg = dict(origin=base, allow_loopback_http=True, report_url=base + "/r/" + TOKEN, report_code=CODE)
                result = cli(cfg, "--mode", "report")
                self.assertEqual(result.returncode, expected, result.stdout)
                self.assertIn(f"; report={base}/r/{TOKEN}; unlock_code={CODE}", result.stdout.split(" | ")[0])
                self.assertNotIn("private", result.stdout)
                for threshold, status in (("--warning", 1), ("--critical", 2)):
                    if expected == 0:
                        result = cli(cfg, "--mode", "report", threshold, "95:")
                        self.assertEqual(result.returncode, status)
                        self.assertIn(f"unlock_code={CODE} | ", result.stdout)

    def test_parent_deadline_keeps_reference_when_child_is_blocked(self):
        def blocked(*_args):
            signal.signal(signal.SIGALRM, signal.SIG_IGN)
            time.sleep(5)

        cfg = dict(origin=BASE, report_url=BASE + "/r/" + TOKEN, report_code=CODE)
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / "config.json"
            path.write_text(json.dumps(cfg))
            path.chmod(0o600)
            with mock.patch.object(PLUGIN, "fetch_report", side_effect=blocked), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(PLUGIN.main(["--config", str(path), "--mode", "report", "--timeout", "0.1"]), 2)
            self.assertIn(f"; report={BASE}/r/{TOKEN}; unlock_code={CODE}", out.getvalue())

    def test_missing_or_invalid_access_never_reuses_previous_values(self):
        with http_peer() as (base, _requests):
            cfg = dict(origin=base, allow_loopback_http=True, report_url=base + "/r/" + TOKEN)
            result = cli(cfg, "--mode", "report")
            self.assertIn("unlock_code=unavailable", result.stdout)
            for code in ("bad\ncode", "C" * 23, 123):
                result = cli(dict(cfg, report_code=code), "--mode", "report")
                self.assertEqual(result.returncode, 3)
                self.assertIn("report=unavailable; unlock_code=unavailable", result.stdout)
                self.assertNotIn(TOKEN, result.stdout)


if __name__ == "__main__":
    unittest.main()
