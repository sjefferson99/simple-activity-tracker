# utimezone
# Licence: MIT
# Repo: samcorky/utimezone
_CACHE = {}
_MAX_CACHE_SIZE = 10


def _zones_csv_path():
    path = __file__
    for sep in ("/", "\\"):
        if sep in path:
            return path.rsplit(sep, 1)[0] + sep + "zones.csv"
    return "zones.csv"


def _evict_if_needed():
    """Clear cache when capacity is reached."""
    if len(_CACHE) >= _MAX_CACHE_SIZE:
        _CACHE.clear()


def _parse_zone_line(line):
    """Parse a CSV-ish line into (iana_name, posix_rule)."""
    line = line.strip()
    if not line:
        return None

    parts = line.split('","', 1)
    if len(parts) < 2:
        return None

    name = parts[0].strip('"')
    posix_rule = parts[1].strip('"')
    return name, posix_rule


def _read_zones(db_path):
    """Yield (iana_name, posix_rule) tuples from the zones file."""
    with open(db_path, encoding="utf-8") as f:
        for raw in f:
            parsed = _parse_zone_line(raw)
            if parsed:
                yield parsed


def get_posix_rule_for_iana_name(iana_timezone_name):
    """Return the POSIX rule for an IANA timezone name, or None."""
    # fast path
    if iana_timezone_name in _CACHE:
        return _CACHE[iana_timezone_name]

    db_path = _zones_csv_path()

    # noinspection PyBroadException
    try:
        for name, posix_rule in _read_zones(db_path):
            if name == iana_timezone_name:
                _evict_if_needed()
                _CACHE[iana_timezone_name] = posix_rule
                return posix_rule
    except Exception:
        return None

    return None


def _get_all_iana_names():
    """Return a list of all IANA names known in zones.csv."""
    db_path = _zones_csv_path()
    names = []

    # noinspection PyBroadException
    try:
        for name, _ in _read_zones(db_path):
            names.append(name)
    except Exception:
        return names

    return names
