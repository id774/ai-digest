#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/images/resolver.py: Best effort image scraping
#
#  Description:
#  This module tries to obtain a representative image for a topic from
#  its primary source.
#
#  For arXiv papers the identifier is extracted from the URL and the
#  HTML rendering hosted at ar5iv.labs.arxiv.org is parsed; the first
#  image inside a <figure> element is used, which is normally the
#  overview figure of the paper. For news articles the Open Graph image
#  declared by <meta property="og:image"> is used.
#
#  Every step is optional. Missing pages, timeouts, unsupported formats,
#  oversized downloads and undecodable data all lead to None so that the
#  caller can generate a card instead.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - requests, beautifulsoup4, Pillow
#
#  Version History:
#  v1.4 2026-09-22
#       Pin scraping connections to the public address validated against DNS
#       rebinding, and refuse decompression-bomb-warning-range images too.
#  v1.3 2026-09-08
#       Fetch source pages and images only over HTTPS.
#  v1.2 2026-08-04
#       Treat an image refused as a decompression bomb like any other undecodable one. Pillow raises
#       that error outside OSError, so it escaped and ended the daily run instead of yielding a card.
#  v1.1 2026-08-02
#       Enforce the size limit while reading a response instead of after the
#       whole body has been buffered, and request only http and https URLs.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import contextlib
import ipaddress
import io
import logging
import re
import socket
import warnings
from typing import Iterator, List, Optional, Tuple, Union
from urllib.parse import urljoin, urlparse, urlsplit

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

from ai_digest.transport import HTTPSOnlyError, https_get

# arXiv abstract, PDF and versioned URLs all embed the same identifier.
ARXIV_ID_PATTERN = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})")

# HTML rendering of a paper, used to locate its figures.
AR5IV_URL = "https://ar5iv.labs.arxiv.org/html/{0}"

# Downloads larger than this are refused, so that a mislabeled video or
# a huge poster cannot stall the batch. The limit is applied while the
# body is being read, because a remote host is free to announce one
# size and send another, or to stream without ever announcing one.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# Same limit for the pages parsed to find an image. They are ordinary
# article pages, so this is generous.
MAX_PAGE_BYTES = 4 * 1024 * 1024

# Size of the chunks read from a response body.
CHUNK_BYTES = 64 * 1024

# Images smaller than this in either dimension are usually logos,
# tracking pixels or social badges rather than illustrations.
MIN_IMAGE_SIDE = 200

logger = logging.getLogger(__name__)


class PublicNetworkOnlyError(HTTPSOnlyError):
    """
    Report a scraping target that is HTTPS but not a public network host.

    A subclass of HTTPSOnlyError, not a sibling: every place that
    already treats HTTPS-only refusal as an ordinary failed fetch treats
    this the same way, without a second except clause of its own.
    """


IPAddress = Union[ipaddress.IPv4Address, ipaddress.IPv6Address]


def _is_public_address(address: IPAddress) -> bool:
    """
    Return True for an address reachable on the public Internet.

    ipaddress' own is_global is not enough on its own: it excludes
    loopback, private, link-local, unspecified and reserved ranges, but
    not multicast, which is_global still reports as global for both
    IPv4 and IPv6.
    """
    return address.is_global and not address.is_multicast


def _resolve_addresses(hostname: str) -> List[IPAddress]:
    """
    Return every IP address a scraping target's host resolves to.

    A literal IP address is used as is. A DNS name is resolved through
    getaddrinfo(), the same resolver requests/urllib3 uses to actually
    connect, so the addresses checked are the ones a request would
    reach; every address a name resolves to is returned, since a host
    that answers with a public address and a private one is only as
    safe as its worst answer.

    Raises:
        PublicNetworkOnlyError: DNS resolution failed. This is treated
            as an image resolution failure by the caller, the same as
            an unreachable host, never as a batch failure.
    """
    try:
        return [ipaddress.ip_address(hostname)]
    except ValueError:
        pass
    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as error:
        raise PublicNetworkOnlyError(
            "name resolution failed for {0}: {1}".format(hostname, error)
        )
    return [ipaddress.ip_address(info[4][0]) for info in resolved]


