"""One logging setup for the whole app: one handler on stdout, one line per record."""
import logging
import sys


class OneLineFormatter(logging.Formatter):
    def format(self, record):
        text = super().format(record)
        return text.replace("\r\n", " | ").replace("\n", " | ")


def configure_logging(level: str = "INFO") -> None:
    """Safe to call more than once: it always leaves exactly one handler on the root logger."""
    lvl = getattr(logging, str(level or "INFO").upper(), None)
    if not isinstance(lvl, int):
        lvl = logging.INFO
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(OneLineFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(lvl)
    # uvicorn's own handlers would print every line a second time; let them flow through the root handler.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True