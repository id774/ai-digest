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
#  v1.0 2026-09-08
#       Initial release.
#
########################################################################

from contextlib import contextmanager
from typing import Iterator
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


class HTTPSOnlyError(requests.RequestException):
    """ Report a source target that cannot be requested over HTTPS. """


def is_https_url(url: str) -> bool:
    """
    Return True when url is an absolute HTTPS URL.

    Only the scheme and the presence of a host are checked; a path, a
    query string and a port are all allowed. A non-HTTPS URL is never
    repaired into one, and surrounding whitespace is never trimmed here,
    since a caller that means to allow it already does so before this
    function is reached.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except (TypeError, ValueError):
        return False
    return parsed.scheme.lower() == "https" and bool(parsed.netloc)


@contextmanager
def https_get(url: str, timeout: int, user_agent: str,
              stream: bool = False) -> Iterator[requests.Response]:
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
        timeout: Timeout in seconds, applied to every hop.
        user_agent: User-Agent header sent with every hop.
        stream: Whether the response body is streamed rather than read.

    Yields:
        The final response, not yet read from when stream is True. It is
        closed once the caller's block exits.

    Raises:
        HTTPSOnlyError: The initial target, or a redirect target, is not
            an absolute HTTPS URL.
        requests.TooManyRedirects: The redirect chain exceeds
            MAX_REDIRECTS.
        requests.RequestException: Any other network failure.
    """
    if not is_https_url(url):
        raise HTTPSOnlyError(
            "refusing non-HTTPS request target: {0}".format(url)
        )

    with requests.Session() as session:
        current_url = url
        redirects = 0
        while True:
            response = session.get(
                current_url,
                timeout=timeout,
                stream=stream,
                headers={"User-Agent": user_agent},
                allow_redirects=False,
            )
            if response.status_code not in REDIRECT_STATUSES:
                try:
                    yield response
                finally:
                    response.close()
                return

            location = response.headers.get("Location")
            if not location:
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
