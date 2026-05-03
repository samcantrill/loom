"""Codec protocol and default implementations."""

from .base import Codec
from .bytes_codec import BytesCodec
from .errors import CodecError, CodecRegistrationError, CodecDecodeError, CodecEncodeError, UnknownCodecError
from .json_codec import JSONCodec
from .registry import CodecRegistry, create_default_codec_registry
from .text_codec import TextCodec

__all__ = [
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

