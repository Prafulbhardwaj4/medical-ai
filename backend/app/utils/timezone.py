from datetime import datetime, timedelta, date, timezone

IST_OFFSET = timedelta(hours=5, minutes=30)
IST = timezone(IST_OFFSET)


def now_ist() -> datetime:
    """Current time, timezone-aware, in IST."""
    return datetime.now(IST)


def now_ist_naive() -> datetime:
    """Current IST wall-clock time as a naive datetime (no tzinfo) —
    used as the default for columns that store IST directly."""
    return datetime.now(IST).replace(tzinfo=None)


def ist_today() -> date:
    """Today's calendar date in IST."""
    return now_ist_naive().date()


def ist_day_bounds(d: date = None):
    """(start, end) naive-IST datetimes spanning the given IST calendar day
    (default: today). end is the exclusive start of the next day."""
    d = d or ist_today()
    start = datetime(d.year, d.month, d.day)
    end = start + timedelta(days=1)
    return start, end


def ist_day_bounds_utc(d: date = None):
    """(start, end) naive-UTC datetimes equivalent to the given IST calendar
    day's 00:00-24:00 - for filtering columns stored as naive UTC
    (e.g. datetime.utcnow() defaults)."""
    start_ist, end_ist = ist_day_bounds(d)
    return start_ist - IST_OFFSET, end_ist - IST_OFFSET


def utc_naive_to_ist_date(dt: datetime):
    """DEPRECATED — kept only so any stray old import doesn't crash. All
    naive datetimes in this app are now IST already; use ist_date() or
    dt.date() directly instead of this."""
    return ist_date(dt)


def ist_date(dt: datetime):
    """Convert a stored datetime to its IST calendar date. Naive datetimes
    are assumed to already be IST wall-clock (this app's storage convention
    as of the IST migration) — no offset is added. Timezone-aware datetimes
    are converted to IST first."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.date()
    return dt.astimezone(IST).date()