def _pinned_getaddrinfo(hostname: str, addresses: List[IPAddress],
                        real_getaddrinfo):
    """
    Return a getaddrinfo() replacement answering only from addresses.

    A call naming any other host is passed through to the real resolver
    unchanged; a call naming hostname can only ever get back one of the
    addresses already checked as public, whatever a name server would
    answer for it at that moment.
    """
    def _getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
        if host != hostname or type not in (0, socket.SOCK_STREAM):
            return real_getaddrinfo(host, port, family, type, proto, flags)
        results = []
        for address in addresses:
            addr_family = (socket.AF_INET6 if address.version == 6
                          else socket.AF_INET)
            if family not in (0, addr_family):
                continue
            sockaddr = ((str(address), port, 0, 0) if address.version == 6
                       else (str(address), port))
            results.append((addr_family, socket.SOCK_STREAM,
                            socket.IPPROTO_TCP, "", sockaddr))
        if not results:
            raise socket.gaierror(
                "no pinned address for {0} matches the requested family"
                .format(host)
            )
        return results

    return _getaddrinfo


@contextlib.contextmanager
def validate_and_pin_public_target(url: str) -> Iterator[None]:
    """
    Refuse a non-public scraping target, and pin the wrapped request's
    DNS resolution to exactly the addresses just checked.

    A preflight lookup and the lookup made when a connection is actually
    opened are two separate DNS resolutions; a host that answers the
    first with a public address and the second with a private one - DNS
    rebinding - would otherwise let a validated hostname's connection
    reach a private target anyway. Pinning closes that gap: for the life
    of the wrapped request, a lookup of this exact hostname can only
    return an address this function already checked, so the address
    connected to is provably one of the addresses validated. The
    original hostname still decides TLS SNI, certificate validation and
    the Host header; only which address the connection reaches is
    fixed, and it is never a non-public one, whatever a name server
    answers meanwhile.

    Called on the initial target and on every redirect hop of a request
    the image resolver sends. Collectors do not use this: the arXiv API
    and the configured feeds are not subject to it, only pages and
    images the resolver scrapes from source URLs it does not control.

    Raises:
        PublicNetworkOnlyError: The host is missing, resolves to a
            loopback, private, link-local, unspecified, multicast or
            otherwise non-global address, or fails to resolve at all.
    """
    hostname = urlsplit(url).hostname
    if not hostname:
        raise PublicNetworkOnlyError(
            "refusing request with no host: {0}".format(url)
        )
    addresses = _resolve_addresses(hostname)
    for address in addresses:
        if not _is_public_address(address):
            raise PublicNetworkOnlyError(
                "refusing non-public request target {0}: {1} resolves to "
                "{2}".format(url, hostname, address)
            )

    real_getaddrinfo = socket.getaddrinfo
    socket.getaddrinfo = _pinned_getaddrinfo(hostname, addresses,
                                             real_getaddrinfo)
    try:
        yield
    finally:
        socket.getaddrinfo = real_getaddrinfo


def _read_capped(response: requests.Response, limit: int) -> Optional[bytes]:
    """
    Read a response body, giving up once it exceeds limit bytes.

    Returning None rather than the truncated bytes is deliberate: a
    partial image is not worth publishing, and stopping the read is
    what keeps an oversized or endless body out of memory.
    """
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch(url: str, timeout: int, user_agent: str,
           limit: int) -> Optional[Tuple[bytes, str]]:
    """
    Fetch a URL, reading at most limit bytes of its body.

    Returns the body together with the URL the response came from, so
    that relative links can be resolved against it, or None on any
    failure. Only HTTPS is requested, and a redirect to a downgraded
    target is refused before it is followed: the candidate URLs come
    from third party pages, and no other scheme or protocol has a
    meaning here.
    """
    try:
        with https_get(url, timeout, user_agent, stream=True,
                       target_pin=validate_and_pin_public_target) as response:
            response.raise_for_status()
            body = _read_capped(response, limit)
            if body is None:
                logger.info("response larger than %d bytes, skipped: %s",
                            limit, url)
                return None
            return body, response.url
    except HTTPSOnlyError as error:
        logger.info("refusing image source %s: %s", url, error)
        return None
    except requests.RequestException as error:
        logger.info("image source unreachable %s: %s", url, error)
        return None


