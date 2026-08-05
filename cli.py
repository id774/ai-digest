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
#  Every setting of config.py except the three credentials and PORT,
#  which only the viewer reads, can also be given as an option, which
#  overrides the environment and .env for one invocation:
#
#      python cli.py run --lookback-hours 72
#
#  Usage:
#      python cli.py run [--date YYYY-MM-DD] [--no-images] [OVERRIDE ...]
#                        [--verbose]
#      python cli.py demo [--date YYYY-MM-DD] [--input FILE]
#                         [OVERRIDE ...] [--verbose]
#      python cli.py render DATE [OVERRIDE ...] [--verbose]
#      python cli.py list [--data-dir DIR] [--verbose]
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
#  Setting overrides, each naming the variable it replaces:
#  - Any command: --data-dir DIR (DATA_DIR)
#  - 'run', 'demo' and 'render': --font-path PATH (AI_DIGEST_FONT_PATH)
#  - 'run' and 'demo': --max-topics N (MAX_TOPICS)
#  - 'run' only:
#      --lookback-hours N (LOOKBACK_HOURS)
#      --arxiv-categories LIST (ARXIV_CATEGORIES)
#      --arxiv-max-results N (ARXIV_MAX_RESULTS)
#      --news-feed-urls LIST (NEWS_FEED_URLS)
#      --summarizer-backend NAME (SUMMARIZER_BACKEND)
#      --summarizer-model NAME (SUMMARIZER_MODEL)
#      --summarizer-base-url URL (SUMMARIZER_BASE_URL)
#      --summarizer-max-retries N (SUMMARIZER_MAX_RETRIES)
#      --summarizer-thinking-mode MODE (SUMMARIZER_THINKING_MODE)
#      --summarizer-tool-choice-mode MODE
#          (SUMMARIZER_TOOL_CHOICE_MODE)
#      --summarizer-text-json-fallback MODE
#          (SUMMARIZER_TEXT_JSON_FALLBACK)
#      --max-output-tokens N (MAX_OUTPUT_TOKENS)
#      --summarizer-timeout SECONDS (SUMMARIZER_TIMEOUT)
#      --http-timeout SECONDS (HTTP_TIMEOUT)
#      --user-agent STRING (USER_AGENT)
#
#  SUMMARIZER_API_KEY and SUMMARIZER_AUTH_TOKEN have no option on
#  purpose: a command line is readable by every user of the host, so a
#  credential belongs in the environment or in .env.
#
#  Exit Codes:
#  - 0: The command completed.
#  - 1: The command failed, for example because no entry was collected,
#       because no topic could be built, because the credential is
#       missing, because SUMMARIZER_BACKEND,
#       SUMMARIZER_THINKING_MODE or SUMMARIZER_TOOL_CHOICE_MODE holds
#       an unknown value, or because a setting this project no longer
#       reads is still exported.
#  - 2: The command line was rejected, for example because an option
#       expecting a positive number received something else.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt
#  - SUMMARIZER_API_KEY or SUMMARIZER_AUTH_TOKEN must be set for the
#    'run' command, unless SUMMARIZER_BACKEND=plain is used
#
#  Version History:
#  v1.5 2026-08-05
#       Name the endpoint options and settings after the summarization
#       stage instead of a vendor: --anthropic-* and --openai-* become
#       one --summarizer-* set, matching the SUMMARIZER_* variables
#       they override, and one credential serves whichever backend is
#       selected.
#  v1.4 2026-08-05
#       Bound the summarization request with SUMMARIZER_TIMEOUT, and
#       check it before anything is collected, so that an endpoint
#       which never answers cannot hold a nightly run open.
#  v1.3 2026-08-04
#       Accept every setting except the credentials as an option, so
#       that a one off run needs neither the environment edited nor a
#       variable prefixed. Record the look back window a run used in
#       its statistics, so that 'render' redraws the summary image with
#       the period the report was built from.
#  v1.2 2026-08-03
#       Pass the look back window to the summarizers and to the summary
#       image, so that both describe the period actually collected.
#       Report why a run collected nothing, distinguishing sources that
#       could not be reached from sources that offered nothing recent.
#  v1.1 2026-08-02
#       Stop 'run' on an unknown SUMMARIZER_BACKEND value, and validate
#       the thinking and tool choice settings before collecting
#       anything, so that a bad value costs no API call. Run the OpenAI
#       compatible backend when it is selected, and pass the text JSON
#       fallback, the retry budget and the output budget to the
#       summarizer.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import argparse
import logging
import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ai_digest import CollectionResult, Topic, __version__, demo
from ai_digest.analyzer import openai_compat, plain, summarizer
from ai_digest.collectors import arxiv, news_rss
from ai_digest.dedup import deduplicate
from ai_digest.images import fallback, resolver
from ai_digest.render import build, compose_image
from ai_digest.storage import (ensure_report_dir, list_dates, load_report,
                               save_report)
