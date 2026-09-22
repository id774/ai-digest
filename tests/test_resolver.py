#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_resolver.py: Tests for ai_digest/images/resolver.py
#
#  Description:
#  This test suite covers the fetching of an illustration, which is the
#  part of the run that reaches pages nobody in this project controls.
#  Every case here is about a limit holding: a body is read only up to
#  its cap and the response is abandoned as soon as the cap is passed,
#  rather than being buffered in full and measured afterwards, so that
#  an endless response cannot exhaust the memory of the host.
#
#  The rest is the best-effort contract. Retrieval is HTTPS-only: a
#  direct http source and an http redirect target are both refused
#  without a plaintext request ever being sent, a host that fails and an
#  image Pillow refuses both yield None, and a decompression bomb, which
#  is small enough to pass the byte limit and only refused on open,
#  yields None as well. The caller has to be able to draw a fallback
#  card in every one of those cases rather than lose the run. This is
#  separate from published citation compatibility: an http citation can
#  still derive an HTTPS ar5iv URL to fetch.
#
#  No request is made. resolver.https_get is replaced by a stub
#  returning a stand-in response for most cases; the direct HTTP source
#  and SSRF refusal cases go through the real transport helper with
#  requests.Session mocked instead, so that "no request is ever sent" is
#  proven rather than assumed. The suite needs no network either way.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Running the tests:
#  Run the whole suite from the repository root:
#      python -m unittest discover -s tests
#  Run this module alone:
#      python -m unittest tests.test_resolver
#
#  Test Cases:
#    - Return a body that stays within the limit.
#    - Stop reading once the limit is exceeded.
#    - Abandon the response instead of reading the whole body first.
#    - Stream the request and close the response.
#    - Give up on an oversized body.
#    - Return None when the host fails.
#    - Skip an oversized image.
#    - Pass MAX_IMAGE_BYTES as the limit when fetching an image.
#    - Return None for a decompression bomb instead of raising.
#    - Refuse a direct http page and a direct http image candidate
#      without ever creating a Session.
#    - Refuse an HTTPS to http downgrade redirect target.
#    - Derive the HTTPS ar5iv URL from an http arXiv citation.
#    - Judge a public, loopback, private, link-local, unspecified and
#      multicast address correctly, multicast in particular, since it
#      reports is_global True and is excluded only by is_multicast.
#    - Refuse a loopback or private IP literal, a hostless URL, and a DNS
#      name that resolves to a non-global address, one among several
#      included.
#    - Treat DNS resolution failure as the same refusal family as any
#      other non-public target, so the caller's existing fallback holds.
#    - Prove, through the real transport with Session mocked, that a
#      direct loopback or private target, a DNS name resolving to one, and
#      a redirect from a public target to a private one are all refused
#      before a next request is sent.
#    - Prove that validate_and_pin_public_target() pins a hostname's
#      resolution to the address it validated, restores the real resolver
#      on exit, and leaves a lookup for any other host untouched, so a
#      second, rebound DNS answer for the pinned host is never reached.
#    - Refuse a decompression-bomb-warning-range image the same as one
#      past the error threshold, and keep an ordinary image usable.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Pillow, requests, beautifulsoup4
#
#  Version History:
#  v1.2 2026-09-22
#       Cover connection pinning against DNS rebinding, and
#       decompression-bomb-warning-range refusal.
#  v1.1 2026-09-08
#       Cover HTTPS-only page and image retrieval.
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import io
import ipaddress
import unittest
from unittest import mock

from PIL import Image

from ai_digest import transport
from ai_digest.images import resolver
from ai_digest.transport import HTTPSOnlyError


