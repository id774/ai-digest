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
#  Author: id774 (More info: http://id774.net)
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
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Pillow
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import unittest

from PIL import Image, ImageDraw, ImageFont

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


if __name__ == "__main__":
    unittest.main()
