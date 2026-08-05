#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_fallback.py: Tests for wrap_text in ai_digest/images/fallback.py
#
#  Description:
#  This test suite covers the line breaking of the fallback card, whose
#  contract is that a card gets no more lines than its layout reserves
#  room for. It checks the two ways a line ends, the configured width
#  and an explicit line break, that the limit applies to both, and that
#  an ellipsis marks text the limit dropped.
#
#  The last case is the guard against an endless loop: a line always
#  accepts its first character, so a character wider than the whole
#  column still advances the wrap instead of never fitting.
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
#      python -m unittest tests.test_fallback
#
#  Test Cases:
#    - Keep text that fits the width on one line.
#    - Yield no line for empty text.
#    - Start a new line at an explicit line break.
#    - Apply the line limit to explicit line breaks as well.
#    - Add no empty line for a trailing break.
#    - Break an overflowing line and cap it at the limit.
#    - Mark dropped text with an ellipsis after a break.
#    - Drop nothing when the text fits within the limit.
#    - Advance on a character wider than the configured width.
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

from ai_digest.images.fallback import wrap_text


class WrapTextTest(unittest.TestCase):
    """ A card gets no more lines than its layout reserves room for. """

    def setUp(self):
        self.draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        # The bundled bitmap font keeps the test independent of the
        # fonts installed on the host.
        self.font = ImageFont.load_default()

    def wrap(self, text, max_width=1000, max_lines=0):
        return wrap_text(self.draw, text, self.font, max_width, max_lines)

    def test_text_within_the_width_stays_on_one_line(self):
        self.assertEqual(["abc"], self.wrap("abc"))

    def test_empty_text_yields_no_line(self):
        self.assertEqual([], self.wrap(""))

    def test_a_line_break_starts_a_new_line(self):
        self.assertEqual(["a", "b", "c"], self.wrap("a\nb\nc"))

    def test_line_breaks_honour_the_limit(self):
        wrapped = self.wrap("a\nb\nc\nd\ne", max_lines=2)

        self.assertEqual(2, len(wrapped))
        self.assertEqual("a", wrapped[0])

    def test_a_trailing_break_adds_no_empty_line(self):
        self.assertEqual(["abc"], self.wrap("abc\n"))

    def test_an_overflowing_line_is_broken_and_capped(self):
        wrapped = self.wrap("x" * 200, max_width=40, max_lines=2)

        self.assertEqual(2, len(wrapped))
        self.assertTrue(wrapped[-1].endswith("…"))

    def test_dropped_text_is_marked_after_a_break(self):
        wrapped = self.wrap("abc\ndef\nghi", max_lines=2)

        self.assertEqual(2, len(wrapped))
        self.assertTrue(wrapped[-1].endswith("…"))

    def test_nothing_is_dropped_when_the_text_fits_the_limit(self):
        wrapped = self.wrap("abc\ndef", max_lines=2)

        self.assertEqual(["abc", "def"], wrapped)

    def test_a_character_wider_than_the_width_still_advances(self):
        # Every character overflows, so the guard against an endless
        # loop is that a line always accepts its first character.
        self.assertEqual(["a", "b"], self.wrap("ab", max_width=1))


if __name__ == "__main__":
    unittest.main()
