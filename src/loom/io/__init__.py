"""I/O primitives for URI parsing, sources, codecs, and registries."""

from loom.io.codecs import (
    Codec,
    CodecDecodeError,
    CodecEncodeError,
    CodecError,
    CodecRegistry,
    BytesCodec,
    JSONCodec,
    TextCodec,
    UnknownCodecError,
    create_default_codec_registry,
    CodecRegistrationError,
)
from loom.io.errors import LoomIOError, UnsupportedURIError
from loom.io.sources import (
    DataSource,
    DataSourceError,
    LocalFileSystemSource,
    SourceNotFoundError,
    SourcePermissionError,
    UnsupportedSourceOperationError,
)
from loom.io.uris import ParsedURI, get_uri_scheme, is_file_uri, normalize_uri, parse_uri, path_to_file_uri, uri_to_path

__all__ = [
    "ParsedURI",
    "parse_uri",
    "get_uri_scheme",
    "is_file_uri",
    "uri_to_path",
    "path_to_file_uri",
    "normalize_uri",
    "LoomIOError",
    "UnsupportedURIError",
    "DataSource",
    "LocalFileSystemSource",
    "DataSourceError",
    "SourceNotFoundError",
    "SourcePermissionError",
    "UnsupportedSourceOperationError",
    "Codec",
    "JSONCodec",
    "TextCodec",
    "BytesCodec",
    "CodecRegistry",
    "create_default_codec_registry",
    "CodecError",
    "CodecRegistrationError",
    "UnknownCodecError",
    "CodecEncodeError",
    "CodecDecodeError",
]
