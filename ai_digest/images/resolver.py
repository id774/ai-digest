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
#       Refuse a page or image target that resolves to a non-public address,
#       on the initial target and every redirect hop, closing an SSRF path.
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

import ipaddress
import io
import logging
import re
import socket
from typing import List, Optional, Tuple, Union
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


def validate_public_target(url: str) -> None:
    """
    Refuse a scraping target whose host is not a public network address.

    Called on the initial target and on every redirect hop of a request
    the image resolver sends, before that request goes out, so a host
    that only turns private after a redirect is refused before the next
    request rather than after. Collectors do not use this: the arXiv
    API and the configured feeds are not subject to it, only pages and
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
    for address in _resolve_addresses(hostname):
        if not _is_public_address(address):
            raise PublicNetworkOnlyError(
                "refusing non-public request target {0}: {1} resolves to "
                "{2}".format(url, hostname, address)
            )


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
                       target_validator=validate_public_target) as response:
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
        with Image.open(io.BytesIO(content)) as image:
            image_format = (image.format or "").lower()
            width, height = image.size
    except (UnidentifiedImageError, Image.DecompressionBombError,
            OSError) as error:
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
