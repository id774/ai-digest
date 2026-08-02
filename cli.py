#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# cli.py: Daily batch entry point of ai-digest
#
#  Description:
#  This script runs the daily pipeline of ai-digest:
#
#      collect (arXiv API + news RSS)
#        -> deduplicate by title similarity
#        -> summarize and classify with the Claude API
#        -> resolve one image per topic (scrape, else generate)
#        -> store report.json and the images under DATA_DIR
#        -> render the report HTML and the composite summary PNG
#
#  It is meant to be started once a day from cron, and is independent
#  from the Flask viewer: the viewer only reads what this script wrote,
#  so a failed run never takes the site down.
#
#  The 'demo' command stores a report built from the sample bundled in
#  ai_digest/demo, skipping collection and summarization, so that the
#  viewer has something to show before an API key is configured.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Usage:
#      python cli.py run [--date YYYY-MM-DD] [--no-images] [--verbose]
#      python cli.py demo [--date YYYY-MM-DD] [--input FILE] [--verbose]
#      python cli.py render DATE
#      python cli.py list
#      python cli.py -h | --help
#      python cli.py -v | --version
#
#  Options:
#  - run
#      Execute the whole pipeline and store a new report.
#  - demo
#      Store a report built from the sample shipped in ai_digest/demo,
#      without collecting anything and without calling the API. Use it
#      to see a finished report before configuring a key.
#  - render DATE
#      Rebuild the HTML and the summary image of a stored report,
#      without collecting or calling the API again.
#  - list
#      Print the dates of the stored reports.
#  - --date YYYY-MM-DD
#      Date the report is filed under. Defaults to today, UTC, and to
#      the date recorded in the sample for 'demo'.
#  - --input FILE
#      Sample used by 'demo' instead of the bundled one.
#  - --no-images
#      Skip the scraping stage and generate every topic card locally.
#      Useful for a quick run or on a host without outbound access to
#      the publisher sites.
#  - --verbose
#      Log at debug level instead of info.
#
#  Exit Codes:
#  - 0: The command completed.
#  - 1: The command failed, for example because no topic could be built,
#       because the API key is missing or because SUMMARIZER_BACKEND,
#       ANTHROPIC_THINKING_MODE or ANTHROPIC_TOOL_CHOICE_MODE holds an
#       unknown value.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt
#  - ANTHROPIC_API_KEY must be set for the 'run' command, unless
#    SUMMARIZER_BACKEND=plain is used
#
#  Version History:
#  v1.1 2026-08-02
#       Stop 'run' on an unknown SUMMARIZER_BACKEND value, and validate
#       the thinking and tool choice settings before collecting
#       anything, so that a bad value costs no API call.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import argparse
import logging
import os
import sys
from datetime import datetime, timezone
from typing import List, Optional

from ai_digest import Entry, Topic, __version__, demo
from ai_digest.analyzer import plain, summarizer
from ai_digest.collectors import arxiv, news_rss
from ai_digest.dedup import deduplicate
from ai_digest.images import fallback, resolver
from ai_digest.render import build, compose_image
from ai_digest.storage import (ensure_report_dir, list_dates, load_report,
                               save_report)
from config import Config, load_config

logger = logging.getLogger("ai_digest.cli")


def configure_logging(verbose: bool) -> None:
    """ Send timestamped logs to stderr, quiet enough for cron. """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # The HTTP stack is chatty at debug level and adds nothing here.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def collect_entries(config: Config) -> List[Entry]:
    """
    Collect papers and news, papers first.

    The order matters for deduplication: when a paper and an article
    about it collide, the paper is the one kept as primary source.
    """
    papers = arxiv.collect(
        config.arxiv_categories, config.arxiv_max_results,
        config.lookback_hours, config.http_timeout, config.user_agent,
    )
    news = news_rss.collect(
        config.news_feed_urls, config.lookback_hours,
        config.http_timeout, config.user_agent,
    )
    return papers + news


def attach_images(topics: List[Topic], report_dir: str, config: Config,
                  scrape: bool = True) -> None:
    """
    Give every topic an illustration, in place.

    Scraping is attempted on the sources of the topic in order. The
    first usable image wins; when every attempt fails, or when scraping
    is disabled, a card is generated locally so that no topic is left
    without an image.
    """
    for index, topic in enumerate(topics, start=1):
        stored = None
        if scrape:
            for source in topic.sources:
                found = resolver.resolve(source.get("url", ""),
                                         config.http_timeout,
                                         config.user_agent)
                if found is None:
                    continue
                content, extension, credit = found
                filename = "topic-{0}.{1}".format(index, extension)
                with open(os.path.join(report_dir, filename), "wb") as handle:
                    handle.write(content)
                stored = (filename, credit)
                break

        if stored is None:
            filename = "topic-{0}.png".format(index)
            card = fallback.generate_card(topic.title, topic.category,
                                          config.font_path)
            card.save(os.path.join(report_dir, filename), format="PNG")
            stored = (filename, "generated")

        topic.image, topic.image_credit = stored
        logger.info("topic %d image: %s (%s)", index, topic.image,
                    topic.image_credit)


