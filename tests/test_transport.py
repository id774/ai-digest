#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_transport.py: Tests for ai_digest/transport.py
#
#  Description:
#  This test suite covers the shared HTTPS retrieval boundary every
#  collector and the image resolver call through. is_https_url() is
#  checked on its own first, since https_get() relies on it both for the
#  initial target and for every redirect target.
#
#  https_get() itself is exercised with a mocked requests.Session, whose
#  get() is scripted to return one fake response per hop: a normal
#  request, a relative redirect, an absolute redirect, a downgrade to
#  http, a malformed redirect target, and a redirect chain longer than
#  the configured bound. Each case also pins that the request carries
#  the given timeout, User-Agent and stream flag, that no verify=False
#  is ever passed, and that every intermediate and final response is
#  closed.
#
#  No network is used. requests.Session is replaced by a mock, so the
#  suite needs no network.
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
#      python -m unittest tests.test_transport
#
#  Test Cases:
#    - Judge is_https_url() on scheme, host presence and malformed input.
#    - Refuse a non-HTTPS initial target without creating a Session.
#    - Send a normal HTTPS request with the given timeout, User-Agent and
#      stream flag, and no verify=False.
#    - Follow a relative HTTPS redirect, reusing the same request options.
#    - Follow an absolute HTTPS redirect.
#    - Refuse a downgrade to http before a plaintext request is sent.
#    - Refuse a malformed redirect target before the next request is sent.
#    - Bound the redirect chain and raise TooManyRedirects.
#    - Close the Session on both success and failure.
#    - Run target_pin on the initial target before any request, and on
#      every redirect hop before it is followed, stopping the chain when
#      it refuses one.
#    - Return a streamed body within the limit, accept one at exactly the
#      limit, and give up once it is exceeded without buffering an endless
#      one in full first.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - requests
#
#  Version History:
#  v1.1 2026-09-22
#       Cover target_pin, trust_env, a fetch-wide elapsed deadline, and
#       stricter HTTPS URL validation by hostname and port.
#  v1.0 2026-09-08
#       Initial release.
#
########################################################################

import contextlib
import unittest
from unittest import mock

from ai_digest import transport


class FakeResponse:
    """ Minimal stand in for a requests.Response, not a context manager. """

    def __init__(self, status_code=200, headers=None,
                url="https://example.test/a"):
        self.status_code = status_code
        self.headers = headers or {}
        self.url = url
        self.closed = False

    def close(self):
        self.closed = True

    def raise_for_status(self):
        return None


def _fake_session(*responses):
    """ Return a mocked requests.Session yielding responses in order. """
    session = mock.MagicMock()
    session.__enter__.return_value = session
    session.__exit__.return_value = False
    session.get.side_effect = list(responses)
    return session


class IsHttpsUrlTest(unittest.TestCase):

    def test_accepts_a_plain_https_url(self):
        self.assertTrue(transport.is_https_url("https://example.test/x"))

    def test_accepts_a_port_and_query(self):
        self.assertTrue(
            transport.is_https_url("https://example.test:8443/x?q=1"))

    def test_rejects_http(self):
        self.assertFalse(transport.is_https_url("http://example.test/x"))

    def test_rejects_a_schemeless_value(self):
        self.assertFalse(transport.is_https_url("example.test/x"))

    def test_rejects_a_hostless_https_url(self):
        self.assertFalse(transport.is_https_url("https:///x"))

    def test_rejects_a_malformed_ipv6_literal(self):
        self.assertFalse(transport.is_https_url("https://[::1/x"))

    def test_rejects_an_empty_value(self):
        self.assertFalse(transport.is_https_url(""))

    def test_rejects_a_port_with_no_host(self):
        self.assertFalse(transport.is_https_url("https://:8443/x"))

    def test_rejects_credentials_with_no_host(self):
        self.assertFalse(transport.is_https_url("https://user:pass@/x"))

    def test_rejects_a_port_above_the_valid_range(self):
        self.assertFalse(
            transport.is_https_url("https://example.test:99999/x"))

    def test_rejects_a_non_numeric_port(self):
        self.assertFalse(
            transport.is_https_url("https://example.test:abc/x"))


class InitialTargetRefusalTest(unittest.TestCase):

    def test_a_non_https_target_never_creates_a_session(self):
        with mock.patch.object(transport.requests, "Session") as session_cls:
            with self.assertRaises(transport.HTTPSOnlyError):
                with transport.https_get("http://example.test/a", 5, "ua"):
                    pass

        session_cls.assert_not_called()


