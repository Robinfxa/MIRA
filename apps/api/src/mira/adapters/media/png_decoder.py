"""Strict PNG container bounds plus maintained Pillow decoding and canonical encoding.

Container inspection is not a pixel codec: Pillow verifies, fully decompresses,
converts and encodes every accepted raster. No process-global Pillow flags change.
"""
import io
import struct
import warnings
import zlib

from mira.application.ports.media import CanonicalImage
from mira.domain.story_images import SQUARE_OUTPUT_POLICY, image_output_dimensions
from ._openai_http import MAX_IMAGE_BYTES, PNG_SIGNATURE, ImageProviderError


class PillowPngDecoder:
    def __init__(self, *, max_bytes: int = MAX_IMAGE_BYTES, width: int = 1024, height: int = 1024,
                 output_dimension_policy: str = SQUARE_OUTPUT_POLICY):
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_IMAGE_BYTES:
            raise ValueError('image_decoder_byte_limit_invalid')
        if type(width) is not int or type(height) is not int or (width, height) != (1024, 1024):
            raise ValueError('image_decoder_dimensions_invalid')
        self._max_bytes = max_bytes
        self._allowed_sizes = image_output_dimensions(output_dimension_policy)

    def _verify_container(self, data: bytes) -> tuple[list[memoryview], tuple[int, int]]:
        if type(data) is not bytes or not 1 <= len(data) <= self._max_bytes or not data.startswith(PNG_SIGNATURE):
            raise ImageProviderError('image_png_input')
        offset, count = 8, 0
        compressed: list[memoryview] = []
        dimensions = None
        while offset + 12 <= len(data):
            size = struct.unpack_from('>I', data, offset)[0]
            end = offset + size + 12
            if end > len(data) or count >= 4096:
                raise ImageProviderError('image_png_container')
            kind = data[offset + 4:offset + 8]
            if kind in (b'acTL', b'fcTL', b'fdAT'):
                raise ImageProviderError('image_png_animation')
            if count == 0 and (kind != b'IHDR' or size != 13):
                raise ImageProviderError('image_png_header')
            if kind == b'IHDR':
                if count != 0 or size != 13:
                    raise ImageProviderError('image_png_dimensions')
                dimensions = struct.unpack_from('>II', data, offset + 8)
                if dimensions not in self._allowed_sizes:
                    raise ImageProviderError('image_png_dimensions')
            expected = struct.unpack_from('>I', data, end - 4)[0]
            if zlib.crc32(memoryview(data)[offset + 4:end - 4]) != expected:
                raise ImageProviderError('image_png_crc')
            if kind == b'IDAT':
                compressed.append(memoryview(data)[offset + 8:end - 4])
            if kind == b'IEND':
                if size or end != len(data):
                    raise ImageProviderError('image_png_trailing')
                if not compressed:
                    raise ImageProviderError('image_png_missing_pixels')
                return compressed, dimensions
            offset, count = end, count + 1
        raise ImageProviderError('image_png_truncated')

    def _filtered_byte_count(self, data: bytes, dimensions: tuple[int, int]) -> int:
        # Count the declared raster envelope only, without interpreting filters
        # or pixels. PNG sections 7/8/10 define packed rows plus one filter byte.
        depth, color, compression, filtering, interlace = struct.unpack_from('>BBBBB', data, 24)
        samples = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}
        depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
                  4: (8, 16), 6: (8, 16)}
        if (color not in samples or depth not in depths[color]
                or compression != 0 or filtering != 0 or interlace not in (0, 1)):
            raise ImageProviderError('image_png_header')
        passes = ((0, 0, 1, 1),) if not interlace else (
            (0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4),
            (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2),
        )
        total = 0
        for x, y, step_x, step_y in passes:
            columns = (dimensions[0] - x + step_x - 1) // step_x
            rows = (dimensions[1] - y + step_y - 1) // step_y
            if columns > 0 and rows > 0:
                total += rows * (1 + (columns * samples[color] * depth + 7) // 8)
        return total

    def _verify_compressed_stream(self, parts: list[memoryview], expected_bytes: int) -> None:
        # Pillow deliberately tolerates some zlib trailing/truncated data even
        # when LOAD_TRUNCATED_IMAGES is false. Validate only compressed-stream
        # completeness here; Pillow remains the sole PNG filter/pixel decoder.
        # Exact header-derived byte count rejects hidden extra raster data as
        # well as bombs; each temporary output allocation stays at most 64 KiB.
        maximum = expected_bytes
        total = 0
        decompressor = zlib.decompressobj()
        try:
            for part in parts:
                pending = part
                while pending:
                    if decompressor.eof:
                        raise ImageProviderError('image_png_deflate_trailing')
                    decoded = decompressor.decompress(pending, min(65_536, maximum - total + 1))
                    total += len(decoded)
                    if total > maximum:
                        raise ImageProviderError('image_png_deflate_limit')
                    if decompressor.unused_data:
                        raise ImageProviderError('image_png_deflate_trailing')
                    pending = decompressor.unconsumed_tail
            if (not decompressor.eof or decompressor.unused_data
                    or decompressor.unconsumed_tail or total != expected_bytes):
                raise ImageProviderError('image_png_deflate_incomplete')
        except zlib.error:
            raise ImageProviderError('image_png_deflate_invalid') from None

    def canonicalize(self, data: bytes) -> CanonicalImage:
        compressed, dimensions = self._verify_container(data)
        self._verify_compressed_stream(compressed, self._filtered_byte_count(data, dimensions))
        # Import is delayed until capability use, not environment/config discovery.
        from PIL import Image, ImageFile, UnidentifiedImageError
        if ImageFile.LOAD_TRUNCATED_IMAGES:
            raise ImageProviderError('image_png_decoder_tolerance')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error')
                with Image.open(io.BytesIO(data), formats=('PNG',)) as source:
                    if source.size != dimensions or getattr(source, 'n_frames', 1) != 1:
                        raise ImageProviderError('image_png_dimensions')
                    source.verify()
                with Image.open(io.BytesIO(data), formats=('PNG',)) as source:
                    source.load()
                    # Opaque output can still be encoded with an alpha channel. Accept
                    # it only when every alpha value is 255; never silently composite.
                    if source.mode not in ('RGB', 'RGBA', 'L', 'LA', 'P'):
                        raise ImageProviderError('image_png_mode')
                    # Always take palette tRNS through RGBA. Direct P -> RGB
                    # warns for byte-array tRNS even after an earlier alpha check.
                    with source.convert('RGBA') as rgba:
                        with rgba.getchannel('A') as alpha:
                            if alpha.getextrema() != (255, 255):
                                raise ImageProviderError('image_png_transparency')
                        with rgba.convert('RGB') as rgb:
                            # Fresh pixels carry no EXIF, ICC, text or ancillary metadata.
                            with Image.frombytes('RGB', dimensions, rgb.tobytes()) as clean:
                                output = io.BytesIO()
                                clean.save(output, format='PNG', optimize=False, compress_level=9)
                                canonical = output.getvalue()
            if len(canonical) > self._max_bytes:
                raise ImageProviderError('image_png_output_limit')
            return CanonicalImage(canonical, *dimensions)
        except ImageProviderError:
            raise  # Preserve only the fixed local code; no payload or exception text.
        except (OSError, ValueError, SyntaxError, Warning, UnidentifiedImageError):
            raise ImageProviderError('image_png_decode') from None
