#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/render/compose_image.py: Daily summary image
#
#  Description:
#  This module draws the single PNG that summarizes a day of AI news and
#  papers. The layout follows the infographic style requested for the
#  project:
#
#      - header with the report date, a one line description of the
#        scope and a label in the upper right corner
#      - legend mapping every category of the day to its color
#      - grid of numbered cards, each with a headline, an illustration,
#        the Japanese bullet points and the URL of the primary source
#      - footer with the metadata of the run and a disclaimer
#
#  The image is composed directly with Pillow instead of screenshotting
#  an HTML page with a headless browser. That keeps the runtime
#  dependencies light, at the cost of a layout that has to be computed
#  here rather than by a CSS engine.
#
#  All rendered text is Japanese, so a CJK capable font is required; see
#  ai_digest.images.fallback for how the font is resolved.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Pillow
#
#  Version History:
#  v1.2 2026-08-04
#       Choose the legend entries before drawing them, so that a row
#       too narrow for every category drops the trailing ones instead
#       of the leading, most important ones.
#  v1.1 2026-08-03
#       Name the configured look back window in the header and the
#       footer instead of always announcing 24 hours.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import logging
import os
import re
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw

from ai_digest import Topic, category_color
from ai_digest.images.fallback import load_font, text_size, wrap_text

# Canvas geometry. The canvas is fixed so that every daily image has the
# same proportions and can be posted or archived without rescaling.
CANVAS_WIDTH = 1536
CANVAS_HEIGHT = 1024
MARGIN = 24
HEADER_HEIGHT = 118
FOOTER_HEIGHT = 96
CARD_GAP = 18
GRID_COLUMNS = 3

# Colors of the surrounding chrome.
BACKGROUND_COLOR = "#e8ecf1"
CARD_COLOR = "#ffffff"
BORDER_COLOR = "#c7d0da"
TEXT_COLOR = "#1a1a1a"
SUBTEXT_COLOR = "#4a5560"

LABEL_TEXT = "AI DIGEST"
HEADER_SUBTITLE = "過去 {0} 時間の AI 関連論文・ニュースを AI により要約・分類"
PERIOD_TEXT = "過去 {0} 時間"
FOOTER_ITEMS = (
    ("データソース", "arXiv・公開ニュース"),
    ("対象期間", PERIOD_TEXT),
    ("分析手法", "AI による要約・分類"),
    ("目的", "研究・技術動向の把握"),
)
DISCLAIMER = (
    "留意事項: 本資料は公開情報を AI により要約・分類した参考情報です。"
    "重要な判断に際しては、原典となる一次情報を確認してください。"
)

# Look back window announced when the caller does not say which one the
# collectors used. It matches LOOKBACK_HOURS in config.py.
DEFAULT_LOOKBACK_HOURS = 24

# Height of the strip at the bottom of a card that carries the source
# URL, so that a reader can reach the original material from the image
# alone.
SOURCE_STRIP_HEIGHT = 26

# Categories the legend lists at most, and the space one entry needs
# beyond its label for the color swatch and the gap after it.
LEGEND_MAX_ENTRIES = 6
LEGEND_ENTRY_PADDING = 44

logger = logging.getLogger(__name__)


def _display_url(url: str) -> str:
    """
    Return the URL as shown on a card.

    The scheme and a leading 'www.' carry no information at this size
    and are dropped, and a trailing slash is removed. Truncation to the
    available width is left to the caller, which knows the font.
    """
    shortened = re.sub(r"^https?://(www\.)?", "", url.strip())
    return shortened.rstrip("/")


def _legend_entries(draw: ImageDraw.ImageDraw, categories: List[str],
                    font, right: int,
                    left_limit: int) -> List[Tuple[str, int]]:
    """
    Return the legend entries that fit, each with its width.

    The row is right aligned, so which entries fit has to be decided
    before the first one is drawn. Laying them out from the right and
    stopping once the row is full drops the leading categories, and
    those belong to the most important topics of the day, so the
    trailing ones are removed instead.
    """
    shown = list(categories[:LEGEND_MAX_ENTRIES])
    widths = [text_size(draw, name, font)[0] + LEGEND_ENTRY_PADDING
              for name in shown]
    while shown and right - sum(widths) < left_limit:
        shown.pop()
        widths.pop()
    return list(zip(shown, widths))