from config import (SUMMARIZER_BACKENDS, SUMMARIZER_TEXT_JSON_FALLBACK_MODES,
                    SUMMARIZER_THINKING_MODES, SUMMARIZER_TOOL_CHOICE_MODES,
                    Config, detect_font_path, load_config, split_csv)

logger = logging.getLogger("ai_digest.cli")

# Config fields an option may replace. Every option is named after the
# field it sets, so argparse stores it under that name and no table of
# its own is needed; an option left out stays None and changes nothing.
OVERRIDABLE_FIELDS = (
    "summarizer_base_url",
    "summarizer_model",
    "summarizer_thinking_mode",
    "summarizer_tool_choice_mode",
    "summarizer_text_json_fallback",
    "summarizer_max_retries",
    "max_output_tokens",
    "summarizer_timeout",
    "summarizer_backend",
    "arxiv_categories",
    "arxiv_max_results",
    "news_feed_urls",
    "lookback_hours",
    "max_topics",
    "font_path",
    "data_dir",
    "http_timeout",
    "user_agent",
)


def configure_logging(verbose: bool) -> None:
    """ Send timestamped logs to stderr, quiet enough for cron. """
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    # The HTTP stack is chatty at debug level and adds nothing here.
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def positive_int(value: str) -> int:
    """ Parse an option that accepts a number of one or more. """
    return bounded_int(value, 1)


def non_negative_int(value: str) -> int:
    """ Parse an option that also accepts zero. """
    return bounded_int(value, 0)


def bounded_int(value: str, minimum: int) -> int:
    """ Parse an integer option, rejecting anything below minimum. """
    try:
        number = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            "'{0}' is not a whole number".format(value))
    if number < minimum:
        raise argparse.ArgumentTypeError(
            "{0} is below the minimum of {1}".format(number, minimum))
    return number


def apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    """
    Replace the settings the command line gave, and only those.

    An option left out is None and keeps whatever the environment or
    .env configured, so an invocation without overrides behaves as it
    did before they existed. The replacements are logged, because a
    report has to stay explainable from the run that wrote it.
    """
    given = vars(args)
    overrides: Dict[str, Any] = {}
    for name in OVERRIDABLE_FIELDS:
        value = given.get(name)
        if value is not None:
            overrides[name] = value
    if not overrides:
        return config

    if "data_dir" in overrides:
        overrides["data_dir"] = os.path.abspath(overrides["data_dir"])
    # A path naming no file is probed as AI_DIGEST_FONT_PATH is, rather
    # than left to fail later in the image generators.
    if "font_path" in overrides:
        overrides["font_path"] = detect_font_path(overrides["font_path"])

    logger.info("command line overrides: %s", ", ".join(
        "{0}={1}".format(name, overrides[name])
        for name in sorted(overrides)))
    return replace(config, **overrides)


def collect_entries(config: Config) -> CollectionResult:
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
    return papers.merge(news)


