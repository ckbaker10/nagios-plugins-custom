"""Full-report severity, rating and finding counts."""
import copy
import unittest

from test_check_mail_report import NOW, PLUGIN, report


def full_report():
    data = report()
    for name, code in (("TLS", "encrypted"), ("HELO", "helo_forward_match"),
                       ("Reverse DNS", "forward_confirmed"), ("Absenderbezug", "sender_match")):
        data["checks"].append(dict(name=name, code=code, result="pass", level="ok"))
    return data


class FullReportTest(unittest.TestCase):
    def assess(self, data=None, **kwargs):
        return PLUGIN.evaluate(data or full_report(), {"assess_all": True}, NOW, NOW, 300, **kwargs)

    def test_full_report_counts_all_findings_separately_from_expectations(self):
        data = full_report()
        # Use a signed good message for a baseline without advisory findings.
        data["checks"][1].update(code="signature_valid", result="pass", level="ok")
        data["checks"].append(dict(name="MTA-STS", code="mtasts_missing", result="missing", level="nicht_anwendbar"))
        status, metrics = self.assess(data)
        self.assertEqual(status, 0)
        self.assertEqual(metrics["checks_total"], 9)
        self.assertEqual(metrics["checks_ok"], 8)
        self.assertEqual(metrics["checks_na"], 1)
        self.assertEqual(metrics["expectations_ok"], 0)
        line = PLUGIN.output(status, metrics)
        self.assertIn("rating=A score=90/100", line)
        self.assertIn("score=90.000", line)
        self.assertNotIn("grade=", line)
        self.assertLess(len(line), 1024)

    def test_every_optional_level_affects_status_even_with_good_rating(self):
        for level, status in (("problem", 2), ("unbekannt", 3), ("hinweis", 1), ("ok", 0), ("nicht_anwendbar", 0)):
            data = full_report()
            data["checks"][1].update(code="signature_valid", result="pass", level="ok")
            data["checks"].append(dict(name="DNSSEC", code="dnssec_insecure", result="insecure", level=level))
            if level == "problem":
                data["status"] = "auffaellig"
            self.assertEqual(self.assess(data)[0], status)
            # Original selected-expectation mode remains compatible.
            self.assertEqual(PLUGIN.evaluate(data, {}, NOW, NOW, 300)[0], 0)

    def test_known_problem_takes_priority_over_optional_unknown(self):
        data = full_report()
        data["status"] = "auffaellig"
        for level in ("problem", "unbekannt"):
            data["checks"].append(dict(name="Future check", code="fixed_code", result="observed", level=level))
        self.assertEqual(self.assess(data)[0], 2)

    def test_complete_rating_and_all_rating_core_findings_are_required(self):
        data = full_report()
        for key in ("rating",):
            modified = copy.deepcopy(data)
            del modified[key]
            with self.assertRaises(PLUGIN.Failure):
                self.assess(modified)
        for name in ("TLS", "Metadaten", "HELO", "Reverse DNS", "Absenderbezug"):
            modified = copy.deepcopy(data)
            modified["checks"] = [c for c in modified["checks"] if c["name"] != name]
            with self.assertRaises(PLUGIN.Failure):
                self.assess(modified)
        data["rating"]["state"] = "incomplete"
        with self.assertRaises(PLUGIN.Failure):
            self.assess(data)

    def test_profile_is_boolean_and_score_thresholds_remain_optional(self):
        for value in (1, "true", None, []):
            with self.assertRaises(PLUGIN.Failure):
                PLUGIN.configuration({"origin": "https://validator.example.test", "assess_all": value}, "probe")
        self.assertEqual(self.assess(critical=PLUGIN.Range("91:"))[0], 2)


if __name__ == "__main__":
    unittest.main()
