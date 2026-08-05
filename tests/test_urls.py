#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_urls.py: Tests for the URL scheme filter and rendered links
#
#  Description:
#  This test suite covers the one rule the link filter enforces: only
#  http and https reach a page. It pins the refusal of javascript:,
#  data:, file: and vbscript:, of a relative and a protocol relative
#  path, and of a scheme given without a host.
#
#  The rendering cases close the loop at the other end. Reports written
#  before the collectors filtered links, or edited by hand, still exist
#  in the archive, so the template filter has to neutralize such a link
#  into "#" at render time rather than trusting what was stored.
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
#      python -m unittest tests.test_urls
#
#  Test Cases:
#    - Accept http and https, whatever the case of the scheme.
#    - Reject every other scheme, and a relative or protocol relative path.
#    - Reject a scheme given without a host.
#    - Replace an unsafe URL with "#" and leave a safe one alone.
#    - Keep a normal link in the rendered report.
#    - Neutralize a script link stored in a report.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Jinja2 (through the report renderer)
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import unittest

from ai_digest import Topic, is_safe_url, safe_url
from ai_digest.render import build

UNSAFE_URLS = (
    "javascript:alert(1)",
    "JavaScript:alert(1)",
    "  javascript:alert(1)  ",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "file:///etc/passwd",
    "vbscript:msgbox(1)",
    "/relative/path",
    "//example.test/protocol-relative",
    "",
)


class SafeUrlTest(unittest.TestCase):

    def test_accepts_http_and_https(self):
        self.assertTrue(is_safe_url("http://example.test/a"))
        self.assertTrue(is_safe_url("https://example.test/a"))
        self.assertTrue(is_safe_url("HTTPS://example.test/a"))

    def test_rejects_everything_else(self):
        for url in UNSAFE_URLS:
            with self.subTest(url=url):
                self.assertFalse(is_safe_url(url))

    def test_rejects_a_scheme_without_a_host(self):
        self.assertFalse(is_safe_url("http:///no-host"))

    def test_filter_replaces_an_unsafe_url(self):
        self.assertEqual("#", safe_url("javascript:alert(1)"))
        self.assertEqual("https://example.test/a",
                         safe_url("https://example.test/a"))


class RenderedLinkTest(unittest.TestCase):

    def render(self, url):
        topic = Topic(
            category="テスト",
            title="見出し",
            bullets=["本文"],
            sources=[{"title": "出典", "url": url}],
            image="topic-1.png",
        )
        return build.render_report("2026-08-02", [topic], {})

    def test_keeps_a_normal_link(self):
        html = self.render("https://example.test/article")

        self.assertIn('href="https://example.test/article"', html)

    def test_neutralizes_a_script_link_stored_in_a_report(self):
        # Reports written before the collectors filtered links, or
        # edited by hand, must not produce a clickable javascript: URL.
        html = self.render("javascript:alert(1)")

        self.assertNotIn("javascript:", html)
        self.assertIn('href="#"', html)


if __name__ == "__main__":
    unittest.main()
