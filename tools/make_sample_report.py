#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tools/make_sample_report.py: Build the documentation sample report
#
#  Description:
#  This script produces the report shown in the README screenshots. It
#  runs the same code as the daily batch for every stage that shapes the
#  output - Topic validation, card generation, composite image and HTML
#  rendering - but replaces the two stages that need the network:
#
#      collection      -> entries read from doc/sample/sample_input.json
#      summarization   -> the build_report arguments read from the same
#                         file, passed through summarizer._to_topics()
#
#  It exists so that the screenshots in the documentation can be rebuilt
#  by anyone, on any machine, without an API key and without depending
#  on what arXiv happened to publish that morning. It is a documentation
#  tool and is not part of the application; nothing under ai_digest/
#  imports it.
#
#  For a report built from live sources, run the batch itself:
#
#      python cli.py run
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt
#  - A CJK capable TrueType font, as for the batch itself
#
#  Usage:
#      python tools/make_sample_report.py [--data-dir DIR]
#                                         [--input FILE] [--date DATE]
#
#  Options:
#  - --data-dir DIR
#      Archive the report is written to. Defaults to DATA_DIR, that is
#      the same archive the batch and the viewer use.
#  - --input FILE
#      Sample input. Defaults to doc/sample/sample_input.json.
#  - --date DATE
#      Report date. Defaults to the date recorded in the input file.
#
#  Exit Codes:
#  - 0: The report was written.
#  - 1: The input file is missing or yielded no usable topic.
#
#  Version History:
#  v1.0 2026-07-28
#       Initial release.
#
########################################################################

import argparse
import json
import logging
import os
import sys

# The repository root, so that the script runs from anywhere.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ai_digest import Entry                                  # noqa: E402
from ai_digest.analyzer.summarizer import _to_topics          # noqa: E402
from ai_digest.render import build, compose_image             # noqa: E402
from ai_digest.storage import ensure_report_dir, save_report  # noqa: E402
from cli import attach_images                                 # noqa: E402
from config import load_config                                # noqa: E402

DEFAULT_INPUT = os.path.join(BASE_DIR, "doc", "sample", "sample_input.json")

logger = logging.getLogger("ai_digest.tools.sample")


def parse_args(argv=None):
    """ Build the command line parser and parse the arguments. """
    parser = argparse.ArgumentParser(
        prog="make_sample_report.py",
        description="Build the sample report used by the documentation.",
    )
    parser.add_argument("--data-dir", help="archive to write to")
    parser.add_argument("--input", default=DEFAULT_INPUT,
                        help="sample input JSON")
    parser.add_argument("--date", help="report date, YYYY-MM-DD")
    return parser.parse_args(argv)


def main(argv=None):
    """ Entry point returning the process exit code. """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = parse_args(argv)
    config = load_config()

    if not os.path.isfile(args.input):
        logger.error("no sample input at %s", args.input)
        return 1
    with open(args.input, encoding="utf-8") as handle:
        payload = json.load(handle)

    date = args.date or payload["date"]
    data_dir = os.path.abspath(args.data_dir or config.data_dir)
    entries = [Entry.from_dict(item) for item in payload["entries"]]

    # The same conversion the Claude backend applies to a build_report
    # tool call, so a malformed sample is rejected exactly as a
    # malformed model answer would be.
    topics = _to_topics(payload["build_report"], entries, config.max_topics)
    if not topics:
        logger.error("the sample input yielded no usable topic")
        return 1

    report_dir = ensure_report_dir(data_dir, date)
    # Scraping is disabled: the cards have to be reproducible, and the
    # sample must not depend on what the publishers serve today.
    attach_images(topics, report_dir, config, scrape=False)

    stats = {
        "collected": len(entries),
        "deduplicated": len(entries),
        "topics": len(topics),
        "model": "sample",
        "generated_at": "{0}T00:00:00+00:00".format(date),
    }
    save_report(data_dir, date, topics, stats)
    compose_image.compose(date, topics, report_dir, config.font_path)
    build.write_report_html(report_dir, date, topics, stats)
    logger.info("sample report for %s written to %s", date, report_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
