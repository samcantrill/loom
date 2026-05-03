"""Unit tests for URI helpers."""

from pathlib import Path
import pytest

from loom.io.errors import UnsupportedURIError
from loom.io.uris import (
    normalize_uri,
    parse_uri,
    get_uri_scheme,
    is_file_uri,
    path_to_file_uri,
    uri_to_path,
)


def test_parse_uri_local_paths() -> None:
    assert parse_uri("data/input.json").scheme is None
    assert parse_uri("data/input.json").path == "data/input.json"
    assert parse_uri("/tmp/example.json").scheme is None
    assert parse_uri("/tmp/example.json").path == "/tmp/example.json"


def test_parse_uri_file_uri() -> None:
    parsed = parse_uri("file:///tmp/example.json")
    assert parsed.scheme == "file"
    assert parsed.path == "/tmp/example.json"
    assert parsed.authority is None


def test_parse_uri_file_uri_localhost() -> None:
    assert parse_uri("file://localhost/tmp/example.json").authority is None


def test_parse_uri_remote_preserves_query_fragment() -> None:
    parsed = parse_uri("https://example.com/data.json?download=1#v1")
    assert parsed.scheme == "https"
    assert parsed.path == "/data.json"
    assert parsed.query == "download=1"
    assert parsed.fragment == "v1"


def test_parse_uri_invalid_empty_or_whitespace() -> None:
    with pytest.raises(UnsupportedURIError):
        parse_uri("")
    with pytest.raises(UnsupportedURIError):
        parse_uri("  ")


def test_get_uri_scheme_and_file_helper() -> None:
    assert get_uri_scheme("/tmp/a") is None
    assert get_uri_scheme("file:///tmp/a") == "file"
    assert get_uri_scheme("https://example.com") == "https"
    assert is_file_uri("file:///tmp/a")
    assert not is_file_uri("/tmp/a")


def test_uri_to_path_accepts_local_file_uri() -> None:
    assert uri_to_path("file:///tmp/example.json") == Path("/tmp/example.json")


def test_uri_to_path_rejects_remote_or_query_or_non_local_authority() -> None:
    with pytest.raises(UnsupportedURIError):
        uri_to_path("https://example.com/data.json")
    with pytest.raises(UnsupportedURIError):
        uri_to_path("file:///tmp/example.json?download=1")
    with pytest.raises(UnsupportedURIError):
        uri_to_path("file://server/share/example.json")


def test_uri_to_path_converts_local_paths_and_relative_without_root() -> None:
    assert uri_to_path("relative/path.json") == Path("relative/path.json")
    assert uri_to_path("/tmp/example.json") == Path("/tmp/example.json")


def test_path_to_file_uri_requires_absolute() -> None:
    with pytest.raises(UnsupportedURIError):
        path_to_file_uri("relative/path.json")
    quoted = path_to_file_uri("/tmp/a b.txt")
    assert quoted == "file:///tmp/a%20b.txt"


def test_normalize_uri_local_and_remote_behavior() -> None:
    assert normalize_uri("/tmp/a b.txt") == "file:///tmp/a%20b.txt"
    assert normalize_uri("relative/path.json") == "relative/path.json"
    assert normalize_uri("relative/path.json", base_dir="/tmp") == "file:///tmp/relative/path.json"
    assert normalize_uri("https://example.com/data.json?download=1#v1") == "https://example.com/data.json?download=1#v1"

