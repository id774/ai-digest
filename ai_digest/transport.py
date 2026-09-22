#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/transport.py: HTTPS-only retrieval and redirect boundary
#
#  Description:
#  This module is the single shared entry point every collector and the
#  image resolver use to reach a public source: the arXiv API, a
#  configured RSS or Atom feed, a scraped article page, and a candidate
#  image. It refuses a request whose initial target is not an absolute
#  HTTPS URL, and it inspects every redirect target itself, following
#  automatic redirects turned off, so that a redirect chain can never
#  send a plaintext request on the caller's behalf.
#
#  Published citations are a separate concern: a report may still carry
#  an ordinary absolute http or https link, and rendering it is the
#  business of ai_digest.is_safe_url() and ai_digest.safe_url(), which
#  this module does not touch.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - requests
#
#  Version History:
#  v1.1 2026-09-22
#       Add target_pin, trust_env and a fetch-wide elapsed deadline, and
#       validate HTTPS URLs by hostname and port, not just netloc presence.
#  v1.0 2026-09-08
#       Initial release.
#
########################################################################

import time
from contextlib import contextmanager, nullcontext
from typing import Callable, ContextManager, Iterator, Optional
from urllib.parse import urljoin, urlparse

import requests

# Redirect status codes handled by https_get() itself, since automatic
# redirect following is turned off so that every hop can be inspected
# before the next request is sent.
REDIRECT_STATUSES = (301, 302, 303, 307, 308)

# Upper bound of redirect hops in one call, matching the scale of the
# bound Requests itself applies when it follows redirects automatically.
# A fixed internal constant, not a configuration setting.
MAX_REDIRECTS = 30

# Default limit of read_capped_content(), used by the arXiv and news
# feed collectors. A fixed internal constant, not a configuration
# setting: the image resolver reads under its own, tighter limits and
# does not use this one.
MAX_COLLECTOR_RESPONSE_BYTES = 8 * 1024 * 1024

# Size of the chunks read.iter_content() draws content in.
_READ_CHUNK_BYTES = 64 * 1024


class HTTPSOnlyError(requests.RequestException):
    """ Report a source target that cannot be requested over HTTPS. """


class ResponseTooLargeError(requests.RequestException):
    """ Report a response body larger than read_capped_content()'s limit. """


class FetchTimeoutError(requests.RequestException):
    """ Report a fetch whose total elapsed time exceeded its deadline. """


# Attribute name https_get() uses to hand its per-hop deadline to a body
# reader called on the response it yielded, so header wait and body
# streaming share one fetch-wide budget instead of each getting their
# own. Not part of the public interface of either function.
_DEADLINE_ATTR = "_ai_digest_fetch_deadline"


def fetch_deadline(response: requests.Response) -> Optional[float]:
    """
    Return the monotonic deadline of the fetch response came from.

    None when response was not obtained through https_get(), so a
    caller reading a response from elsewhere degrades to no deadline
    rather than failing.
    """
    return getattr(response, _DEADLINE_ATTR, None)


def read_capped_content(response: requests.Response,
                        limit: int = MAX_COLLECTOR_RESPONSE_BYTES) -> bytes:
    """
    Read a streamed response body, refusing to buffer past limit bytes
    or past the fetch's own deadline, whichever comes first.

    Reading in chunks and counting as they arrive is what keeps an
    oversized or endless body from ever being fully buffered in the
    first place; the response's own Content-Length, sent or not, is
    never the only thing trusted. The caller must have requested the
    response with stream=True, or the body is already read in full by
    the time this function sees it.

    A response from https_get() carries the monotonic deadline of the
    fetch it came from. Bytes trickling in just fast enough that no
    single socket read times out could otherwise stretch one fetch far
    past its configured budget; checking elapsed time between chunks,
    regardless of whether they keep arriving, is what actually bounds
    the total.

    Raises:
        ResponseTooLargeError: More than limit bytes were read. A
            source this large is treated as a source-local failure by
            the caller, never as partial content to parse.
        FetchTimeoutError: The fetch's deadline passed while reading.
            Treated the same as any other request timeout.
    """
    deadline = fetch_deadline(response)
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=_READ_CHUNK_BYTES):
        if deadline is not None and time.monotonic() > deadline:
            raise FetchTimeoutError(
                "response body still incomplete after the fetch's "
                "deadline elapsed"
            )
        total += len(chunk)
        if total > limit:
            raise ResponseTooLargeError(
                "response exceeded {0} bytes".format(limit)
            )
        chunks.append(chunk)
    return b"".join(chunks)


