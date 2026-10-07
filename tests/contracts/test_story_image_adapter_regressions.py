"""Regression contracts for independent audit findings, plus cleanup boundaries."""
import asyncio
from hashlib import sha256
import io
import json
import struct
import zlib

import httpx
from PIL import Image
import pytest

from mira.adapters.media._openai_http import ImageProviderError
from mira.adapters.media.openai_images import OpenAIImageBackend, OpenAIImageOptions
from mira.adapters.media.openai_vision_review import OpenAIVisionReviewBackend, OpenAIVisionOptions
from mira.adapters.media.png_decoder import PillowPngDecoder
from tests.contracts.test_story_image_adapters import (
    ByteStream, IMAGE_MODEL, REVIEW_MODEL, SYNTHETIC_KEY, artifact, chunk,
    image_reply, png, request, review_reply,
)


@pytest.mark.asyncio
@pytest.mark.parametrize('kind', ['image', 'review'])
@pytest.mark.parametrize('where', ['handler', 'body', 'stream_close', 'client_close'])
@pytest.mark.parametrize('trigger', ['cancel', 'deadline'])
async def test_suppressed_cancellation_cannot_survive_await_or_cleanup(kind, where, trigger):
    entered = asyncio.Event()
    calls = []
    body = json.dumps(image_reply() if kind == 'image' else review_reply()).encode()
    async def swallow():
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
    class UncooperativeStream(ByteStream):
        async def __aiter__(self):
            if where == 'body':
                await swallow()
            yield body
        async def aclose(self):
            if where == 'stream_close':
                await swallow()
            self.closed = True
    stream = UncooperativeStream([])
    class UncooperativeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, http):
            calls.append(http)
            if where == 'handler':
                await swallow()
            return httpx.Response(200, headers={'content-type': 'application/json'}, stream=stream)
        async def aclose(self):
            if where == 'client_close':
                await swallow()
    kwargs = {'api_key': SYNTHETIC_KEY, 'transport': UncooperativeTransport(),
              'timeout_seconds': 0.05 if trigger == 'deadline' else 5}
    if kind == 'image':
        backend = OpenAIImageBackend(options=OpenAIImageOptions(IMAGE_MODEL, 'low'), **kwargs)
        operation = backend.generate(request())
    else:
        backend = OpenAIVisionReviewBackend(options=OpenAIVisionOptions(REVIEW_MODEL, 512), **kwargs)
        operation = backend.review(artifact(), request())
    task = asyncio.create_task(operation)
    if trigger == 'cancel':
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(ImageProviderError, match='timeout'):
            await asyncio.wait_for(task, 2)
    assert len(calls) == 1 and stream.closed


@pytest.mark.parametrize('change', ['no-adler', 'partial-adler', 'extra-data', 'two-streams', 'bomb'])
def test_png_requires_exact_bounded_complete_deflate_stream(change):
    source = png()
    size = struct.unpack_from('>I', source, 33)[0]
    data = source[41:41 + size]
    if change == 'no-adler': data = data[:-4]
    elif change == 'partial-adler': data = data[:-1]
    elif change == 'extra-data': data += b'unclaimed compressed tail'
    elif change == 'two-streams': data += zlib.compress(b'another stream')
    else: data = zlib.compress(b'\0' * 9_000_000)
    invalid = source[:33] + chunk(b'IDAT', data) + chunk(b'IEND', b'')
    with pytest.raises(ImageProviderError):
        PillowPngDecoder().canonicalize(invalid)


def test_png_split_idat_is_one_valid_compressed_stream():
    source = png()
    size = struct.unpack_from('>I', source, 33)[0]
    data = source[41:41 + size]
    parts = [data[:1], data[1:-3], data[-3:-1], data[-1:]]
    split = source[:33] + b''.join(chunk(b'IDAT', value) for value in parts) + chunk(b'IEND', b'')
    assert PillowPngDecoder().canonicalize(split).png == PillowPngDecoder().canonicalize(source).png


def test_fully_opaque_palette_array_keeps_every_pixel():
    with Image.new('P', (1024, 1024), 0) as source:
        source.putpalette([11, 22, 33] + [0, 0, 0] * 255)
        out = io.BytesIO()
        source.save(out, 'PNG', transparency=bytes([255] * 256))
        original = source.convert('RGB').tobytes()
    canonical = PillowPngDecoder().canonicalize(out.getvalue())
    with Image.open(io.BytesIO(canonical.png)) as decoded:
        assert decoded.mode == 'RGB' and decoded.tobytes() == original
        assert sha256(decoded.tobytes()).digest() == sha256(original).digest()


@pytest.mark.parametrize('extra', [b'\0', b'\0' * 3073])
def test_complete_zlib_stream_cannot_hide_extra_uncompressed_raster(extra):
    source = png()
    size = struct.unpack_from('>I', source, 33)[0]
    raster = zlib.decompress(source[41:41 + size])
    invalid = source[:33] + chunk(b'IDAT', zlib.compress(raster + extra)) + chunk(b'IEND', b'')
    with pytest.raises(ImageProviderError):
        PillowPngDecoder().canonicalize(invalid)


def test_valid_adam7_pixels_still_use_maintained_decoder():
    passes = ((0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
              (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2))
    raster = bytearray()
    for x, y, sx, sy in passes:
        columns = (1024 - x + sx - 1) // sx
        rows = (1024 - y + sy - 1) // sy
        raster.extend((b'\0' + bytes((10, 20, 30)) * columns) * rows)
    interlaced = (b'\x89PNG\r\n\x1a\n'
                  + chunk(b'IHDR', struct.pack('>IIBBBBB', 1024, 1024, 8, 2, 0, 0, 1))
                  + chunk(b'IDAT', zlib.compress(raster)) + chunk(b'IEND', b''))
    assert PillowPngDecoder().canonicalize(interlaced).png == PillowPngDecoder().canonicalize(png()).png


@pytest.mark.parametrize('bits', [1, 2, 4])
def test_valid_packed_palette_rows_still_decode(bits):
    with Image.new('P', (1024, 1024), 0) as source:
        source.putpalette([10, 20, 30] + [0, 0, 0] * 255)
        out = io.BytesIO()
        source.save(out, 'PNG', bits=bits)
    assert PillowPngDecoder().canonicalize(out.getvalue()).png == PillowPngDecoder().canonicalize(png()).png
