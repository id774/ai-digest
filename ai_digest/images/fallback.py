#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/images/fallback.py: Locally generated topic cards
#
#  Description:
#  When no image can be scraped for a topic, this module draws one with
#  Pillow: a panel in the category color, the category label and the
#  Japanese headline, wrapped to the available width.
#
#  The text is Japanese, so a font with CJK glyphs is mandatory. Neither
#  the bitmap font bundled with Pillow nor DejaVuSans contains those
#  glyphs, and using them renders every character as an empty box. The
#  font is therefore resolved through config.detect_font_path(), which
#  honours AI_DIGEST_FONT_PATH and probes the usual Noto CJK locations;
#  a warning is emitted once when nothing suitable is installed.
#
#  This module also exposes the text helpers load_font(), text_size()
#  and wrap_text(), which the composite image renderer reuses.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Pillow
#  - A CJK capable TrueType font, e.g. the fonts-noto-cjk package
#
#  Version History:
#  v1.1 2026-08-04
#       Apply the line limit of wrap_text() to an explicit line break
#       as well, which returned more lines than the caller asked for.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import logging
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from ai_digest import category_color

# Default size of a generated card, matching the aspect ratio of the
# slot it occupies in the composite image.
CARD_SIZE = (800, 450)

logger = logging.getLogger(__name__)

# Emitted only once per process to keep cron logs quiet.
_font_warning_emitted = False


def load_font(font_path: Optional[str], size: int) -> ImageFont.ImageFont:
    """
    Load a TrueType font, or Pillow's bitmap font as a last resort.

    The bitmap font has no CJK glyphs and ignores the requested size,
    so the result is only legible for ASCII text. Callers cannot do
    anything about it at run time; the operator has to install a CJK
    font, which the warning explains.
    """
    global _font_warning_emitted
    if font_path:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError as error:
            logger.warning("cannot load font %s: %s", font_path, error)
    if not _font_warning_emitted:
        logger.warning(
            "no CJK font available; Japanese text will not render. "
            "Install fonts-noto-cjk or set AI_DIGEST_FONT_PATH."
        )
        _font_warning_emitted = True
    return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str,
              font: ImageFont.ImageFont) -> Tuple[int, int]:
    """ Return the pixel width and height of a single line of text. """
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    return right - left, bottom - top


def wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont,
              max_width: int, max_lines: int = 0) -> List[str]:
    """
    Wrap text to a pixel width.

    Japanese has no word separators, so wrapping is performed character
    by character; ASCII passages are still broken at a sensible place
    because a character that does not fit simply starts the next line.

    Args:
        draw: Drawing context used to measure the text.
        text: Text to wrap.
        font: Font the text is rendered with.
        max_width: Available width in pixels.
        max_lines: Maximum number of lines, 0 for unlimited. The last
            line is suffixed with an ellipsis when text is dropped.

    Returns:
        The wrapped lines.
    """
    lines: List[str] = []
    current = ""
    dropped = ""
    for position, char in enumerate(text):
        if char == "\n":
            # An explicit break ends the line wherever it stands, and
            # is consumed rather than carried over to the next one.
            lines.append(current)
            remainder = text[position + 1:]
        else:
            candidate = current + char
            if (text_size(draw, candidate, font)[0] <= max_width
                    or not current):
                current = candidate
                continue
            lines.append(current)
            remainder = text[position:]
        # The limit is checked on both paths. Counting only the lines a
        # width overflow produced let a text carrying breaks return more
        # of them than the caller reserved room for.
        if max_lines and len(lines) >= max_lines:
            dropped = remainder
            current = ""
            break
        current = "" if char == "\n" else char
    if current:
        lines.append(current)
    # Mark the truncation, unless the dropped remainder is a single
    # punctuation character that carries no information.
    if len(dropped.strip()) > 1 and lines:
        lines[-1] = lines[-1][:-1] + "…"
    return lines


def generate_card(title: str, category: str, font_path: Optional[str],
                  size: Tuple[int, int] = CARD_SIZE) -> Image.Image:
    """
    Draw a placeholder card for a topic.

    Args:
        title: Japanese headline of the topic.
        category: Category label, which also selects the color.
        font_path: Path of a CJK capable font, or None.
        size: Card size in pixels.

    Returns:
        An RGB image ready to be saved as PNG.
    """
    width, height = size
    background = category_color(category)
    image = Image.new("RGB", size, background)
    draw = ImageDraw.Draw(image)

    # Lighter band at the top carrying the category label.
    band_height = int(height * 0.18)
    draw.rectangle([(0, 0), (width, band_height)], fill="#ffffff")

    label_font = load_font(font_path, max(18, int(height * 0.055)))
    title_font = load_font(font_path, max(24, int(height * 0.085)))

    draw.text((int(width * 0.04), int(band_height * 0.3)), category,
              font=label_font, fill=background)

    margin = int(width * 0.06)
    lines = wrap_text(draw, title, title_font, width - 2 * margin, max_lines=4)
    line_height = int(text_size(draw, "あ", title_font)[1] * 1.6)
    top = band_height + int(height * 0.12)
    for offset, line in enumerate(lines):
        draw.text((margin, top + offset * line_height), line,
                  font=title_font, fill="#ffffff")

    return image
