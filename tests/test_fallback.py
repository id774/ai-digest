#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
