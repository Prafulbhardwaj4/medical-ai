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
    """Given a naive UTC datetime, return the IST calendar date it falls on."""
    if dt is None:
        return None
    return (dt + IST_OFFSET).date()


def ist_date(dt: datetime):
    """Convert any datetime (naive - assumed UTC, or timezone-aware) to its
    IST calendar date."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return (dt + IST_OFFSET).date()
    return dt.astimezone(IST).date()