def describe_empty_collection(result: CollectionResult,
                              lookback_hours: int) -> str:
    """
    Explain why a collection pass produced no entry.

    An empty run has three distinct causes, and a single message that
    lists every possible one leaves the reader to guess which applies.
    The counters of the pass separate them: nothing configured, nothing
    reachable, or sources that answered and had nothing recent to offer.
    The failure reasons of the unreachable sources are appended, since
    they say whether the host, the URL or the network is at fault.
    """
    if result.sources_total == 0:
        return ("no source configured; set ARXIV_CATEGORIES or "
                "NEWS_FEED_URLS")

    detail = "; ".join(result.failures)
    if result.sources_failed == result.sources_total:
        return ("no entry collected: all {0} sources failed, so nothing "
                "was read at all; check the network connection, the "
                "proxy settings and the configured URLs ({1})".format(
                    result.sources_total, detail))

    if result.items_seen == 0:
        reached = ("{0} of {1} sources answered but returned no item at "
                   "all; check ARXIV_CATEGORIES and NEWS_FEED_URLS".format(
                       result.sources_read, result.sources_total))
    else:
        reached = ("{0} of {1} sources answered and offered {2} items, none "
                   "of them published within the last {3} hours; raise "
                   "--lookback-hours or LOOKBACK_HOURS, or review "
                   "ARXIV_CATEGORIES and NEWS_FEED_URLS".format(
                       result.sources_read, result.sources_total,
                       result.items_seen, lookback_hours))
    if result.sources_failed:
        return ("no entry collected: {0}; the remaining {1} could not be "
                "read ({2})".format(reached, result.sources_failed, detail))
    return "no entry collected: {0}".format(reached)


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


def _model_label(config: Config, use_api: bool) -> str:
    """ Name the model a report was built with, for its statistics. """
    return config.resolved_model if use_api else "plain"


def command_run(args: argparse.Namespace, config: Config) -> int:
    """ Execute the whole pipeline for one date. """
    date = args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        config.validate_summarizer_backend()
    except RuntimeError as error:
        logger.error("%s", error)
        return 1

    use_anthropic = config.summarizer_backend == "anthropic-compatible"
    use_openai = config.summarizer_backend == "openai-compatible"
    use_api = use_anthropic or use_openai
    try:
        if use_api:
            config.validate_summarizer_auth()
            config.validate_summarizer_model()
            config.validate_retry_budget()
            config.validate_output_budget()
            config.validate_summarizer_timeout()
        if use_anthropic:
            config.validate_protocol_options()
    except RuntimeError as error:
        logger.error("%s", error)
        return 1

    collection = collect_entries(config)
    collected = collection.entries
    if not collected:
        logger.error("%s", describe_empty_collection(collection,
                                                     config.lookback_hours))
        return 1
    if collection.sources_failed:
        logger.warning("continuing with %d of %d sources; %d failed (%s)",
                       collection.sources_read, collection.sources_total,
                       collection.sources_failed,
                       "; ".join(collection.failures))

    unique = deduplicate(collected)
    try:
        if use_anthropic:
            topics = summarizer.summarize(
                unique,
                api_key=config.summarizer_api_key,
                model=config.resolved_model,
                max_topics=config.max_topics,
                base_url=config.summarizer_base_url,
                auth_token=config.summarizer_auth_token,
                thinking_mode=config.summarizer_thinking_mode,
                tool_choice_mode=config.summarizer_tool_choice_mode,
                text_json_fallback=(
                    config.summarizer_text_json_fallback == "enabled"),
                max_retries=config.summarizer_max_retries,
                max_output_tokens=config.max_output_tokens,
                timeout=config.summarizer_timeout,
                lookback_hours=config.lookback_hours,
            )
        elif use_openai:
            # The OpenAI SDK sends its api_key as a Bearer token, which
            # is the header SUMMARIZER_AUTH_TOKEN names, so either
            # spelling of the credential describes the same request.
            topics = openai_compat.summarize(
                unique,
                api_key=(config.summarizer_api_key
                         or config.summarizer_auth_token or ""),
                model=config.resolved_model,
                max_topics=config.max_topics,
                base_url=config.summarizer_base_url,
                max_retries=config.summarizer_max_retries,
                max_output_tokens=config.max_output_tokens,
                timeout=config.summarizer_timeout,
                lookback_hours=config.lookback_hours,
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
        "model": _model_label(config, use_api),
        "lookback_hours": config.lookback_hours,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    save_report(config.data_dir, date, topics, stats)
    compose_image.compose(date, topics, report_dir, config.font_path,
                          config.lookback_hours)
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
        "lookback_hours": config.lookback_hours,
        "generated_at": "{0}T00:00:00+00:00".format(date),
    }
    save_report(config.data_dir, date, topics, stats)
    compose_image.compose(date, topics, report_dir, config.font_path,
                          config.lookback_hours)
    build.write_report_html(report_dir, date, topics, stats)
    logger.info("demo report for %s written to %s", date, report_dir)
    return 0