def is_https_url(url: str) -> bool:
    """
    Return True when url is a requestable absolute HTTPS URL.

    The scheme must be https and a hostname must actually be present:
    `netloc` alone is not enough, since 'https://:8080/x' and
    'https://user:pass@/x' both carry a nonempty netloc with no host. An
    explicit port must be syntactically valid, which urlparse defers
    until `.port` is read. A path and a query string are always allowed.
    A non-HTTPS URL is never repaired into one, and surrounding
    whitespace is never trimmed here, since a caller that means to allow
    it already does so before this function is reached.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except (TypeError, ValueError):
        return False
    if parsed.scheme.lower() != "https" or not parsed.hostname:
        return False
    try:
        parsed.port
    except ValueError:
        return False
    return True


@contextmanager
def https_get(url: str, timeout: int, user_agent: str,
              stream: bool = False,
              target_pin: Optional[Callable[[str], ContextManager[None]]]
              = None, trust_env: bool = True) -> Iterator[requests.Response]:
    """
    Request url over HTTPS, inspecting every redirect before following it.

    This is the one place that actually opens a network connection for
    source collection and illustration scraping. The initial target must
    already be an absolute HTTPS URL; automatic redirect following is
    turned off, and each redirect target is validated as HTTPS in turn
    before the next request is sent, so a downgrade to plaintext is
    refused rather than followed.

    Args:
        url: Initial request target.
        timeout: Budget, in seconds, for the whole fetch - the initial
            request, every redirect hop, and the body of the response
            finally yielded - not a per-hop allowance: each hop is given
            only what remains of it, so a redirect chain can never add
            up to more than timeout seconds total. A body read through
            read_capped_content() shares the same deadline.
        user_agent: User-Agent header sent with every hop.
        stream: Whether the response body is streamed rather than read.
        target_pin: Optional context manager factory wrapping the actual
            request for the initial target and for every redirect
            target, after the HTTPS check passes. Entering it may raise
            to refuse a target this function's own HTTPS check would
            accept, and may also pin how the wrapped request resolves
            its host, so validating a URL string and connecting to the
            address that validation checked stay one atomic step. The
            image resolver uses it to keep a public-network-only policy,
            pinned against DNS rebinding, without imposing either on
            every other caller of this function.
        trust_env: Whether the Session reads proxy settings (and other
            environment-driven defaults, such as .netrc) from the
            process environment, the same thing requests.Session.
            trust_env controls. Collectors leave this True, so an
            operator's configured proxy still carries the arXiv API and
            feed requests it always has. The image resolver passes
            False: a proxy sitting between it and a target_pin-validated
            address could otherwise resolve and route the connection
            itself, which would make the pinning guarantee meaningless.

    Yields:
        The final response, not yet read from when stream is True. It is
        closed once the caller's block exits.

    Raises:
        HTTPSOnlyError: The initial target, or a redirect target, is not
            an absolute HTTPS URL.
        requests.TooManyRedirects: The redirect chain exceeds
            MAX_REDIRECTS.
        FetchTimeoutError: No time was left of the fetch's budget before
            a hop's request could be sent.
        requests.RequestException: Any other network failure, including
            one raised by target_pin.
    """
    if not is_https_url(url):
        raise HTTPSOnlyError(
            "refusing non-HTTPS request target: {0}".format(url)
        )

    pin = target_pin if target_pin is not None else (lambda _url: nullcontext())
    deadline = time.monotonic() + timeout

    with requests.Session() as session:
        session.trust_env = trust_env
        current_url = url
        redirects = 0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise FetchTimeoutError(
                    "fetch deadline of {0}s elapsed before requesting "
                    "{1}".format(timeout, current_url)
                )
            with pin(current_url):
                response = session.get(
                    current_url,
                    timeout=remaining,
                    stream=stream,
                    headers={"User-Agent": user_agent},
                    allow_redirects=False,
                )
            if response.status_code not in REDIRECT_STATUSES:
                setattr(response, _DEADLINE_ATTR, deadline)
                try:
                    yield response
                finally:
                    response.close()
                return

            location = response.headers.get("Location")
            if not location:
                setattr(response, _DEADLINE_ATTR, deadline)
                try:
                    yield response
                finally:
                    response.close()
                return

            if redirects >= MAX_REDIRECTS:
                response.close()
                raise requests.TooManyRedirects(
                    "exceeded {0} redirects: {1}".format(
                        MAX_REDIRECTS, url)
                )

            try:
                next_url = urljoin(response.url or current_url, location)
            except ValueError:
                response.close()
                raise HTTPSOnlyError(
                    "malformed redirect target from {0}: {1}".format(
                        current_url, location)
                )

            if not is_https_url(next_url):
                response.close()
                raise HTTPSOnlyError(
                    "refusing non-HTTPS redirect target: {0}".format(
                        next_url)
                )

            response.close()
            current_url = next_url
            redirects += 1
