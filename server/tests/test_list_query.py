"""Unit tests for app/web/list_query.py — the shared URL/hx-vals builder for
the activity list's sort/page/search state (issue #76). Pure, no app/DB
needed."""

from app.web.list_query import ActivityListQuery, list_url, list_vals


def test_default_query_produces_the_bare_root_url() -> None:
    assert list_url(ActivityListQuery()) == "/"


def test_only_non_default_fields_appear_in_the_url() -> None:
    query = ActivityListQuery(page=2)
    assert list_url(query) == "/?page=2"


def test_override_replaces_a_field_without_mutating_the_original() -> None:
    query = ActivityListQuery(sort="distance", dir="asc")
    # page=1 is the default and stays omitted from the URL even though it's
    # passed explicitly — only dir="desc" (a real override, non-default) shows up.
    url = list_url(query, page=1, dir="desc")
    assert url == "/?sort=distance"
    # original query is untouched — overrides never mutate in place.
    assert query.dir == "asc"


def test_q_with_special_characters_is_escaped_in_the_url() -> None:
    query = ActivityListQuery(q="a&b c/d")
    url = list_url(query)
    assert url == "/?q=a%26b+c%2Fd"


def test_q_with_unicode_is_escaped_in_the_url() -> None:
    query = ActivityListQuery(q="café run")
    url = list_url(query)
    assert "q=caf%C3%A9+run" in url


def test_list_vals_returns_the_same_non_default_params_as_a_plain_dict() -> None:
    query = ActivityListQuery(sort="distance", dir="asc", q="hills")
    # page=1 is the default (see the previous test) and stays omitted here too.
    vals = list_vals(query, page=1)
    assert vals == {"sort": "distance", "dir": "asc", "q": "hills"}


def test_list_vals_with_all_defaults_is_empty() -> None:
    assert list_vals(ActivityListQuery()) == {}