def command_render(args: argparse.Namespace, config: Config) -> int:
    """
    Rebuild the artifacts of a stored report.

    The summary image announces the window the run collected, which the
    statistics of the report carry. Reading it from the configuration
    instead would make a report rebuilt after LOOKBACK_HOURS changed
    describe a period it was never built from. Reports stored before
    the window was recorded fall back on the configured one.
    """
    report = load_report(config.data_dir, args.date)
    if report is None:
        logger.error("no stored report for %s", args.date)
        return 1
    stats = report["stats"]
    report_dir = ensure_report_dir(config.data_dir, args.date)
    compose_image.compose(args.date, report["topics"], report_dir,
                          config.font_path,
                          stats.get("lookback_hours", config.lookback_hours))
    build.write_report_html(report_dir, args.date, report["topics"], stats)
    return 0


def command_list(_args: argparse.Namespace, config: Config) -> int:
    """ Print the dates of the stored reports, newest first. """
    for date in list_dates(config.data_dir):
        print(date)
    return 0


def add_common_options(parser: argparse.ArgumentParser) -> None:
    """ Add the options every subcommand accepts. """
    parser.add_argument("--data-dir",
                        help="directory holding the reports (DATA_DIR)")
    parser.add_argument("--verbose", action="store_true",
                        help="log at debug level")


def add_topics_option(parser: argparse.ArgumentParser) -> None:
    """ Add the option capping how many topics a report holds. """
    parser.add_argument("--max-topics", type=positive_int,
                        help="topics rendered in one report (MAX_TOPICS)")


def add_font_option(parser: argparse.ArgumentParser) -> None:
    """ Add the font option, for the subcommands that draw images. """
    parser.add_argument("--font-path",
                        help="CJK font used for the images "
                             "(AI_DIGEST_FONT_PATH)")


def add_collection_options(parser: argparse.ArgumentParser) -> None:
    """ Add the options shaping what 'run' collects. """
    parser.add_argument("--lookback-hours", type=positive_int,
                        help="age limit of the collected entries, in hours "
                             "(LOOKBACK_HOURS)")
    parser.add_argument("--arxiv-categories", type=split_csv,
                        help="comma separated arXiv categories "
                             "(ARXIV_CATEGORIES)")
    parser.add_argument("--arxiv-max-results", type=positive_int,
                        help="entries fetched per arXiv category "
                             "(ARXIV_MAX_RESULTS)")
    parser.add_argument("--news-feed-urls", type=split_csv,
                        help="comma separated RSS or Atom feeds "
                             "(NEWS_FEED_URLS)")
    parser.add_argument("--http-timeout", type=positive_int,
                        help="timeout of every request, in seconds "
                             "(HTTP_TIMEOUT)")
    parser.add_argument("--user-agent",
                        help="User-Agent sent with every request "
                             "(USER_AGENT)")