def command_run(args: argparse.Namespace, config: Config) -> int:
    """ Execute the whole pipeline for one date. """
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        config.validate_summarizer_backend()
    except RuntimeError as error:
        logger.error("%s", error)
        return 1

    use_claude = config.summarizer_backend == "claude"
    if use_claude:
        try:
            config.validate_anthropic_auth()
            config.validate_anthropic_options()
        except RuntimeError as error:
            logger.error("%s", error)
            return 1

    collected = collect_entries(config)
    if not collected:
        logger.error("no entry collected; check ARXIV_CATEGORIES and "
                     "NEWS_FEED_URLS, or the network connection")
        return 1

    unique = deduplicate(collected)
    try:
        if use_claude:
            topics = summarizer.summarize(
                unique,
                api_key=config.anthropic_api_key,
                model=config.anthropic_model,
                max_topics=config.max_topics,
                base_url=config.anthropic_base_url,
                auth_token=config.anthropic_auth_token,
                thinking_mode=config.anthropic_thinking_mode,
                tool_choice_mode=config.anthropic_tool_choice_mode,
            )
        else:
            topics = plain.summarize(unique, config.max_topics)
    except Exception as error:  # network, quota and protocol errors alike
        logger.error("summarization failed: %s", error)
        return 1
    if not topics:
        logger.error("the model returned no usable topic")
        return 1

    report_dir = ensure_report_dir(config.data_dir, date)
    attach_images(topics, report_dir, config, scrape=not args.no_images)

    stats = {
        "collected": len(collected),
        "deduplicated": len(unique),
        "topics": len(topics),
        "model": config.anthropic_model if use_claude else "plain",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_report(config.data_dir, date, topics, stats)
    compose_image.compose(date, topics, report_dir, config.font_path)
    build.write_report_html(report_dir, date, topics, stats)
    logger.info("report for %s written to %s", date, report_dir)
    return 0


def command_demo(args: argparse.Namespace, config: Config) -> int:
    """ Build the bundled demo report, without network or API key. """
    try:
        sample_date, topics, collected = demo.build_topics(config.max_topics,
                                                           args.input)
    except (KeyError, OSError, ValueError) as error:
        logger.error("cannot read the demo sample: %s", error)
        return 1
    if not topics:
        logger.error("the demo sample yielded no usable topic")
        return 1

    date = args.date or sample_date
    report_dir = ensure_report_dir(config.data_dir, date)
    # Scraping stays off, so that a demo run touches nothing but disk.
    attach_images(topics, report_dir, config, scrape=False)

    stats = {
        "collected": collected,
        "deduplicated": collected,
        "topics": len(topics),
        "model": "demo",
        "generated_at": "{0}T00:00:00+00:00".format(date),
    }
    save_report(config.data_dir, date, topics, stats)
    compose_image.compose(date, topics, report_dir, config.font_path)
    build.write_report_html(report_dir, date, topics, stats)
    logger.info("demo report for %s written to %s", date, report_dir)
    return 0


def command_render(args: argparse.Namespace, config: Config) -> int:
    """ Rebuild the artifacts of a stored report. """
    report = load_report(config.data_dir, args.date)
    if report is None:
        logger.error("no stored report for %s", args.date)
        return 1
    report_dir = ensure_report_dir(config.data_dir, args.date)
    compose_image.compose(args.date, report["topics"], report_dir,
                          config.font_path)
    build.write_report_html(report_dir, args.date, report["topics"],
                            report["stats"])
    return 0


def command_list(_args: argparse.Namespace, config: Config) -> int:
    """ Print the dates of the stored reports, newest first. """
    for date in list_dates(config.data_dir):
        print(date)
    return 0


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """ Build the command line parser and parse the arguments. """
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Generate the daily AI digest report.",
    )
    parser.add_argument("-v", "--version", action="version",
                        version="ai-digest {0}".format(__version__))
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="collect, summarize and render a new report")
    run_parser.add_argument("--date", help="report date, YYYY-MM-DD")
    run_parser.add_argument("--no-images", action="store_true",
                            help="never scrape, generate every card")
    run_parser.add_argument("--verbose", action="store_true",
                            help="log at debug level")
    run_parser.set_defaults(handler=command_run)

    demo_parser = subparsers.add_parser(
        "demo", help="build the bundled sample report, no API key needed")
    demo_parser.add_argument("--date", help="report date, YYYY-MM-DD")
    demo_parser.add_argument("--input", help="sample JSON to use instead "
                                             "of the bundled one")
    demo_parser.add_argument("--verbose", action="store_true",
                             help="log at debug level")
    demo_parser.set_defaults(handler=command_demo)

    render_parser = subparsers.add_parser(
        "render", help="rebuild the artifacts of a stored report")
    render_parser.add_argument("date", help="report date, YYYY-MM-DD")
    render_parser.add_argument("--verbose", action="store_true",
                               help="log at debug level")
    render_parser.set_defaults(handler=command_render)

    list_parser = subparsers.add_parser("list", help="list stored reports")
    list_parser.add_argument("--verbose", action="store_true",
                             help="log at debug level")
    list_parser.set_defaults(handler=command_list)

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """ Entry point returning the process exit code. """
    args = parse_args(argv)
    configure_logging(getattr(args, "verbose", False))
    return args.handler(args, load_config())


if __name__ == "__main__":
    sys.exit(main())