class _FakeRedirectResponse:
    """
    Stand in for the non-streamed response transport.https_get() itself
    sees at the Session.get() boundary: it needs status_code and
    headers, which resolver.py's own FakeResponse (a streamed body
    reader) has no reason to carry.
    """

    def __init__(self, status_code, headers=None,
                url="https://example.test/a"):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        return None


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
        with mock.patch.object(resolver, "https_get",
                               return_value=response) as getter:
            result = resolver._fetch(url, 5, "ai-digest", limit)
        return result, getter, response

    def test_streams_the_request(self):
        result, getter, response = self.fetch("https://example.test/page")

        self.assertEqual((b"body", "https://example.test/page"), result)
        self.assertTrue(getter.call_args.kwargs["stream"])
        self.assertTrue(response.closed)

    def test_gives_up_on_an_oversized_body(self):
        result, _getter, _response = self.fetch(
            "https://example.test/huge", chunks=(b"x" * 2048,), limit=1024)

        self.assertIsNone(result)

    def test_returns_none_when_the_host_fails(self):
        with mock.patch.object(resolver, "https_get",
                               side_effect=resolver.requests.RequestException(
                                   "boom")):
            self.assertIsNone(
                resolver._fetch("https://example.test/x", 5, "ai-digest", 10))

    def test_returns_none_on_a_downgrade_redirect(self):
        with mock.patch.object(resolver, "https_get",
                               side_effect=HTTPSOnlyError(
                                   "refusing non-HTTPS redirect target")):
            self.assertIsNone(
                resolver._fetch("https://example.test/x", 5, "ai-digest", 10))


class DirectHttpSourceTest(unittest.TestCase):
    """
    A direct http source must never create a Session: the refusal
    happens inside https_get() before any network object exists, not
    only inside _fetch()'s own error handling.
    """

    def test_a_direct_http_page_is_never_requested(self):
        with mock.patch.object(transport.requests, "Session") as session_cls:
            result = resolver._fetch("http://example.test/page", 5,
                                     "ai-digest", 1024)

        self.assertIsNone(result)
        session_cls.assert_not_called()

    def test_a_direct_http_image_candidate_is_never_requested(self):
        with mock.patch.object(transport.requests, "Session") as session_cls:
            result = resolver._download_image("http://example.test/i.png",
                                              5, "ai-digest")

        self.assertIsNone(result)
        session_cls.assert_not_called()


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

    def test_a_decompression_bomb_warning_range_image_also_yields_none(self):
        # Below 2x MAX_IMAGE_PIXELS, Pillow only warns instead of
        # raising; that range must be refused just as the error range
        # is, not let through as a usable image.
        side = int((1.5 * Image.MAX_IMAGE_PIXELS) ** 0.5) + 10
        buffer = io.BytesIO()
        Image.new("L", (side, side)).save(buffer, format="PNG")
        self.assertLess(len(buffer.getvalue()), resolver.MAX_IMAGE_BYTES)

        with mock.patch.object(resolver, "_fetch",
                               return_value=(buffer.getvalue(),
                                             "https://example.test/i.png")):
            self.assertIsNone(
                resolver._download_image("https://example.test/i.png",
                                         5, "ai-digest"))

    def test_an_ordinary_image_is_still_usable(self):
        buffer = io.BytesIO()
        Image.new("RGB", (300, 300), color=(10, 20, 30)).save(
            buffer, format="PNG")

        with mock.patch.object(resolver, "_fetch",
                               return_value=(buffer.getvalue(),
                                             "https://example.test/i.png")):
            result = resolver._download_image("https://example.test/i.png",
                                              5, "ai-digest")

        self.assertIsNotNone(result)
        content, extension = result
        self.assertEqual(buffer.getvalue(), content)
        self.assertEqual("png", extension)


class PublicAddressJudgmentTest(unittest.TestCase):
    """ _is_public_address() judges is_global and multicast together. """

    def test_accepts_a_public_ipv4_address(self):
        self.assertTrue(
            resolver._is_public_address(ipaddress.ip_address("8.8.8.8")))

    def test_accepts_a_public_ipv6_address(self):
        self.assertTrue(resolver._is_public_address(
            ipaddress.ip_address("2001:4860:4860::8888")))

    def test_rejects_loopback(self):
        self.assertFalse(
            resolver._is_public_address(ipaddress.ip_address("127.0.0.1")))

    def test_rejects_private(self):
        self.assertFalse(
            resolver._is_public_address(ipaddress.ip_address("10.0.0.5")))

    def test_rejects_link_local(self):
        self.assertFalse(resolver._is_public_address(
            ipaddress.ip_address("169.254.1.1")))

    def test_rejects_unspecified(self):
        self.assertFalse(
            resolver._is_public_address(ipaddress.ip_address("0.0.0.0")))

    def test_rejects_multicast_even_though_it_is_global(self):
        # 224.0.0.0/4 reports is_global True; is_multicast is what
        # actually excludes it, so this pins that is_global alone is
        # not what _is_public_address relies on.
        address = ipaddress.ip_address("224.0.0.1")
        self.assertTrue(address.is_global)
        self.assertFalse(resolver._is_public_address(address))

    def test_rejects_ipv6_loopback_and_link_local(self):
        self.assertFalse(
            resolver._is_public_address(ipaddress.ip_address("::1")))
        self.assertFalse(
            resolver._is_public_address(ipaddress.ip_address("fe80::1")))