class TrustEnvTest(unittest.TestCase):
    """
    trust_env controls whether the Session reads proxy settings (and
    other environment-driven defaults) from the process environment.
    Collectors need it on, so a configured proxy still carries their
    requests; the image resolver turns it off, so a proxy can never
    quietly pick the destination target_pin validated.
    """

    def test_defaults_to_true(self):
        response = FakeResponse(200)
        session = _fake_session(response)

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with transport.https_get("https://example.test/a", 5, "ua"):
                pass

        self.assertTrue(session.trust_env)

    def test_can_be_turned_off(self):
        response = FakeResponse(200)
        session = _fake_session(response)

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with transport.https_get("https://example.test/a", 5, "ua",
                                     trust_env=False):
                pass

        self.assertFalse(session.trust_env)


class NormalRequestTest(unittest.TestCase):

    def test_sends_one_request_with_the_given_options(self):
        response = FakeResponse(200, url="https://example.test/a")
        session = _fake_session(response)

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with transport.https_get("https://example.test/a", 5, "ua",
                                     stream=True) as got:
                self.assertIs(response, got)

        self.assertEqual(1, session.get.call_count)
        call = session.get.call_args
        self.assertEqual("https://example.test/a", call.args[0])
        # The remaining fetch budget, not the original timeout value
        # verbatim: negligibly less, since computing it costs time too.
        self.assertAlmostEqual(5, call.kwargs["timeout"], delta=1)
        self.assertEqual({"User-Agent": "ua"}, call.kwargs["headers"])
        self.assertTrue(call.kwargs["stream"])
        self.assertFalse(call.kwargs["allow_redirects"])
        self.assertNotIn("verify", call.kwargs)
        self.assertTrue(response.closed)


class RelativeRedirectTest(unittest.TestCase):

    def test_follows_a_relative_https_redirect(self):
        first = FakeResponse(302, headers={"Location": "/b"},
                             url="https://example.test/a")
        second = FakeResponse(200, url="https://example.test/b")
        session = _fake_session(first, second)

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with transport.https_get("https://example.test/a", 5, "ua",
                                     stream=True) as got:
                self.assertIs(second, got)

        self.assertEqual(2, session.get.call_count)
        first_call, second_call = session.get.call_args_list
        self.assertEqual("https://example.test/a", first_call.args[0])
        self.assertEqual("https://example.test/b", second_call.args[0])
        for call in (first_call, second_call):
            self.assertAlmostEqual(5, call.kwargs["timeout"], delta=1)
            self.assertEqual({"User-Agent": "ua"}, call.kwargs["headers"])
            self.assertTrue(call.kwargs["stream"])
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)


class AbsoluteRedirectTest(unittest.TestCase):

    def test_follows_an_absolute_https_redirect(self):
        first = FakeResponse(
            302, headers={"Location": "https://other.example/b"},
            url="https://example.test/a")
        second = FakeResponse(200, url="https://other.example/b")
        session = _fake_session(first, second)

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with transport.https_get("https://example.test/a", 5, "ua") as got:
                self.assertIs(second, got)

        self.assertEqual(2, session.get.call_count)
        self.assertEqual("https://other.example/b",
                         session.get.call_args_list[1].args[0])
        self.assertTrue(first.closed)


class DowngradeRedirectTest(unittest.TestCase):

    def test_refuses_a_downgrade_before_the_next_request(self):
        first = FakeResponse(
            302, headers={"Location": "http://other.example/b"},
            url="https://example.test/a")
        session = _fake_session(first)

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with self.assertRaises(transport.HTTPSOnlyError):
                with transport.https_get("https://example.test/a", 5, "ua"):
                    pass

        self.assertEqual(1, session.get.call_count)
        self.assertTrue(first.closed)


class MalformedRedirectTest(unittest.TestCase):

    def test_refuses_a_malformed_redirect_target(self):
        first = FakeResponse(
            302, headers={"Location": "https://[::1/b"},
            url="https://example.test/a")
        session = _fake_session(first)

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with self.assertRaises(transport.HTTPSOnlyError):
                with transport.https_get("https://example.test/a", 5, "ua"):
                    pass

        self.assertEqual(1, session.get.call_count)
        self.assertTrue(first.closed)