def add_summarizer_options(parser: argparse.ArgumentParser) -> None:
    """ Add the options shaping how 'run' summarizes. """
    parser.add_argument("--summarizer-backend", choices=SUMMARIZER_BACKENDS,
                        help="summarizer to use (SUMMARIZER_BACKEND)")
    parser.add_argument("--summarizer-model",
                        help="model asked for on the endpoint "
                             "(SUMMARIZER_MODEL)")
    parser.add_argument("--summarizer-base-url",
                        help="base URL of the endpoint; the "
                             "openai-compatible backend expects the "
                             "version path in it (SUMMARIZER_BASE_URL)")
    parser.add_argument("--summarizer-max-retries", type=non_negative_int,
                        help="retries the SDK may spend on one request "
                             "(SUMMARIZER_MAX_RETRIES)")
    parser.add_argument("--summarizer-thinking-mode",
                        choices=SUMMARIZER_THINKING_MODES,
                        help="thinking parameter sent with an "
                             "anthropic-compatible request "
                             "(SUMMARIZER_THINKING_MODE)")
    parser.add_argument("--summarizer-tool-choice-mode",
                        choices=SUMMARIZER_TOOL_CHOICE_MODES,
                        help="how the tool is demanded "
                             "(SUMMARIZER_TOOL_CHOICE_MODE)")
    parser.add_argument("--summarizer-text-json-fallback",
                        choices=SUMMARIZER_TEXT_JSON_FALLBACK_MODES,
                        help="accept a report written as JSON text "
                             "(SUMMARIZER_TEXT_JSON_FALLBACK)")
    parser.add_argument("--max-output-tokens", type=positive_int,
                        help="tokens the model may produce in one answer "
                             "(MAX_OUTPUT_TOKENS)")
    parser.add_argument("--summarizer-timeout", type=positive_int,
                        help="seconds allowed for one summarization "
                             "request (SUMMARIZER_TIMEOUT)")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """ Build the command line parser and parse the arguments. """
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="Generate the daily AI digest report. Every setting "
                    "except the credentials can be given as an option, "
                    "which overrides the environment and .env.",
    )
    parser.add_argument("-v", "--version", action="version",
                        version="ai-digest {0}".format(__version__))
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser(
        "run", help="collect, summarize and render a new report")
    run_parser.add_argument("--date", help="report date, YYYY-MM-DD")
    run_parser.add_argument("--no-images", action="store_true",
                            help="never scrape, generate every card")
    add_topics_option(run_parser)
    add_collection_options(run_parser)
    add_summarizer_options(run_parser)
    add_font_option(run_parser)
    add_common_options(run_parser)
    run_parser.set_defaults(handler=command_run)

    demo_parser = subparsers.add_parser(
        "demo", help="build the bundled sample report, no API key needed")
    demo_parser.add_argument("--date", help="report date, YYYY-MM-DD")
    demo_parser.add_argument("--input", help="sample JSON to use instead "
                                             "of the bundled one")
    add_topics_option(demo_parser)
    add_font_option(demo_parser)
    add_common_options(demo_parser)
    demo_parser.set_defaults(handler=command_demo)

    render_parser = subparsers.add_parser(
        "render", help="rebuild the artifacts of a stored report")
    render_parser.add_argument("date", help="report date, YYYY-MM-DD")
    add_font_option(render_parser)
    add_common_options(render_parser)
    render_parser.set_defaults(handler=command_render)

    list_parser = subparsers.add_parser("list", help="list stored reports")
    add_common_options(list_parser)
    list_parser.set_defaults(handler=command_list)

    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """ Entry point returning the process exit code. """
    args = parse_args(argv)
    configure_logging(getattr(args, "verbose", False))
    try:
        config = load_config()
    except RuntimeError as error:
        # A setting the project no longer reads is a configuration
        # problem, not a crash: it deserves the same one line every
        # other refused setting gets, not a traceback the operator has
        # to read past to find the name and its replacement.
        logger.error("%s", error)
        return 1
    return args.handler(args, apply_overrides(config, args))


if __name__ == "__main__":
    sys.exit(main())
