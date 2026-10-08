#!/usr/bin/env python3
"""Fresh direct SMTP or local Postfix probe and public JSON report check on Linux.

JSON evaluator and direct probe adapted from incoming-email-validator-go,
deploy/check-mail-report.py (4802a8f). Requires Python 3.11 or newer.
"""

import argparse
import contextlib
import datetime as dt
import email.message
import email.policy
import email.utils
import ipaddress
import json
import math
import os
import re
import secrets
import signal
import smtplib
import ssl
import stat
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_BODY = 1 << 20
MAX_CONFIG = 16 << 10
TOKEN = r"[A-Za-z0-9_-]{32}"
STATUSES = ("OK", "WARNING", "CRITICAL", "UNKNOWN")
REPORT_STATES = {"ohne_festgestellte_probleme", "auffaellig", "unvollstaendig"}
LEVELS = {"ok", "hinweis", "problem", "unbekannt", "nicht_anwendbar"}
RESULTS = {"pass", "fail", "none", "neutral", "softfail", "permerror", "temperror", "unknown", "testing"}
CORE_CODES = {
    "SPF": {**{"spf_" + result: result for result in ("pass", "fail", "none", "neutral", "softfail", "permerror")},
            "invalid_envelope": "permerror"},
    "DKIM": {"unsigned": "none", "signature_valid": "pass", "invalid_headers": "permerror",
             **{code: "fail" for code in ("signature_invalid", "weak_algorithm", "unsupported_algorithm", "partial_body",
                 "body_hash_mismatch", "key_missing", "key_revoked", "key_too_short", "key_ambiguous", "invalid_key",
                 "missing_signature_tags", "malformed_signature", "expired_signature", "invalid_time_interval")}},
    "DMARC": {"aligned": "pass", "unaligned": "fail", "no_policy": "none", "invalid_author": "permerror"},
}