class ValidatePublicTargetTest(unittest.TestCase):
    """
    validate_and_pin_public_target() is the target_pin the resolver
    hands to https_get(), so it must refuse before any request rather
    than after: these cases enter it directly, on both a literal IP
    host and a DNS name resolved through a mocked getaddrinfo().
    """

    def test_accepts_a_public_ip_literal(self):
        with resolver.validate_and_pin_public_target("https://8.8.8.8/x"):
            pass

    def test_refuses_a_loopback_ip_literal(self):
        with self.assertRaises(resolver.PublicNetworkOnlyError):
            with resolver.validate_and_pin_public_target(
                    "https://127.0.0.1/x"):
                pass

    def test_refuses_a_private_ip_literal(self):
        with self.assertRaises(resolver.PublicNetworkOnlyError):
            with resolver.validate_and_pin_public_target(
                    "https://192.168.1.1/x"):
                pass

    def test_refuses_a_url_with_no_host(self):
        with self.assertRaises(resolver.PublicNetworkOnlyError):
            with resolver.validate_and_pin_public_target("https:///x"):
                pass

    def test_accepts_a_dns_name_resolving_to_a_public_address(self):
        addrinfo = [(None, None, None, None, ("93.184.216.34", 443))]
        with mock.patch.object(resolver.socket, "getaddrinfo",
                               return_value=addrinfo):
            with resolver.validate_and_pin_public_target(
                    "https://example.test/x"):
                pass

    def test_refuses_a_dns_name_resolving_to_a_private_address(self):
        addrinfo = [(None, None, None, None, ("10.0.0.9", 443))]
        with mock.patch.object(resolver.socket, "getaddrinfo",
                               return_value=addrinfo):
            with self.assertRaises(resolver.PublicNetworkOnlyError):
                with resolver.validate_and_pin_public_target(
                        "https://internal.example/x"):
                    pass

    def test_refuses_when_any_resolved_address_is_non_global(self):
        addrinfo = [
            (None, None, None, None, ("93.184.216.34", 443)),
            (None, None, None, None, ("127.0.0.1", 443)),
        ]
        with mock.patch.object(resolver.socket, "getaddrinfo",
                               return_value=addrinfo):
            with self.assertRaises(resolver.PublicNetworkOnlyError):
                with resolver.validate_and_pin_public_target(
                        "https://mixed.example/x"):
                    pass

    def test_dns_resolution_failure_raises_the_same_error_family(self):
        with mock.patch.object(
                resolver.socket, "getaddrinfo",
                side_effect=resolver.socket.gaierror("name not known")):
            with self.assertRaises(resolver.PublicNetworkOnlyError):
                with resolver.validate_and_pin_public_target(
                        "https://nowhere.example/x"):
                    pass

    def test_restores_getaddrinfo_after_the_context_exits(self):
        addrinfo = [(None, None, None, None, ("93.184.216.34", 443))]
        with mock.patch.object(resolver.socket, "getaddrinfo",
                               return_value=addrinfo):
            patched_during_test = resolver.socket.getaddrinfo
            with resolver.validate_and_pin_public_target(
                    "https://example.test/x"):
                self.assertIsNot(patched_during_test,
                                 resolver.socket.getaddrinfo)
            self.assertIs(patched_during_test, resolver.socket.getaddrinfo)

    def test_pins_the_connection_against_a_rebinding_second_lookup(self):
        # Simulates DNS rebinding: the name server answers the
        # validation lookup with a public address, then would answer a
        # second lookup for the same host with a private one. Pinning
        # must mean a lookup made from inside the context never reaches
        # that second, rebound answer.
        public_answer = [(None, None, None, None, ("93.184.216.34", 443))]
        rebound_answer = [(None, None, None, None, ("127.0.0.1", 443))]
        real_getaddrinfo = mock.Mock(
            side_effect=[public_answer, rebound_answer])

        with mock.patch.object(resolver.socket, "getaddrinfo",
                               real_getaddrinfo):
            with resolver.validate_and_pin_public_target(
                    "https://rebind.example/x"):
                reconnect = resolver.socket.getaddrinfo(
                    "rebind.example", 443)

        self.assertEqual([("93.184.216.34", 443)],
                         [info[4] for info in reconnect])
        self.assertEqual(1, real_getaddrinfo.call_count)

    def test_a_lookup_for_a_different_host_passes_through_during_the_pin(
            self):
        addrinfo = [(None, None, None, None, ("93.184.216.34", 443))]
        other_host_answer = [(None, None, None, None, ("198.51.100.7", 80))]
        real_getaddrinfo = mock.Mock(
            side_effect=[addrinfo, other_host_answer])

        with mock.patch.object(resolver.socket, "getaddrinfo",
                               real_getaddrinfo):
            with resolver.validate_and_pin_public_target(
                    "https://pinned.example/x"):
                other = resolver.socket.getaddrinfo("other.example", 80)

        self.assertEqual(other_host_answer, other)
        self.assertEqual(2, real_getaddrinfo.call_count)


