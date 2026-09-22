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
#  Author: id774 (More info: https://id774.net)
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
#    - Keep the standalone report from linking to an archive index its own
#      generation never writes, and from claiming an AI summarized what a
#      plain-backend run only collected and organized.
#    - Keep the Flask viewer's header linking back to the archive index.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Jinja2 (through the report renderer)
#  - Flask (through app.py, exercised by ViewerHeaderTest)
#
#  Version History:
#  v1.1 2026-09-22
#       Cover the standalone header/footer fix and the viewer's archive link.
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import importlib
import os
import sys
import unittest
from unittest import mock

import config
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


def _sample_topic():
    return Topic(
        category="テスト",
        title="見出し",
        bullets=["本文"],
        sources=[{"title": "出典", "url": "https://example.test/a"}],
        image="topic-1.png",
    )


class StandaloneHeaderTest(unittest.TestCase):
    """
    render_report() defaults to standalone=True, the mode written next
    to a report's data so its directory can be copied to any static web
    server. That directory's generation never produces an archive index
    one level up, so the standalone page must not link to one, and its
    footer must not claim an AI summarized what a plain-backend run only
    collected and organized.
    """

    def render(self):
        return build.render_report("2026-08-02", [_sample_topic()], {},
                                   standalone=True)

    def test_standalone_html_does_not_link_to_an_archive_index(self):
        html = self.render()

        self.assertNotIn("../../index.html", html)
        self.assertNotIn('<a href="../../index.html">', html)

    def test_standalone_header_is_not_a_link(self):
        html = self.render()

        self.assertIn("<h1>AI ダイジェスト</h1>", html)

    def test_footer_does_not_claim_ai_summarization(self):
        html = self.render()

        self.assertNotIn("AI により要約・分類した参考情報です", html)
        self.assertIn("本資料は公開情報を収集・整理した参考情報です", html)


class ViewerHeaderTest(unittest.TestCase):
    """
    The Flask viewer renders the same templates with standalone=False,
    where '/' is a real route, so the header link back to the archive
    index must survive unchanged.
    """

    def viewer_app(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                if "app" in sys.modules:
                    return importlib.reload(sys.modules["app"])
                return importlib.import_module("app")

    def test_viewer_header_keeps_the_archive_index_link(self):
        viewer = self.viewer_app()
        with viewer.app.test_request_context():
            html = viewer.app.jinja_env.get_template("report.html").render(
                date="2026-08-02", topics=[_sample_topic()], stats={})

        self.assertIn('<h1><a href="/">AI ダイジェスト</a></h1>', html)
        self.assertNotIn("../../index.html", html)


if __name__ == "__main__":
    unittest.main()
