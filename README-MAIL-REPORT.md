# Mail delivery and public JSON reports

`check_mail_report` requires Linux and Python >= 3.11 (the release bundles Python
3.12). The JSON evaluator and direct probe come from `incoming-email-validator-go`
`deploy/check-mail-report.py`, commit `4802a8f`. Only the public report API is read;
no validator database or diagnostics are required. The current validated report
URL and unlock code are shown in Nagios output. Peer text, message contents,
mailboxes and SMTP credentials are excluded.

## Modes

- `probe` (default): direct SMTP DATA returns the fresh report link.
- `report`: validate a preexisting `report_url` in the private config; sends no mail.
- `postfix`: submit a fresh message to numeric loopback SMTP, read its queue ID,
  then wait for that exact `postfix/smtp` delivery in `/var/log/mail.log`. This
  exercises the regular outgoing Postfix, milter/DKIM and SMTP route. The final
  `250` response must contain exactly one report link on the configured origin.

Each sending check creates one synthetic message with a fresh Message-ID and body
nonce, addressed to `check`, without requesting a reply or bounce. Start with a
five-minute interval and one check attempt. Loopback SMTP is deliberately plaintext;
Postfix controls TLS on the actual Internet hop. Remote SMTP in `probe` mode requires
verified STARTTLS or implicit TLS. HTTPS verification is always enabled outside an
explicit numeric loopback test profile. No redirects or environment proxies.

## Protected configuration

Configuration must be a regular nonsymlink JSON file, owned by the executing user
or root and mode 0600. Postfix mode additionally needs read access to the mail log.
The optional Ansible configuration installs a root-owned 0700 directory, 0600
configuration and a sudo rule for one fixed command with fixed arguments. The
plugin, bundle and stable symlink must remain root-owned and unwritable by Nagios.
Nagios receives no general access to mail logs or sudo arguments.
When the Postfix configuration is enabled, the Ansible role installs this
checkout's `check_mail_report.py` over the bundled copy. This keeps mail-check
features current independently of the bundle's Python and other plugins.
For hosts with an existing bundle, `--tags mail_report` updates only this plugin,
its private configuration and the fixed sudo rule.

Set `nagios_plugins_custom_mail_report_postfix` in host variables, for example:

```yaml
nagios_plugins_custom_mail_report_postfix:
  origin: https://validator.example.test
  assess_all: true
  smtp_host: 127.0.0.1
  smtp_port: 25
  smtp_tls: loopback_plain
  sender: monitor@example.test
  recipient: check@validator.example.test
  helo: monitor.example.test
  expect:
    - {name: SPF, codes: [spf_pass], result: pass}
    - {name: DKIM, codes: [signature_valid], result: pass, match: any}
    - {name: DMARC, codes: [aligned], result: pass}
```

```sh
sudo -u nagios sudo -n /opt/nagios-plugins-lukas/check_mail_report --mode postfix --config /etc/nagios/mail-report/postfix.json --timeout 60 --max-age 300
```

Copy `icinga-custom-commands/mail-report.conf` to the master's existing global
command zone, validate and reload Icinga, and import commands through Director
kickstart. Assign `check_mail_report_postfix` to a service with the sending host's
agent as `command_endpoint`, `check_interval=5m`, `retry_interval=5m`,
`max_check_attempts=1`. Keep the existing readiness/statistics checks.

## Assessment and limits

Exit codes: OK=0, WARNING=1, CRITICAL=2, UNKNOWN=3. Without `expect`, an unsigned or
suspicious direct probe can still demonstrate a working validator. Configure
SPF/DKIM/DMARC expectations to assess regular outgoing mail. Failed expectations
are CRITICAL (or WARNING with `severity: warning`); missing/inconclusive evidence,
unknown schema and stale/expired reports are UNKNOWN. A deferred/bounced delivery,
missing delivery report link or transport/deadline failure is CRITICAL. A local
configuration or log access error is UNKNOWN. Score ranges are optional via
`--warning 90:` and `--critical 70:` and require a complete schema-v1 rating.

With `assess_all: true`, every public finding is evaluated, including transport,
DNS, spam, identity, oversigning and message checks. A `problem` finding is
CRITICAL, an `unbekannt` finding UNKNOWN, and a `hinweis` finding WARNING;
`ok` and `nicht_anwendbar` do not alert. Known failures take precedence over
optional unknown findings. A complete supported rating is required and its
grade and score are shown without imposing an additional score threshold.
Perfdata includes all finding counts plus separate configured expectation
counts. Without this opt-in, the original direct-probe behavior is preserved.

### Ignore individual checks

Add `ignore_checks` to the private JSON configuration (or the corresponding
Ansible host variable). Check names and codes match the machine-readable report
exactly. No finding is ignored by default. For example:

```json
"ignore_checks": [
  {"name": "DNSSEC", "codes": ["dnssec_insecure"], "ignore": true},
  {"name": "DKIM", "ignore": false}
]
```

Set `ignore` to `false` or remove a rule to assess that finding again. Omitting
`codes` matches every finding with that name; omitting `ignore` means `true`.
If multiple rules match, the last matching rule wins. A code-specific exception
can therefore reenable one finding within an ignored check group.

Ignored findings do not raise WARNING, CRITICAL or UNKNOWN and are excluded from
configured expectations. Other findings and expectations remain active. Missing
evidence for an expectation ignored by name is also ignored. Schema, freshness,
required core evidence and consistency validation still apply to the entire
report. Score thresholds still use the original rating, which is not recalculated.
With `assess_all`, `checks_total` counts every finding and `checks_ignored` counts
the excluded findings; the severity counters count only active findings.

### Current report access in Nagios

Every status line includes `report=<URL>; unlock_code=<code>` before the `|`
performance data separator. In sending modes these values belong to the current
SMTP DATA or correlated Postfix delivery, never a previous check. Access remains
visible if subsequent HTTP fetching or assessment fails, including GET timeout.

If no current report link was obtained, `report=unavailable` is shown. A missing
code is shown as `unlock_code=unavailable`. In `report` mode an optional
`report_code` in the protected configuration can supply an existing report's code.
URLs and codes are never performance data or command-line arguments. The code
allows access to original diagnostic values and report deletion, so monitoring
viewers receiving these values have that access too.

Only new log bytes after opening the probe are scanned; queue IDs are matched
exactly, incoming `smtpd` and unrelated deliveries are ignored. Rename rotation
and detected truncation are followed. Log reads are limited to 1 MiB and lines
to 16 KiB. Continuous unrelated traffic reaching the cap returns UNKNOWN.
Only file-based Postfix logging is supported, not journal-only installations.
Copytruncate can race with log reads; an absent delivery is bounded by the check
deadline and cannot pass. The whole-run child is supervised and reaped, including
blocked DNS. GET has at most ten seconds. Terminating a check after local queue
acceptance does not remove the message from Postfix; it can still be delivered
later. Its queue ID/report is never reused by the next check.

Public JSON: `GET /api/v1/reports/<token>`, HTTP 200, `application/json`, no content
encoding, schema_version=1. Core checks SPF/DKIM/DMARC must be complete and
internally consistent. Limits: 1 MiB response, depth 16, 16384 nodes, 512 checks,
16 KiB configuration and SMTP response. Reports must be fresh, unexpired and
created within this sending run (five-second clock tolerance).

```sh
python3 -m unittest discover -s tests -p 'test_check_mail_report*.py' -v
```