def _draw_header(draw: ImageDraw.ImageDraw, date: str,
                 topics: List[Topic], font_path: Optional[str],
                 lookback_hours: int) -> None:
    """ Draw the title, the subtitle and the category legend. """
    title_font = load_font(font_path, 40)
    subtitle_font = load_font(font_path, 18)
    legend_font = load_font(font_path, 17)
    label_font = load_font(font_path, 22)

    year, month, day = date.split("-")
    title = "{0}年{1}月{2}日 AI ダイジェスト".format(year, month, day)
    draw.text((MARGIN, MARGIN - 4), title, font=title_font, fill=TEXT_COLOR)
    subtitle = HEADER_SUBTITLE.format(lookback_hours)
    draw.text((MARGIN, MARGIN + 48), subtitle, font=subtitle_font,
              fill=SUBTEXT_COLOR)
    subtitle_end = MARGIN + text_size(draw, subtitle, subtitle_font)[0]

    # Label badge in the upper right corner.
    label_width, label_height = text_size(draw, LABEL_TEXT, label_font)
    badge_right = CANVAS_WIDTH - MARGIN
    badge_left = badge_right - label_width - 28
    draw.rectangle([(badge_left, MARGIN - 6),
                    (badge_right, MARGIN + label_height + 12)],
                   fill="#12181f")
    draw.text((badge_left + 14, MARGIN + 1), LABEL_TEXT, font=label_font,
              fill="#ffffff")

    # Legend listing every distinct category, right aligned below the
    # badge so that it never collides with the title.
    categories: List[str] = []
    for topic in topics:
        if topic.category not in categories:
            categories.append(topic.category)

    # Entries are drawn right to left and stop before the subtitle, so
    # a day with many categories drops the least important ones instead
    # of overprinting the text on its left.
    cursor = badge_right
    for category, width in reversed(_legend_entries(
            draw, categories, legend_font, badge_right, subtitle_end + 24)):
        cursor -= width
        draw.rectangle([(cursor, MARGIN + 54), (cursor + 16, MARGIN + 70)],
                       fill=category_color(category))
        draw.text((cursor + 24, MARGIN + 52), category, font=legend_font,
                  fill=SUBTEXT_COLOR)


def _draw_footer(draw: ImageDraw.ImageDraw, font_path: Optional[str],
                 lookback_hours: int) -> None:
    """ Draw the metadata strip and the disclaimer. """
    label_font = load_font(font_path, 16)
    value_font = load_font(font_path, 18)
    note_font = load_font(font_path, 14)

    top = CANVAS_HEIGHT - FOOTER_HEIGHT
    draw.rectangle([(MARGIN, top), (CANVAS_WIDTH - MARGIN, top + 58)],
                   fill=CARD_COLOR, outline=BORDER_COLOR)

    column_width = (CANVAS_WIDTH - 2 * MARGIN) // len(FOOTER_ITEMS)
    for index, (label, value) in enumerate(FOOTER_ITEMS):
        left = MARGIN + index * column_width + 20
        draw.text((left, top + 8), label, font=label_font, fill=SUBTEXT_COLOR)
        # Only the period carries a placeholder; the others format to
        # themselves.
        draw.text((left, top + 30), value.format(lookback_hours),
                  font=value_font, fill=TEXT_COLOR)
        if index > 0:
            divider = MARGIN + index * column_width
            draw.line([(divider, top + 8), (divider, top + 50)],
                      fill=BORDER_COLOR)

    draw.text((MARGIN, top + 68), DISCLAIMER, font=note_font,
              fill=SUBTEXT_COLOR)


def _paste_illustration(canvas: Image.Image, path: str, box) -> None:
    """
    Paste a topic illustration, cropped to fill the given box.

    The aspect ratio is preserved and the overflowing part is cut, which
    keeps the grid regular whatever the shape of the scraped image.
    """
    left, top, right, bottom = box
    target_width = right - left
    target_height = bottom - top
    try:
        with Image.open(path) as source:
            image = source.convert("RGB")
            scale = max(target_width / image.width,
                        target_height / image.height)
            resized = image.resize(
                (max(1, int(image.width * scale)),
                 max(1, int(image.height * scale))),
                Image.LANCZOS,
            )
            offset_x = (resized.width - target_width) // 2
            offset_y = (resized.height - target_height) // 2
            cropped = resized.crop((offset_x, offset_y,
                                    offset_x + target_width,
                                    offset_y + target_height))
            canvas.paste(cropped, (left, top))
    except (OSError, ValueError) as error:
        logger.warning("cannot paste illustration %s: %s", path, error)


