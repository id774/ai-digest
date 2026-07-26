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
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - requests, beautifulsoup4, Pillow
#
#  Version History:
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import io
import logging
import re
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, UnidentifiedImageError

# arXiv abstract, PDF and versioned URLs all embed the same identifier.
ARXIV_ID_PATTERN = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})")

# HTML rendering of a paper, used to locate its figures.
AR5IV_URL = "https://ar5iv.labs.arxiv.org/html/{0}"

# Downloads larger than this are refused, so that a mislabeled video or
# a huge poster cannot stall the batch.
MAX_IMAGE_BYTES = 8 * 1024 * 1024

# Images smaller than this in either dimension are usually logos,
# tracking pixels or social badges rather than illustrations.
MIN_IMAGE_SIDE = 200

logger = logging.getLogger(__name__)


def _get(url: str, timeout: int, user_agent: str) -> Optional[requests.Response]:
    """ Perform a GET request, returning None on any failure. """
    try:
        response = requests.get(
            url, timeout=timeout, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
        return response
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
    response = _get(url, timeout, user_agent)
    if response is None:
        return None
    content = response.content
    if len(content) > MAX_IMAGE_BYTES:
        logger.info("image too large, skipped: %s", url)
        return None
    try:
        with Image.open(io.BytesIO(content)) as image:
            image_format = (image.format or "").lower()
            width, height = image.size
    except (UnidentifiedImageError, OSError) as error:
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
    response = _get(page_url, timeout, user_agent)
    if response is None:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    for figure in soup.find_all("figure"):
        image = figure.find("img")
        if image is not None and image.get("src"):
            return urljoin(response.url, image["src"])
    return None


def open_graph_image_url(url: str, timeout: int,
                         user_agent: str) -> Optional[str]:
    """
    Return the Open Graph image declared by an article page.

    The twitter:image meta tag is accepted as a second choice, since
    several publishers only provide that one.
    """
    response = _get(url, timeout, user_agent)
    if response is None:
        return None
    soup = BeautifulSoup(response.text, "html.parser")
    for attribute, name in (("property", "og:image"),
                            ("name", "twitter:image")):
        tag = soup.find("meta", attrs={attribute: name})
        if tag is not None and tag.get("content"):
            return urljoin(response.url, tag["content"])
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
