#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_compose_image.py: Tests for the legend of the daily image
#
#  Description:
#  This test suite covers the legend row of the composite daily image.
#  The legend keeps the categories of the leading topics, and it has to
#  fit a fixed width: the cases below pin the order it keeps, the
#  trailing entries it drops when the row is too narrow, and the cap on
#  how many entries it lists however wide the row is.
#
#  The tests draw on the bundled bitmap font rather than an installed
#  one, so that only relative widths matter and the result does not
#  depend on the fonts of the host.
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
#      python -m unittest tests.test_compose_image
#
#  Test Cases:
#    - Keep every category, in order, on a row wide enough for them.
#    - Drop the trailing categories on a row that is too narrow.
#    - Keep nothing on a row without room for a single entry.
#    - Yield no entry when there is no category.
#    - Cap the listed categories at LEGEND_MAX_ENTRIES.
#    - Use backend-neutral fixed wording in the daily image.
#    - Label データソース from what topics actually cite: arXiv only, news
#      only, both, or neither.
#    - Refuse a decompression-bomb stored illustration without raising,
#      leaving the canvas untouched, and still paste an ordinary one.
#    - Accept lookback_hours=None, for a demo report, without raising.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Pillow
#
#  Version History:
#  v1.2 2026-09-22
#       Cover the dynamic データソース label, the stored-illustration
#       decompression bomb guard, and a None (demo) lookback_hours.
#  v1.1 2026-08-24
#       Pin the backend-neutral fixed text of the daily summary image.
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import os
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFont

from ai_digest import Topic
from ai_digest.render import compose_image


class LegendEntriesTest(unittest.TestCase):
    """ The legend keeps the categories of the leading topics. """

    def setUp(self):
        self.draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        # The bundled bitmap font keeps the test independent of the
        # fonts installed on the host; only relative widths matter here.
        self.font = ImageFont.load_default()

    def entries(self, categories, available):
        return compose_image._legend_entries(self.draw, categories,
                                             self.font, available, 0)

    def widths(self, categories):
        return [width for _name, width in self.entries(categories, 100000)]

    def test_a_wide_enough_row_keeps_every_category_in_order(self):
        categories = ["基盤モデル", "推論効率", "評価"]

        kept = [name for name, _width in self.entries(categories, 100000)]

        self.assertEqual(categories, kept)

    def test_a_narrow_row_drops_the_trailing_categories(self):
        categories = ["基盤モデル", "推論効率", "評価", "安全性"]
        # Room for the first two entries and nothing more.
        available = sum(self.widths(categories)[:2])

        kept = [name for name, _width in self.entries(categories, available)]

        self.assertEqual(categories[:2], kept)

    def test_a_row_without_room_keeps_nothing(self):
        self.assertEqual([], self.entries(["基盤モデル"], 0))

    def test_no_category_yields_no_entry(self):
        self.assertEqual([], self.entries([], 100000))

    def test_the_listed_categories_are_capped(self):
        categories = ["分類{0}".format(index) for index in range(10)]

        kept = self.entries(categories, 100000)

        self.assertEqual(compose_image.LEGEND_MAX_ENTRIES, len(kept))


class SummaryTextTest(unittest.TestCase):
    """ The fixed summary text is correct for every backend. """

    def test_fixed_summary_text_is_backend_neutral(self):
        self.assertEqual(
            "過去 {0} 時間の AI 関連論文・ニュースを収集・整理",
            compose_image.HEADER_SUBTITLE,
        )
        self.assertIn(
            ("整理方法", "公開情報の収集・整理"),
            compose_image.FOOTER_STATIC_ITEMS,
        )
        self.assertEqual(
            "留意事項: 本資料は公開情報を収集・整理した参考情報です。"
            "重要な判断に際しては、原典となる一次情報を確認してください。",
            compose_image.DISCLAIMER,
        )


class DataSourceLabelTest(unittest.TestCase):
    """
    データソース names what the report's topics actually cite, not a
    fixed string, so an arXiv-only or news-only report is not described
    as drawing from both.
    """

    def topic(self, urls):
        return Topic(category="c", title="t", bullets=["b"],
                    sources=[{"title": "s", "url": url} for url in urls])

    def test_arxiv_only(self):
        topics = [self.topic(["https://arxiv.org/abs/1"])]

        self.assertEqual(compose_image.DATA_SOURCE_ARXIV,
                         compose_image._data_source_label(topics))

    def test_an_arxiv_subdomain_still_counts_as_arxiv(self):
        topics = [self.topic(["https://export.arxiv.org/abs/1"])]

        self.assertEqual(compose_image.DATA_SOURCE_ARXIV,
                         compose_image._data_source_label(topics))

    def test_news_only(self):
        topics = [self.topic(["https://example.test/article"])]

        self.assertEqual(compose_image.DATA_SOURCE_NEWS,
                         compose_image._data_source_label(topics))

    def test_mixed_sources(self):
        topics = [self.topic(["https://arxiv.org/abs/1",
                              "https://example.test/article"])]

        self.assertEqual(compose_image.DATA_SOURCE_BOTH,
                         compose_image._data_source_label(topics))

    def test_no_usable_source(self):
        topics = [self.topic([])]

        self.assertEqual(compose_image.DATA_SOURCE_NONE,
                         compose_image._data_source_label(topics))


class PasteIllustrationTest(unittest.TestCase):
    """
    A stored topic illustration gets the same decompression bomb guard
    the resolver applies when it first scrapes an image, so a rebuild
    cannot be made to decode a hostile file just because it already
    passed the resolver's own byte cap once.
    """

    def test_refuses_a_decompression_bomb_without_raising(self):
        side = int((1.5 * Image.MAX_IMAGE_PIXELS) ** 0.5) + 10
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "big.png")
            Image.new("L", (side, side)).save(path, format="PNG")

            canvas = Image.new("RGB", (100, 100), "white")
            with self.assertLogs(compose_image.logger, "WARNING"):
                compose_image._paste_illustration(canvas, path,
                                                  (0, 0, 100, 100))

            # Refused, not pasted: the canvas is untouched.
            self.assertEqual((255, 255, 255), canvas.getpixel((50, 50)))

    def test_pastes_an_ordinary_image(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "ok.png")
            Image.new("RGB", (40, 40), (10, 20, 30)).save(path, format="PNG")

            canvas = Image.new("RGB", (100, 100), "white")
            compose_image._paste_illustration(canvas, path, (0, 0, 100, 100))

            self.assertEqual((10, 20, 30), canvas.getpixel((50, 50)))


class DemoPeriodRenderTest(unittest.TestCase):
    """
    compose() accepts lookback_hours=None for a demo report, showing a
    sample period rather than formatting None into the hour count.
    """

    def topic(self):
        return Topic(category="c", title="t", bullets=["b1", "b2"],
                    sources=[{"title": "s", "url": "https://arxiv.org/abs/1"}])

    def test_a_none_lookback_does_not_raise(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = compose_image.compose(
                "2026-08-04", [self.topic()], directory, lookback_hours=None)

            self.assertTrue(os.path.isfile(output_path))


if __name__ == "__main__":
    unittest.main()