class Failure(Exception):
    """Only fixed, public messages may cross the CLI boundary."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def unknown(message):
    raise Failure(3, message)


def finite(value, minimum, maximum):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def parse_json(data):
    # Bound nesting before json.loads, including ignored future fields.
    depth, quoted, escaped = 0, False, False
    for byte in data:
        if quoted:
            if escaped:
                escaped = False
            elif byte == 92:
                escaped = True
            elif byte == 34:
                quoted = False
        elif byte == 34:
            quoted = True
        elif byte in (91, 123):
            depth += 1
            if depth > 16:
                unknown("JSON nesting limit exceeded")
        elif byte in (93, 125):
            depth -= 1

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                unknown("duplicate JSON field")
            result[key] = value
        return result

    try:
        result = json.loads(data, object_pairs_hook=pairs, parse_constant=lambda _: unknown("invalid JSON number"))
    except (ValueError, UnicodeError, RecursionError):
        unknown("invalid JSON")
    stack, count = [result], 0
    while stack:
        value = stack.pop()
        count += 1
        if count > 16384:
            unknown("JSON field limit exceeded")
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    if not isinstance(result, dict):
        unknown("JSON object required")
    return result


def protected_config(path):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid not in (0, os.geteuid()):
            unknown("configuration must be an owned private regular file")
        data = stream.read(MAX_CONFIG + 1)
    if len(data) > MAX_CONFIG:
        unknown("configuration size limit exceeded")
    return parse_json(data)


class Range:
    def __init__(self, text):
        self.text = text or ""
        self.inside = self.text.startswith("@")
        raw = self.text.removeprefix("@")
        try:
            if ":" in raw:
                start, end = raw.split(":")
                self.low = -math.inf if start == "~" else float(start or "0")
                self.high = float(end) if end else math.inf
            else:
                self.low, self.high = 0, float(raw)
            if (self.low > self.high or math.isnan(self.low) or math.isnan(self.high)
                    or re.fullmatch(r"@?(?:~|[+-]?(?:\d+(?:\.\d*)?|\.\d+))?(?::[+-]?(?:\d+(?:\.\d*)?|\.\d+)?)?", self.text) is None
                    or self.text in ("", "@", "~", "@~")):
                raise ValueError
        except ValueError:
            unknown("invalid score range")

    def alerts(self, value):
        contained = self.low <= value <= self.high
        return contained if self.inside else not contained


def loopback(host):
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def origin(value, local):
    if not isinstance(value, str) or len(value) > 512 or any(ord(c) <= 32 or ord(c) >= 127 for c in value):
        unknown("invalid configured origin")
    try:
        parts = urllib.parse.urlsplit(value)
        _ = parts.port
    except ValueError:
        unknown("invalid configured origin")
    if (not parts.hostname or parts.username is not None or parts.password is not None
            or parts.path not in ("", "/") or parts.query or parts.fragment
            or parts.scheme not in ("http", "https") or "\\" in value):
        unknown("invalid configured origin")
    if parts.scheme == "http" and not (local is True and loopback(parts.hostname)):
        unknown("HTTPS required outside explicit loopback profile")
    return value.rstrip("/")


def configuration(cfg, mode):
    allowed = {"origin", "allow_loopback_http", "ca_file", "report_url", "smtp_host", "smtp_port",
               "smtp_tls", "smtp_user", "smtp_password", "sender", "recipient", "helo", "expect", "assess_all"}
    if set(cfg) - allowed:
        unknown("unknown configuration field")
    if "allow_loopback_http" in cfg and type(cfg["allow_loopback_http"]) is not bool:
        unknown("invalid loopback HTTP profile")
    if "assess_all" in cfg and type(cfg["assess_all"]) is not bool:
        unknown("invalid full report assessment profile")
    cfg["origin"] = origin(cfg.get("origin"), cfg.get("allow_loopback_http", False))
    if "ca_file" in cfg and (not isinstance(cfg["ca_file"], str) or not os.path.isabs(cfg["ca_file"])):
        unknown("invalid CA file configuration")
    expected = cfg.get("expect", [])
    if not isinstance(expected, list) or len(expected) > 64:
        unknown("invalid check expectations")
    for item in expected:
        if (not isinstance(item, dict) or set(item) - {"name", "codes", "result", "level", "severity", "match"}
                or not isinstance(item.get("name"), str) or not 1 <= len(item["name"]) <= 80
                or not isinstance(item.get("codes"), list) or not 1 <= len(item["codes"]) <= 32
                or any(not isinstance(code, str) or re.fullmatch(r"[a-z0-9_]{1,80}", code) is None for code in item["codes"])
                or item.get("severity", "critical") not in ("critical", "warning")
                or item.get("match", "all") not in ("all", "any")
                or ("result" in item and (not isinstance(item["result"], str) or
                                         re.fullmatch(r"[a-z0-9_]{1,80}", item["result"]) is None))
                or ("level" in item and item["level"] not in LEVELS)):
            unknown("invalid check expectation")
    if mode == "report":
        report_token(cfg.get("report_url"), cfg["origin"])
        return cfg
    host = cfg.get("smtp_host")
    if not isinstance(host, str) or re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", host) is None:
        unknown("invalid SMTP host")
    if type(cfg.get("smtp_port")) is not int or not 1 <= cfg["smtp_port"] <= 65535:
        unknown("invalid SMTP port")
    tls = cfg.get("smtp_tls")
    if tls not in ("starttls", "implicit", "loopback_plain") or (tls == "loopback_plain" and not loopback(host)):
        unknown("invalid SMTP TLS profile")
    for key in ("sender", "recipient"):
        address = cfg.get(key)
        if not isinstance(address, str) or re.fullmatch(r"[A-Za-z0-9._+-]{1,64}@[A-Za-z0-9.-]{1,253}", address) is None:
            unknown("invalid probe mailbox")
    if cfg["recipient"].split("@", 1)[0] != "check":
        unknown("probe requires the check recipient")
    if not isinstance(cfg.get("helo"), str) or re.fullmatch(r"[A-Za-z0-9.-]{1,253}", cfg["helo"]) is None:
        unknown("invalid probe HELO")
    if ("smtp_user" in cfg) != ("smtp_password" in cfg):
        unknown("incomplete SMTP credentials")
    if "smtp_user" in cfg:
        if tls == "loopback_plain" or any(not isinstance(cfg[key], str) or not 1 <= len(cfg[key]) <= 1024
                                         for key in ("smtp_user", "smtp_password")):
            unknown("invalid SMTP authentication profile")
    if mode == "postfix" and (not loopback(host) or tls != "loopback_plain" or "smtp_user" in cfg):
        unknown("Postfix mode requires unauthenticated numeric loopback SMTP")
    return cfg


def report_token(url, base):
    if not isinstance(url, str):
        unknown("missing report reference")
    match = re.fullmatch(re.escape(base) + r"/r/(" + TOKEN + r")", url)
    if match is None:
        unknown("report reference outside configured origin or path")
    return match[1]


@contextlib.contextmanager
def deadline(seconds):
    def expired(_signum, _frame):
        raise Failure(2, "probe deadline or cancellation")

    handlers = {sig: signal.signal(sig, expired) for sig in (signal.SIGALRM, signal.SIGTERM, signal.SIGINT)}
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


class BoundedReply:
    """Limit an entire SMTP reply, including all continuation lines."""

    def __init__(self, stream):
        self.stream, self.remaining = stream, 16384

    def readline(self, maximum):
        raw = self.stream.readline(min(maximum, self.remaining + 1))
        self.remaining -= len(raw)
        if self.remaining < 0:
            unknown("SMTP response size limit exceeded")
        return raw

    def close(self):
        self.stream.close()


class BoundedSMTP(smtplib.SMTP):
    def getreply(self):
        if self.file is None:
            self.file = BoundedReply(self.sock.makefile("rb"))
        self.file.remaining = 16384
        return super().getreply()


class BoundedSMTPSSL(smtplib.SMTP_SSL, BoundedSMTP):
    pass


def smtp_probe(cfg, context, timeout, queued=False):
    nonce = secrets.token_hex(16)
    message = email.message.EmailMessage(policy=email.policy.SMTP)
    message["From"], message["To"] = cfg["sender"], cfg["recipient"]
    message["Date"] = email.utils.format_datetime(dt.datetime.now(dt.timezone.utc))
    message["Message-ID"] = f"<{nonce}@{cfg['helo']}>"
    message["Subject"] = "Validator monitoring probe"
    message["Auto-Submitted"] = "auto-generated"
    message.set_content(f"Validator monitoring probe: {nonce}\n")
    smtp = None
    try:
        smtp = (BoundedSMTPSSL(cfg["smtp_host"], cfg["smtp_port"], context=context, timeout=timeout)
                if cfg["smtp_tls"] == "implicit" else BoundedSMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=timeout))
        if smtp.ehlo(cfg["helo"])[0] != 250:
            raise Failure(2, "SMTP greeting failed")
        if cfg["smtp_tls"] == "starttls":
            smtp.starttls(context=context)
            if smtp.ehlo(cfg["helo"])[0] != 250:
                raise Failure(2, "SMTP greeting failed")
        if "smtp_user" in cfg:
            smtp.login(cfg["smtp_user"], cfg["smtp_password"])
        if smtp.mail(cfg["sender"])[0] != 250 or smtp.rcpt(cfg["recipient"])[0] not in (250, 251):
            raise Failure(2, "SMTP envelope rejected")
        code, response = smtp.data(message.as_bytes())
        if code != 250:
            raise Failure(2, "SMTP DATA not accepted")
        if queued:
            queue_ids = re.findall(rb"\bqueued as ([A-Za-z0-9]{5,32})\b", response)
            if len(queue_ids) != 1:
                raise Failure(2, "Postfix queue reference missing or ambiguous")
            return queue_ids[0].decode("ascii")
        urls = re.findall(rb"https?://[^\s]+", response)
        if len(urls) != 1:
            raise Failure(2, "SMTP DATA report link missing or ambiguous")
        try:
            return report_token(urls[0].decode("ascii"), cfg["origin"])
        except UnicodeError:
            unknown("invalid SMTP report reference")
    except OSError:
        raise Failure(2, "SMTP transport unavailable") from None
    finally:
        # Close directly: a slow QUIT must not consume the remaining GET budget.
        if smtp is not None:
            smtp.close()


class PostfixLog:
    """Read only new log bytes; expose no unrelated mail or peer text."""

    def __init__(self, path="/var/log/mail.log"):
        self.path = path
        self.stream = self.open()
        self.stream.seek(0, os.SEEK_END)
        self.pending = b""
        self.total = 0

    def open(self):
        fd = os.open(self.path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            os.close(fd)
            unknown("Postfix log must be a regular file")
        return os.fdopen(fd, "rb")

    def close(self):
        self.stream.close()

    def lines(self):
        data = self.stream.read(65536)
        if not data:
            current = os.stat(self.path, follow_symlinks=False)
            opened = os.fstat(self.stream.fileno())
            if (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
                replacement = self.open()
                self.stream.close()
                self.stream = replacement
                self.pending = b""
            elif opened.st_size < self.stream.tell():
                self.stream.seek(0)
                self.pending = b""
            return []
        self.total += len(data)
        if self.total > MAX_BODY:
            unknown("Postfix log read limit exceeded")
        parts = (self.pending + data).split(b"\n")
        self.pending = parts.pop()
        if len(self.pending) > 16384 or any(len(line) > 16384 for line in parts):
            unknown("Postfix log line limit exceeded")
        return parts

    def report(self, queue_id, base):
        marker = re.compile(rb"\bpostfix/smtp\[\d+\]: " + queue_id.encode("ascii") + rb": ")
        while True:
            for line in self.lines():
                if not marker.search(line):
                    continue
                if re.search(rb"\bstatus=(?:deferred|bounced)\b", line):
                    raise Failure(2, "Postfix delivery failed or deferred")
                if not re.search(rb"\bstatus=sent \(250\b", line):
                    continue
                urls = re.findall(rb"https?://[^\s()]+", line)
                if len(urls) != 1:
                    raise Failure(2, "Postfix delivery report link missing or ambiguous")
                try:
                    return report_token(urls[0].decode("ascii"), base)
                except UnicodeError:
                    unknown("invalid Postfix report reference")
            time.sleep(0.1)


def postfix_probe(cfg, context, timeout):
    with contextlib.closing(PostfixLog()) as log:
        queue_id = smtp_probe(cfg, context, timeout, queued=True)
        return log.report(queue_id, cfg["origin"])


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, _request, _fp, _code, _msg, _headers, _url):
        unknown("HTTP redirects are unsupported")


def fetch_report(cfg, token, context, timeout):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=context))
    request = urllib.request.Request(cfg["origin"] + "/api/v1/reports/" + token,
                                     headers={"Accept": "application/json", "Accept-Encoding": "identity"})
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise Failure(2, "HTTP report unavailable")
            if (response.headers.get_content_type() != "application/json"
                    or response.headers.get("Content-Encoding", "identity") != "identity"):
                unknown("unsupported HTTP report representation")
            raw = response.read(MAX_BODY + 1)
            if len(raw) > MAX_BODY:
                unknown("HTTP report size limit exceeded")
    except urllib.error.HTTPError as exc:
        exc.close()
        if exc.code in (404, 410):
            unknown("report reference unavailable or expired")
        raise Failure(2, "HTTP report unavailable") from None
    return parse_json(raw), time.monotonic() - started


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40:
        unknown("invalid report timestamp")
    try:
        result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() != dt.timedelta(0):
            raise ValueError
        return result
    except (ValueError, OverflowError):
        unknown("invalid report timestamp")


def evaluate(report, cfg, now, started, maximum_age, warning=None, critical=None):
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        unknown("unsupported report schema")
    if not isinstance(report.get("validator_version"), str) or not 1 <= len(report["validator_version"]) <= 80:
        unknown("missing validator version")
    if report.get("status") not in REPORT_STATES:
        unknown("unsupported report status")
    if report.get("permanent_example", False) is not False:
        unknown("permanent examples are not fresh probes")
    created, expires = timestamp(report.get("created_at")), timestamp(report.get("expires_at"))
    age = (now - created).total_seconds()
    if (age < -5 or age > maximum_age or expires <= now or expires <= created
            or (started is not None and created < started - dt.timedelta(seconds=5))):
        unknown("report is stale, expired or outside this probe")
    checks = report.get("checks")
    if not isinstance(checks, list) or not 1 <= len(checks) <= 512:
        unknown("missing or oversized report checks")
    for check in checks:
        if (not isinstance(check, dict) or any(not isinstance(check.get(key), str) or not 1 <= len(check[key]) <= 80
                                             for key in ("name", "code", "result", "level"))
                or check["level"] not in LEVELS):
            unknown("unsupported check evidence")
    if report["status"] == "unvollstaendig" or not all(any(c["name"] == name for c in checks) for name in ("SPF", "DKIM", "DMARC")):
        unknown("incomplete required core evidence")
    if any(c["name"] in ("SPF", "DKIM", "DMARC", "Nachricht") and c["level"] == "unbekannt" for c in checks):
        unknown("inconsistent core evidence")
    if any(c["name"] in ("SPF", "DKIM", "DMARC") and c["result"] not in RESULTS for c in checks):
        unknown("unsupported core result")
    if report["status"] == "ohne_festgestellte_probleme" and any(c["level"] == "problem" for c in checks):
        unknown("inconsistent report status")
    if report["status"] == "auffaellig" and not any(c["level"] == "problem" for c in checks):
        unknown("inconsistent report status")
    for check in checks:
        if check["name"] in ("SPF", "DKIM", "DMARC"):
            if CORE_CODES[check["name"]].get(check["code"]) != check["result"]:
                unknown("unknown or inconsistent core check code")
            if (check["result"] in ("fail", "permerror") and check["level"] != "problem") or (
                    check["result"] in ("none", "neutral", "softfail") and check["level"] != "hinweis") or (
                    check["result"] == "pass" and check["level"] not in ("ok", "hinweis")):
                unknown("inconsistent core result and severity")
    if any(c["name"] == "DMARC" and c["result"] == "pass" for c in checks) and not any(
            c["name"] in ("SPF", "DKIM") and c["result"] == "pass" for c in checks):
        unknown("inconsistent authentication alignment")
    states = []
    for expectation in cfg.get("expect", []):
        selected = [c for c in checks if c["name"] == expectation["name"]]
        if not selected:
            unknown("required check evidence absent")
        matches = [c["code"] in expectation["codes"] and
                   all(c[key] == expectation[key] for key in ("result", "level") if key in expectation) for c in selected]
        satisfied = any(matches) if expectation.get("match", "all") == "any" else all(matches)
        if not satisfied and any(c["level"] == "unbekannt" for c in selected):
            unknown("required check expectation is inconclusive")
        states.append(0 if satisfied else 2 if expectation.get("severity", "critical") == "critical" else 1)
    metrics = {"report_age": max(age, 0), "checks_ok": states.count(0), "checks_failed": len(states) - states.count(0)}
    if warning or critical or cfg.get("assess_all", False):
        rating = report.get("rating")
        if (not isinstance(rating, dict) or type(rating.get("version")) is not int or rating["version"] != 1
                or rating.get("state") != "complete" or rating.get("scope") != "message_and_last_hop"
                or type(rating.get("score")) is not int or not 0 <= rating["score"] <= 100
                or rating.get("grade") not in ("S", "A", "B", "C", "D", "E", "F") or rating.get("missing") != []):
            unknown("unsupported or incomplete rating")
        score = rating["score"]
        upper_grade = "S" if score >= 95 else next(g for g, lower in zip("ABCDEF", (85, 75, 65, 50, 35, 0), strict=True) if score >= lower)
        if "SABCDEF".index(rating["grade"]) < "SABCDEF".index(upper_grade):
            unknown("inconsistent rating grade")
        metrics["score"] = score
        if cfg.get("assess_all", False):
            metrics["grade"] = rating["grade"]
        states.append(2 if critical and critical.alerts(score) else 1 if warning and warning.alerts(score) else 0)
    if cfg.get("assess_all", False):
        if not all(any(c["name"] == name for c in checks) for name in
                   ("TLS", "Metadaten", "HELO", "Reverse DNS", "Absenderbezug")):
            unknown("incomplete full report evidence")
        metrics["expectations_ok"] = metrics.pop("checks_ok")
        metrics["expectations_failed"] = metrics.pop("checks_failed")
        metrics["checks_total"] = len(checks)
        for label, level in (("ok", "ok"), ("failed", "problem"), ("warning", "hinweis"),
                             ("unknown", "unbekannt"), ("na", "nicht_anwendbar")):
            metrics["checks_" + label] = sum(c["level"] == level for c in checks)
        states.append(2 if metrics["checks_failed"] else 3 if metrics["checks_unknown"] else
                      1 if metrics["checks_warning"] else 0)
        # Known failures remain actionable even if another optional check is unknown.
        status = next((code for code in (2, 3, 1) if code in states), 0)
    else:
        status = max(states, default=0)
    return status, metrics


def output(status, metrics, warning=None, critical=None):
    data = []
    for name, value in metrics.items():
        if name == "grade":
            continue
        unit = "s" if name in ("http_time", "report_age") else ""
        warn, crit = (warning.text if warning else "", critical.text if critical else "") if name == "score" else ("", "")
        upper = "100" if name == "score" else ""
        data.append(f"{name}={value:.3f}{unit};{warn};{crit};0;{upper}")
    messages = ("fresh report meets expectations", "mail expectation warning", "mail expectation failed", "report cannot be assessed")
    message = messages[status]
    if "checks_total" in metrics:
        message = ("full report meets expectations", "report has advisory findings", "report has failed findings or expectations",
                   "report has inconclusive findings")[status]
        message += (f"; checks={metrics['checks_total']} problems={metrics['checks_failed']}"
                    f" warnings={metrics['checks_warning']} unknown={metrics['checks_unknown']}"
                    f"; rating={metrics['grade']} score={metrics['score']}/100")
    return f"{STATUSES[status]} - {message} | {' '.join(data)}"


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        unknown("invalid command line; use --help")


def check(args, warning, critical, get_started):
    try:
        with deadline(args.timeout):
            cfg = configuration(protected_config(args.config), args.mode)
            context = ssl.create_default_context(cafile=cfg.get("ca_file"))
            started = dt.datetime.now(dt.timezone.utc) if args.mode != "report" else None
            if args.mode == "postfix":
                token = postfix_probe(cfg, context, args.timeout)
            elif started:
                token = smtp_probe(cfg, context, args.timeout)
            else:
                token = report_token(cfg["report_url"], cfg["origin"])
            signal.setitimer(signal.ITIMER_REAL, min(10, signal.getitimer(signal.ITIMER_REAL)[0]))
            get_started()
            report, elapsed = fetch_report(cfg, token, context, args.timeout)
            status, metrics = evaluate(report, cfg, dt.datetime.now(dt.timezone.utc), started, args.max_age, warning, critical)
            metrics["http_time"] = elapsed
            return status, output(status, metrics, warning, critical)
    except Failure as exc:
        return exc.status, f"{STATUSES[exc.status]} - {exc}"
    except (ssl.SSLError, smtplib.SMTPException, urllib.error.URLError, TimeoutError, ConnectionError):
        return 2, "CRITICAL - SMTP or HTTP transport unavailable"
    except OSError:
        return 3, "UNKNOWN - local configuration or runtime unavailable"
    except Exception:
        return 3, "UNKNOWN - report check failed"


def supervised_check(args, warning, critical):
    # SIGALRM alone cannot reliably interrupt every libc resolver call. Only
    # the tracked child reads configuration or performs network operations.
    reader, writer = os.pipe()
    child = None
    try:
        with deadline(args.timeout):
            child = os.fork()
            if child == 0:
                os.close(reader)
                try:
                    status, line = check(args, warning, critical, lambda: os.write(writer, b"G"))
                    os.write(writer, f"{status}\n{line}".encode("ascii"))
                finally:
                    os._exit(0)
            os.close(writer)
            writer = None
            result = bytearray()
            while raw := os.read(reader, 1025 - len(result)):
                if not result and raw.startswith(b"G"):
                    signal.setitimer(signal.ITIMER_REAL, min(10, signal.getitimer(signal.ITIMER_REAL)[0]))
                    raw = raw[1:]
                result.extend(raw)
                if len(result) > 1024:
                    unknown("invalid check subprocess result")
            _, wait_status = os.waitpid(child, 0)
            child = None
            if wait_status != 0 or not result:
                unknown("check subprocess unavailable")
            code, line = result.decode("ascii").split("\n", 1)
            if code not in ("0", "1", "2", "3") or "\n" in line or not line.startswith(STATUSES[int(code)] + " - "):
                unknown("invalid check subprocess result")
            return int(code), line
    finally:
        os.close(reader)
        if writer is not None:
            os.close(writer)
        if child is not None:
            with contextlib.suppress(ProcessLookupError):
                os.kill(child, signal.SIGKILL)
            os.waitpid(child, 0)


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("--mode", choices=("probe", "postfix", "report"), default="probe")
    parser.add_argument("--config", required=True, help="Owned mode-0600 JSON configuration")
    parser.add_argument("--timeout", type=float, default=30, help="Whole run deadline in seconds (0.1–300)")
    parser.add_argument("--max-age", type=float, default=300, help="Maximum report age in seconds (1–86400)")
    parser.add_argument("--warning", help="Optional score warning range, for example 90:")
    parser.add_argument("--critical", help="Optional score critical range, for example 70:")
    try:
        args = parser.parse_args(argv)
        if not finite(args.timeout, 0.1, 300) or not finite(args.max_age, 1, 86400):
            unknown("invalid deadline or report age")
        warning = Range(args.warning) if args.warning is not None else None
        critical = Range(args.critical) if args.critical is not None else None
        status, line = supervised_check(args, warning, critical)
        print(line)
        return status
    except Failure as exc:
        print(f"{STATUSES[exc.status]} - {exc}")
        return exc.status
    except (ssl.SSLError, smtplib.SMTPException, urllib.error.URLError, TimeoutError, ConnectionError):
        print("CRITICAL - SMTP or HTTP transport unavailable")
        return 2
    except OSError:
        print("UNKNOWN - local configuration or runtime unavailable")
        return 3
    except SystemExit:
        return 0
    except Exception:
        # No peer text, URL, credential, private value or traceback reaches Nagios.
        print("UNKNOWN - report check failed")
        return 3


if __name__ == "__main__":
    sys.exit(main())