def _draw_card(canvas: Image.Image, draw: ImageDraw.ImageDraw, topic: Topic,
               number: int, box, report_dir: str,
               font_path: Optional[str]) -> None:
    """ Draw one numbered topic card inside the given bounding box. """
    left, top, right, bottom = box
    color = category_color(topic.category)

    draw.rectangle([(left, top), (right, bottom)], fill=CARD_COLOR,
                   outline=BORDER_COLOR)

    number_font = load_font(font_path, 24)
    title_font = load_font(font_path, 21)
    bullet_font = load_font(font_path, 17)

    # Numbered badge in the category color.
    badge = (left + 14, top + 14, left + 50, top + 50)
    draw.rectangle(badge, fill=color)
    label = str(number)
    label_width, label_height = text_size(draw, label, number_font)
    draw.text((badge[0] + (36 - label_width) / 2,
               badge[1] + (36 - label_height) / 2 - 2),
              label, font=number_font, fill="#ffffff")

    # Headline, limited to two lines so that every card keeps the same
    # vertical rhythm.
    title_left = left + 62
    title_width = right - title_left - 14
    title_lines = wrap_text(draw, topic.title, title_font, title_width,
                            max_lines=2)
    for index, line in enumerate(title_lines):
        draw.text((title_left, top + 14 + index * 26), line, font=title_font,
                  fill=TEXT_COLOR)

    # Illustration occupying the middle band of the card.
    image_top = top + 68
    image_bottom = image_top + int((bottom - top) * 0.44)
    image_box = (left + 14, image_top, right - 14, image_bottom)
    if topic.image:
        _paste_illustration(canvas, os.path.join(report_dir, topic.image),
                            image_box)
    else:
        draw.rectangle(image_box, fill=color)

    # Bullet list filling the space left above the source strip.
    bullet_top = image_bottom + 14
    bullet_left = left + 24
    bullet_width = right - bullet_left - 18
    bullet_limit = bottom - SOURCE_STRIP_HEIGHT
    line_height = 24
    for bullet in topic.bullets:
        if bullet_top + line_height > bullet_limit:
            break
        lines = wrap_text(draw, bullet, bullet_font, bullet_width - 16,
                          max_lines=2)
        draw.ellipse([(bullet_left - 12, bullet_top + 7),
                      (bullet_left - 5, bullet_top + 14)], fill=color)
        for line in lines:
            if bullet_top + line_height > bullet_limit:
                break
            draw.text((bullet_left, bullet_top), line, font=bullet_font,
                      fill=TEXT_COLOR)
            bullet_top += line_height
        bullet_top += 4

    # Primary source URL, pinned to the bottom of the card.
    if topic.sources:
        source_font = load_font(font_path, 13)
        url = _display_url(topic.sources[0].get("url", ""))
        if url:
            lines = wrap_text(draw, url, source_font,
                              right - left - 28, max_lines=1)
            draw.text((left + 14, bottom - SOURCE_STRIP_HEIGHT + 4),
                      lines[0], font=source_font, fill=SUBTEXT_COLOR)


def compose(date: str, topics: List[Topic], report_dir: str,
            font_path: Optional[str] = None,
            lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> str:
    """
    Render the composite summary image of one report.

    Args:
        date: Report date in YYYY-MM-DD form.
        topics: Topics of the report, already ordered and illustrated.
        report_dir: Directory holding the topic images; the composite
            image is written there as summary.png.
        font_path: Path of a CJK capable font, or None.
        lookback_hours: Age limit the collectors applied, announced in
            the header and the footer.

    Returns:
        The path of the written PNG file.
    """
    canvas = Image.new("RGB", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(canvas)

    _draw_header(draw, date, topics, font_path, lookback_hours)

    grid_top = HEADER_HEIGHT
    grid_bottom = CANVAS_HEIGHT - FOOTER_HEIGHT - MARGIN
    rows = max(1, (min(len(topics), GRID_COLUMNS * 2) + GRID_COLUMNS - 1)
               // GRID_COLUMNS)
    card_width = (CANVAS_WIDTH - 2 * MARGIN
                  - CARD_GAP * (GRID_COLUMNS - 1)) // GRID_COLUMNS
    card_height = (grid_bottom - grid_top - CARD_GAP * (rows - 1)) // rows

    for index, topic in enumerate(topics[:GRID_COLUMNS * rows]):
        row, column = divmod(index, GRID_COLUMNS)
        left = MARGIN + column * (card_width + CARD_GAP)
        top = grid_top + row * (card_height + CARD_GAP)
        _draw_card(canvas, draw, topic, index + 1,
                   (left, top, left + card_width, top + card_height),
                   report_dir, font_path)

    _draw_footer(draw, font_path, lookback_hours)

    output_path = os.path.join(report_dir, "summary.png")
    canvas.save(output_path, format="PNG")
    logger.info("composed summary image at %s", output_path)
    return output_path
