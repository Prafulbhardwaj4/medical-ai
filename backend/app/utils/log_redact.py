"""Keeps secrets out of log lines: token-looking path segments are replaced and query strings are never written."""
import logging
import re

# Path pieces that always carry a secret or a patient-linked token in the segment right after them.
_TOKEN_AFTER = {"resolve", "verify", "token-for", "transcribe", "ws-ticket", "invite", "reset", "setup", "confirm"}
_LOOKS_LIKE_TOKEN = re.compile(r"^(?=.*[0-9])(?=.*[A-Za-z])[A-Za-z0-9_\-\.]{8,}$|^[A-Za-z0-9_\-]{24,}$")
_REDACTED = "[redacted]"


def redact_path(path: str) -> str:
    """Drops any query string, then hides segments that hold a token. Plain numeric ids and route words stay."""
    path = (path or "").split("?", 1)[0].split("#", 1)[0]
    segments = path.split("/")
    out = []
    prev = ""
    for seg in segments:
        if seg and (prev in _TOKEN_AFTER and not seg.isdigit() or _LOOKS_LIKE_TOKEN.match(seg)):
            out.append(_REDACTED)
        else:
            out.append(seg)
        prev = seg
    return "/".join(out)


class AccessLogRedactionFilter(logging.Filter):
    """uvicorn's access line carries the full request target, including the query string
    (the staff websocket ticket travels there). Rewrites it before the line is printed."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = args[:2] + (redact_path(args[2]),) + args[3:]
        return True


def install_access_log_redaction() -> None:
    lg = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, AccessLogRedactionFilter) for f in lg.filters):
        lg.addFilter(AccessLogRedactionFilter())