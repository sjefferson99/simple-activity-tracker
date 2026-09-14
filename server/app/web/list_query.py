"""One place that knows how to turn the activity list's current filter/sort/
page state into a URL (or an htmx `hx-vals` dict) — see issue #76. Before
this existed, `partials/activity_list_controls.html` and
`partials/activity_list_pagination.html` each hand-built
`/?page=…&per_page=…&sort=…&dir=…` themselves; adding five more filter
params to every one of those hand-built strings is exactly the kind of
duplication that drifts. Every param here has a default that is *omitted*
from the built URL/vals, so a plain `/` with nothing set stays a plain `/`
rather than growing a long string of defaults.
"""

from dataclasses import dataclass, replace
from typing import Any
from urllib.parse import urlencode

from app.repositories.activities import ActivityListDirection, ActivityListSort

_DEFAULT_PAGE = 1
_DEFAULT_PER_PAGE = "20"
_DEFAULT_SORT: ActivityListSort = "date"
_DEFAULT_DIR: ActivityListDirection = "desc"


@dataclass(frozen=True)
class ActivityListQuery:
    """The activity list's full URL-addressable state. `per_page` is kept as
    the raw string the route already parses ("20"/"100"/"all") rather than
    the repository's `int | None`, since that's what every template needs to
    round-trip into a query string or a <select> value anyway."""

    page: int = _DEFAULT_PAGE
    per_page: str = _DEFAULT_PER_PAGE
    sort: ActivityListSort = _DEFAULT_SORT
    dir: ActivityListDirection = _DEFAULT_DIR
    q: str = ""
    min_km: str = ""
    max_km: str = ""
    lat: str = ""
    lon: str = ""
    radius_km: str = ""
    geo: str = ""

    def params(self, **overrides: Any) -> dict[str, str]:
        merged = replace(self, **overrides)
        params: dict[str, str] = {}
        if merged.page != _DEFAULT_PAGE:
            params["page"] = str(merged.page)
        if merged.per_page != _DEFAULT_PER_PAGE:
            params["per_page"] = merged.per_page
        if merged.sort != _DEFAULT_SORT:
            params["sort"] = merged.sort
        if merged.dir != _DEFAULT_DIR:
            params["dir"] = merged.dir
        if merged.q:
            params["q"] = merged.q
        if merged.min_km:
            params["min_km"] = merged.min_km
        if merged.max_km:
            params["max_km"] = merged.max_km
        if merged.lat:
            params["lat"] = merged.lat
        if merged.lon:
            params["lon"] = merged.lon
        if merged.radius_km:
            params["radius_km"] = merged.radius_km
        if merged.geo:
            params["geo"] = merged.geo
        return params


def list_url(query: ActivityListQuery, **overrides: Any) -> str:
    """`{{ list_url(list_query, page=p) }}` /
    `{{ list_url(list_query, sort="distance", dir="asc", page=1) }}` — the
    current state with the given fields overridden, rendered as a `/?...`
    URL with only non-default params present. Used by every sort/page link
    and by the per-page `<select>`'s own `hx-get` target."""
    params = query.params(**overrides)
    return f"/?{urlencode(params)}" if params else "/"


def list_vals(query: ActivityListQuery, **overrides: Any) -> dict[str, str]:
    """The same merged param set as list_url(), as a plain dict — for an
    htmx `hx-vals` attribute (via `| tojson`) on a control that submits its
    own value separately (the per-page `<select>`, which already sends
    `per_page` via `hx-include="this"` and only needs the *other* fields
    supplied via hx-vals)."""
    return query.params(**overrides)