class RedirectBoundTest(unittest.TestCase):

    def test_a_chain_past_the_bound_raises_too_many_redirects(self):
        r0 = FakeResponse(302, headers={"Location": "https://example.test/1"},
                          url="https://example.test/0")
        r1 = FakeResponse(302, headers={"Location": "https://example.test/2"},
                          url="https://example.test/1")
        r2 = FakeResponse(302, headers={"Location": "https://example.test/3"},
                          url="https://example.test/2")
        session = _fake_session(r0, r1, r2)

        with mock.patch.object(transport, "MAX_REDIRECTS", 2):
            with mock.patch.object(transport.requests, "Session",
                                   return_value=session):
                with self.assertRaises(transport.requests.TooManyRedirects):
                    with transport.https_get("https://example.test/0", 5,
                                             "ua"):
                        pass

        self.assertEqual(3, session.get.call_count)
        self.assertTrue(r0.closed)
        self.assertTrue(r1.closed)
        self.assertTrue(r2.closed)


class _RecordingPin:
    """
    A target_pin double: a context manager factory that records every
    URL it wrapped, in call order, and refuses the call numbered
    refuse_at (1-based) by raising before yielding.
    """

    def __init__(self, refuse_at=None, refuse_message="refused"):
        self.calls = []
        self.refuse_at = refuse_at
        self.refuse_message = refuse_message

    @contextlib.contextmanager
    def __call__(self, url):
        self.calls.append(url)
        if self.refuse_at is not None and len(self.calls) == self.refuse_at:
            raise RuntimeError(self.refuse_message)
        yield


class TargetPinTest(unittest.TestCase):
    """
    target_pin wraps the request itself, for the initial target and for
    every redirect hop, before the request for it is sent: it can
    refuse a target the way target_validator once did, and it can also
    pin how the wrapped request resolves its host, since validating and
    connecting now happen inside the same context.
    """

    def test_pin_wraps_the_initial_target_before_any_request(self):
        pin = _RecordingPin(refuse_at=1)

        with mock.patch.object(transport.requests, "Session") as session_cls:
            with self.assertRaises(RuntimeError):
                with transport.https_get("https://example.test/a", 5, "ua",
                                         target_pin=pin):
                    pass

        self.assertEqual(["https://example.test/a"], pin.calls)
        session_cls.return_value.get.assert_not_called()

    def test_pin_wraps_each_redirect_hop(self):
        first = FakeResponse(
            302, headers={"Location": "https://other.example/b"},
            url="https://example.test/a")
        second = FakeResponse(200, url="https://other.example/b")
        session = _fake_session(first, second)
        pin = _RecordingPin()

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with transport.https_get("https://example.test/a", 5, "ua",
                                     target_pin=pin):
                pass

        self.assertEqual(
            ["https://example.test/a", "https://other.example/b"],
            pin.calls)

    def test_a_redirect_refused_by_the_pin_stops_before_it_is_followed(self):
        first = FakeResponse(
            302, headers={"Location": "https://internal.example/b"},
            url="https://example.test/a")
        session = _fake_session(first)
        pin = _RecordingPin(refuse_at=2, refuse_message="refusing internal")

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with self.assertRaises(RuntimeError):
                with transport.https_get("https://example.test/a", 5, "ua",
                                         target_pin=pin):
                    pass

        self.assertEqual(1, session.get.call_count)
        self.assertTrue(first.closed)


class SessionClosureTest(unittest.TestCase):

    def test_session_closes_on_success(self):
        response = FakeResponse(200)
        session = _fake_session(response)

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with transport.https_get("https://example.test/a", 5, "ua"):
                pass

        session.__exit__.assert_called_once()

    def test_session_closes_on_failure(self):
        session = _fake_session()
        session.get.side_effect = transport.requests.ConnectionError("boom")

        with mock.patch.object(transport.requests, "Session",
                               return_value=session):
            with self.assertRaises(transport.requests.ConnectionError):
                with transport.https_get("https://example.test/a", 5, "ua"):
                    pass

        session.__exit__.assert_called_once()


