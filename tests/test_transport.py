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
#  Author: id774 (More info: http://id774.net)
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
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - requests
#
#  Version History:
#  v1.0 2026-09-08
#       Initial release.
#
########################################################################

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


class InitialTargetRefusalTest(unittest.TestCase):

    def test_a_non_https_target_never_creates_a_session(self):
        with mock.patch.object(transport.requests, "Session") as session_cls:
            with self.assertRaises(transport.HTTPSOnlyError):
                with transport.https_get("http://example.test/a", 5, "ua"):
                    pass

        session_cls.assert_not_called()


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
        self.assertEqual(5, call.kwargs["timeout"])
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
            self.assertEqual(5, call.kwargs["timeout"])
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


if __name__ == "__main__":
    unittest.main()