class SSRFRefusalIntegrationTest(unittest.TestCase):
    """
    These cases go through the real transport.https_get(), with
    requests.Session mocked, so that a loopback or private target -
    direct or reached through a redirect from a public one - is proven
    to never reach an actual request, the same guarantee
    DirectHttpSourceTest pins for a plaintext target. target_pin wraps
    the request itself rather than running before the Session exists,
    so what these cases pin is that Session.get() is never called, not
    that Session() itself is never constructed.
    """

    def test_a_direct_loopback_ip_target_is_never_requested(self):
        with mock.patch.object(transport.requests, "Session") as session_cls:
            result = resolver._fetch("https://127.0.0.1/page", 5,
                                     "ai-digest", 1024)

        self.assertIsNone(result)
        session_cls.return_value.get.assert_not_called()

    def test_a_direct_private_ip_target_is_never_requested(self):
        with mock.patch.object(transport.requests, "Session") as session_cls:
            result = resolver._fetch("https://10.0.0.5/page", 5,
                                     "ai-digest", 1024)

        self.assertIsNone(result)
        session_cls.return_value.get.assert_not_called()

    def test_a_dns_name_resolving_to_a_private_address_is_never_requested(
            self):
        addrinfo = [(None, None, None, None, ("192.168.1.1", 443))]
        with mock.patch.object(resolver.socket, "getaddrinfo",
                               return_value=addrinfo):
            with mock.patch.object(transport.requests,
                                   "Session") as session_cls:
                result = resolver._fetch("https://internal.example/page", 5,
                                         "ai-digest", 1024)

        self.assertIsNone(result)
        session_cls.return_value.get.assert_not_called()

    def test_a_redirect_from_public_to_private_is_refused_before_the_next_request(
            self):
        first = _FakeRedirectResponse(
            302, headers={"Location": "https://127.0.0.1/internal"},
            url="https://example.test/a")
        session = mock.MagicMock()
        session.__enter__.return_value = session
        session.__exit__.return_value = False
        session.get.side_effect = [first]
        # example.test itself must resolve publicly, so the redirect to
        # the loopback literal is what gets refused, not the first hop.
        addrinfo = [(None, None, None, None, ("93.184.216.34", 443))]

        with mock.patch.object(resolver.socket, "getaddrinfo",
                               return_value=addrinfo):
            with mock.patch.object(transport.requests, "Session",
                                   return_value=session):
                result = resolver._fetch("https://example.test/a", 5,
                                         "ai-digest", 1024)

        self.assertIsNone(result)
        self.assertEqual(1, session.get.call_count)
        self.assertTrue(first.closed)


class ArxivFigureUrlTest(unittest.TestCase):
    """
    An http arXiv citation is a valid published link, but the figure is
    still fetched from the HTTPS ar5iv rendering: the citation itself is
    never requested.
    """

    def test_derives_the_https_ar5iv_url_from_an_http_citation(self):
        with mock.patch.object(resolver, "_fetch",
                               return_value=None) as fetcher:
            resolver.arxiv_figure_url("http://arxiv.org/abs/2601.00001",
                                      5, "ai-digest")

        fetcher.assert_called_once()
        self.assertEqual("https://ar5iv.labs.arxiv.org/html/2601.00001",
                         fetcher.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