class FetchDeadlineTest(unittest.TestCase):
    """
    timeout bounds the whole fetch, not each hop separately: a redirect
    chain must not add up to more than timeout seconds by handing every
    hop the full budget again.
    """

    def test_a_later_hop_gets_less_time_than_the_first(self):
        first = FakeResponse(302, headers={"Location": "https://example.test/b"},
                             url="https://example.test/a")
        second = FakeResponse(200, url="https://example.test/b")
        session = _fake_session(first, second)
        # monotonic() calls, in order: the initial deadline, the first
        # hop's remaining-time check, the second hop's.
        clock = mock.Mock(side_effect=[100.0, 100.0, 102.0])

        with mock.patch.object(transport.time, "monotonic", clock):
            with mock.patch.object(transport.requests, "Session",
                                   return_value=session):
                with transport.https_get("https://example.test/a", 5, "ua"):
                    pass

        first_timeout = session.get.call_args_list[0].kwargs["timeout"]
        second_timeout = session.get.call_args_list[1].kwargs["timeout"]
        self.assertAlmostEqual(5, first_timeout, delta=0.01)
        self.assertAlmostEqual(3, second_timeout, delta=0.01)

    def test_raises_when_no_budget_remains_before_a_hop_is_sent(self):
        first = FakeResponse(302, headers={"Location": "https://example.test/b"},
                             url="https://example.test/a")
        session = _fake_session(first)
        # The deadline has already passed by the time the second hop's
        # remaining-time check runs, so that hop is never requested.
        clock = mock.Mock(side_effect=[100.0, 100.0, 110.0])

        with mock.patch.object(transport.time, "monotonic", clock):
            with mock.patch.object(transport.requests, "Session",
                                   return_value=session):
                with self.assertRaises(transport.FetchTimeoutError):
                    with transport.https_get("https://example.test/a", 5,
                                             "ua"):
                        pass

        self.assertEqual(1, session.get.call_count)
        self.assertTrue(first.closed)

    def test_the_yielded_response_carries_the_deadline(self):
        response = FakeResponse(200)
        session = _fake_session(response)

        with mock.patch.object(transport.time, "monotonic",
                               return_value=100.0):
            with mock.patch.object(transport.requests, "Session",
                                   return_value=session):
                with transport.https_get("https://example.test/a", 5,
                                         "ua") as got:
                    self.assertEqual(105.0, transport.fetch_deadline(got))

    def test_fetch_deadline_is_none_for_an_unrelated_response(self):
        self.assertIsNone(transport.fetch_deadline(FakeResponse(200)))


class _StreamedFakeResponse:
    """ Minimal stand in for a streamed response's body iteration. """

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def iter_content(self, chunk_size=None):
        for chunk in self.chunks:
            yield chunk


class ReadCappedContentTest(unittest.TestCase):
    """
    read_capped_content() is what keeps the arXiv and news feed
    collectors from buffering an oversized or endless response body in
    full: it counts as chunks arrive and gives up as soon as the limit
    is passed, never after the whole body has already been read.
    """

    def test_returns_a_body_within_the_limit(self):
        response = _StreamedFakeResponse([b"a" * 10, b"b" * 10])

        self.assertEqual(b"a" * 10 + b"b" * 10,
                         transport.read_capped_content(response, 100))

    def test_accepts_a_body_at_exactly_the_limit(self):
        response = _StreamedFakeResponse([b"a" * 100])

        self.assertEqual(b"a" * 100,
                         transport.read_capped_content(response, 100))

    def test_raises_once_the_limit_is_exceeded(self):
        response = _StreamedFakeResponse([b"a" * 60, b"b" * 60])

        with self.assertRaises(transport.ResponseTooLargeError):
            transport.read_capped_content(response, 100)

    def test_does_not_read_the_whole_body_before_giving_up(self):
        # An endless response must not be buffered in full first; the
        # generator is abandoned as soon as the limit is passed.
        read = []

        def endless():
            while True:
                read.append(1)
                yield b"x" * 1024

        response = _StreamedFakeResponse([])
        response.iter_content = lambda chunk_size=None: endless()

        with self.assertRaises(transport.ResponseTooLargeError):
            transport.read_capped_content(response, 4096)
        self.assertLessEqual(len(read), 6)

    def test_uses_the_default_limit_when_none_is_given(self):
        response = _StreamedFakeResponse(
            [b"x" * (transport.MAX_COLLECTOR_RESPONSE_BYTES + 1)])

        with self.assertRaises(transport.ResponseTooLargeError):
            transport.read_capped_content(response)

    def test_stops_once_the_deadline_passes_despite_ongoing_progress(self):
        # A byte trickle just fast enough that no single chunk ever
        # exceeds the limit must still be bounded by elapsed time.
        response = _StreamedFakeResponse([b"a" * 10, b"b" * 10, b"c" * 10])
        setattr(response, transport._DEADLINE_ATTR, 5.0)
        clock = mock.Mock(side_effect=[1.0, 6.0])

        with mock.patch.object(transport.time, "monotonic", clock):
            with self.assertRaises(transport.FetchTimeoutError):
                transport.read_capped_content(response, 1000)

    def test_a_response_with_no_deadline_is_not_time_bounded(self):
        response = _StreamedFakeResponse([b"a" * 10, b"b" * 10])

        self.assertEqual(b"a" * 10 + b"b" * 10,
                         transport.read_capped_content(response, 100))


if __name__ == "__main__":
    unittest.main()