def _download_image(url: str, timeout: int,
                    user_agent: str) -> Optional[Tuple[bytes, str]]:
    """
    Download and validate an image.

    Returns the raw bytes together with a lower case file extension, or
    None when the resource is not a usable raster image.
    """
    fetched = _fetch(url, timeout, user_agent, MAX_IMAGE_BYTES)
    if fetched is None:
        return None
    content, _final_url = fetched
    try:
        # Scoped to this one decode: Pillow only warns, rather than
        # raising, below twice MAX_IMAGE_PIXELS, and simplefilter() here
        # is undone by catch_warnings() on exit, so it never touches the
        # process-wide warning filter other code relies on.
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                image_format = (image.format or "").lower()
                width, height = image.size
    except (UnidentifiedImageError, Image.DecompressionBombError,
            Image.DecompressionBombWarning, OSError) as error:
        # A picture whose pixel count would exhaust the memory of the
        # host compresses to far less than MAX_IMAGE_BYTES, so the byte
        # limit does not catch it and Pillow refuses it here. That error
        # derives from Exception rather than from OSError, so it has to
        # be named: unnamed, it left the module and ended the batch.
        logger.info("undecodable image %s: %s", url, error)
        return None
    if width < MIN_IMAGE_SIDE or height < MIN_IMAGE_SIDE:
        logger.info("image too small, skipped: %s", url)
        return None
    extension = {"jpeg": "jpg"}.get(image_format, image_format)
    if extension not in ("jpg", "png", "gif", "webp"):
        logger.info("unsupported image format %s: %s", image_format, url)
        return None
    return content, extension


def arxiv_figure_url(url: str, timeout: int, user_agent: str) -> Optional[str]:
    """
    Return the URL of the first figure of an arXiv paper.

    None is returned when the URL is not an arXiv link, when ar5iv has
    no HTML rendering of the paper, or when the rendering contains no
    figure.
    """
    match = ARXIV_ID_PATTERN.search(url)
    if match is None:
        return None
    page_url = AR5IV_URL.format(match.group(1))
    fetched = _fetch(page_url, timeout, user_agent, MAX_PAGE_BYTES)
    if fetched is None:
        return None
    body, final_url = fetched
    soup = BeautifulSoup(body, "html.parser")
    for figure in soup.find_all("figure"):
        image = figure.find("img")
        if image is not None and image.get("src"):
            return urljoin(final_url, image["src"])
    return None


def open_graph_image_url(url: str, timeout: int,
                         user_agent: str) -> Optional[str]:
    """
    Return the Open Graph image declared by an article page.

    The twitter:image meta tag is accepted as a second choice, since
    several publishers only provide that one.
    """
    fetched = _fetch(url, timeout, user_agent, MAX_PAGE_BYTES)
    if fetched is None:
        return None
    body, final_url = fetched
    soup = BeautifulSoup(body, "html.parser")
    for attribute, name in (("property", "og:image"),
                            ("name", "twitter:image")):
        tag = soup.find("meta", attrs={attribute: name})
        if tag is not None and tag.get("content"):
            return urljoin(final_url, tag["content"])
    return None


def resolve(source_url: str, timeout: int = 15,
            user_agent: str = "ai-digest") -> Optional[Tuple[bytes, str, str]]:
    """
    Try to fetch an illustration for one source URL.

    Args:
        source_url: Canonical URL of the paper or article.
        timeout: HTTP timeout in seconds.
        user_agent: User-Agent header sent to the remote hosts.

    Returns:
        A tuple of (image bytes, file extension, credit label), or None
        when no usable image could be retrieved.
    """
    if not source_url:
        return None

    candidate = arxiv_figure_url(source_url, timeout, user_agent)
    if candidate is None:
        candidate = open_graph_image_url(source_url, timeout, user_agent)
    if candidate is None:
        return None

    downloaded = _download_image(candidate, timeout, user_agent)
    if downloaded is None:
        return None

    content, extension = downloaded
    return content, extension, urlparse(candidate).netloc
