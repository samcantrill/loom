"""Unit tests for I/O error hierarchy."""

from loom.io.errors import LoomIOError, UnsupportedURIError
from loom.io.sources.errors import (
    DataSourceError,
    SourceNotFoundError,
    SourcePermissionError,
    UnsupportedSourceOperationError,
)
from loom.io.codecs.errors import (
    CodecDecodeError,
    CodecEncodeError,
    CodecError,
    CodecRegistrationError,
    UnknownCodecError,
)


def test_io_error_roots() -> None:
    assert issubclass(LoomIOError, Exception)


def test_io_error_exports_match_contract() -> None:
    assert LoomIOError.__name__ == "LoomIOError"
    assert UnsupportedURIError.__name__ == "UnsupportedURIError"


def test_source_errors_inherit_from_lom_io_error() -> None:
    assert issubclass(DataSourceError, LoomIOError)
    assert issubclass(SourceNotFoundError, DataSourceError)
    assert issubclass(SourcePermissionError, DataSourceError)
    assert issubclass(UnsupportedSourceOperationError, DataSourceError)


def test_codec_errors_inherit_from_lom_io_error() -> None:
    assert issubclass(CodecError, LoomIOError)
    assert issubclass(CodecRegistrationError, CodecError)
    assert issubclass(UnknownCodecError, CodecError)
    assert issubclass(CodecEncodeError, CodecError)
    assert issubclass(CodecDecodeError, CodecError)


def test_source_error_messages_include_context() -> None:
    err = SourceNotFoundError("local source missing file: path")
    assert "missing file" in str(err)


def test_codec_error_messages_include_context() -> None:
    err = CodecEncodeError("Codec json.v1 failed for key")
    assert "json.v1" in str(err)
