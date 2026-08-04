#!/usr/bin/env python
# -*- coding: utf-8 -*-

import io
import unittest
from unittest import mock

from PIL import Image

from ai_digest.images import resolver


class FakeResponse:
    """ Minimal stand in for a streamed requests.Response. """

    def __init__(self, chunks, url="https://example.test/page"):
        self.chunks = chunks
        self.url = url
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_exception):
        self.closed = True
        return False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=None):
        for chunk in self.chunks:
            yield chunk


class ReadCappedTest(unittest.TestCase):

    def test_returns_a_body_within_the_limit(self):
        response = FakeResponse([b"a" * 10, b"b" * 10])

        self.assertEqual(b"a" * 10 + b"b" * 10,
                         resolver._read_capped(response, 100))

    def test_stops_once_the_limit_is_exceeded(self):
        response = FakeResponse([b"a" * 60, b"b" * 60])

        self.assertIsNone(resolver._read_capped(response, 100))

    def test_does_not_read_the_whole_body_before_giving_up(self):
        # An endless response must not be buffered in full first; the
        # generator is abandoned as soon as the limit is passed.
        read = []

        def endless():
            while True:
                read.append(1)
                yield b"x" * 1024

        response = FakeResponse([])
        response.iter_content = lambda chunk_size=None: endless()

        self.assertIsNone(resolver._read_capped(response, 4096))
        self.assertLessEqual(len(read), 6)


class FetchTest(unittest.TestCase):

    def fetch(self, url, chunks=(b"body",), limit=1024):
        response = FakeResponse(list(chunks))
        with mock.patch.object(resolver.requests, "get",
                               return_value=response) as getter:
            result = resolver._fetch(url, 5, "ai-digest", limit)
        return result, getter, response

    def test_streams_the_request(self):
        result, getter, response = self.fetch("https://example.test/page")

        self.assertEqual((b"body", "https://example.test/page"), result)
        self.assertTrue(getter.call_args.kwargs["stream"])
        self.assertTrue(response.closed)

    def test_refuses_a_non_http_url_without_requesting_it(self):
        result, getter, _response = self.fetch("file:///etc/passwd")

        self.assertIsNone(result)
        getter.assert_not_called()

    def test_gives_up_on_an_oversized_body(self):
        result, _getter, _response = self.fetch(
            "https://example.test/huge", chunks=(b"x" * 2048,), limit=1024)

        self.assertIsNone(result)

    def test_returns_none_when_the_host_fails(self):
        with mock.patch.object(resolver.requests, "get",
                               side_effect=resolver.requests.RequestException(
                                   "boom")):
            self.assertIsNone(
                resolver._fetch("https://example.test/x", 5, "ai-digest", 10))


class DownloadImageTest(unittest.TestCase):

    def test_oversized_image_is_skipped(self):
        with mock.patch.object(resolver, "_fetch", return_value=None):
            self.assertIsNone(
                resolver._download_image("https://example.test/i.png",
                                         5, "ai-digest"))

    def test_limit_passed_to_fetch_is_the_image_limit(self):
        with mock.patch.object(resolver, "_fetch",
                               return_value=None) as fetcher:
            resolver._download_image("https://example.test/i.png",
                                     5, "ai-digest")

        self.assertEqual(resolver.MAX_IMAGE_BYTES, fetcher.call_args.args[3])

    def test_a_decompression_bomb_yields_none_instead_of_raising(self):
        # A picture of this many pixels compresses to a few hundred
        # kilobytes, so MAX_IMAGE_BYTES lets it through and Pillow
        # refuses it on open. The caller must be able to draw a card.
        side = int((2 * Image.MAX_IMAGE_PIXELS) ** 0.5) + 1000
        buffer = io.BytesIO()
        Image.new("L", (side, side)).save(buffer, format="PNG")
        self.assertLess(len(buffer.getvalue()), resolver.MAX_IMAGE_BYTES)

        with mock.patch.object(resolver, "_fetch",
                               return_value=(buffer.getvalue(),
                                             "https://example.test/i.png")):
            self.assertIsNone(
                resolver._download_image("https://example.test/i.png",
                                         5, "ai-digest"))


if __name__ == "__main__":
    unittest.main()
