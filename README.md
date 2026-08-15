# ai-digest

## Contents

1. [Overview](#overview)
2. [Features](#features)
3. [Requirements](#requirements)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Standalone use, no API key](#standalone-use-no-api-key)
7. [Usage](#usage)
8. [When something fails](#when-something-fails)
9. [Tests](#tests)
10. [Deployment](#deployment)
11. [Repository Structure](#repository-structure)
12. [The Japanese that stays](#the-japanese-that-stays)
13. [Demo and sample output](#demo-and-sample-output)
14. [Contribution](#contribution)
15. [License](#license)

## Overview

**ai-digest** collects AI related papers and news once a day, summarizes and classifies them in Japanese with the Claude API, and publishes the result as a browsable HTML report together with a single composite PNG image.

The batch pipeline and the web viewer are separate processes. `cli.py` performs the daily collection and generation, writes everything under `data/reports/<date>/`, and exits. `app.py` is a read only Flask application that serves what the batch already produced, so a failed or slow run never takes the site down and the web process needs no API key.

Every topic carries an illustration. The application first tries to obtain a real image from the source, an `ar5iv` figure for arXiv papers or the Open Graph image for news articles, and draws a card locally with Pillow when that fails. Scraping is best effort by design; a publisher changing its markup degrades the look of the report, never its availability.

The Claude API is only used for one stage: clustering, translating and classifying the collected entries into topics. Collection (arXiv, RSS/Atom) and every image path already run without an API key. Setting `SUMMARIZER_BACKEND=plain` removes the last dependency and runs the whole pipeline offline except for fetching the feeds themselves; see [Standalone use, no API key](#standalone-use-no-api-key).

- Requirements definition: [doc/REQUIREMENTS.md](doc/REQUIREMENTS.md)
- Basic design: [doc/BASIC_DESIGN.md](doc/BASIC_DESIGN.md)
- Debian and nginx deployment: [doc/DEPLOYMENT.md](doc/DEPLOYMENT.md)
- Demo mode and the screenshots: [doc/DEMO.md](doc/DEMO.md)
- Implementation policy: [doc/POLICY.md](doc/POLICY.md)
- Repository version history: [doc/VERSIONS](doc/VERSIONS)

## Features

- **Daily pipeline in a single command**: collect, deduplicate, summarize, illustrate, render
- **Structured summarization**: the Claude API is called through tool use, so the answer is validated JSON rather than prose
- **Japanese output**: English sources are translated and condensed into two to four bullet points per topic
- **Free form categories**: labels are chosen by the model per day, and colors are derived from the label so that they stay consistent within a report
- **Resilient image handling**: scraping is attempted first and falls back to locally generated cards
- **One image per day**: a composite PNG summarizing the whole report, drawn with Pillow, without a headless browser
- **No database**: reports are plain JSON and PNG files under one directory per day
- **Deployable as is**: `systemd`, `nginx` and `cron` examples in [deploy/](deploy), a `Procfile` for Heroku

## Requirements

- Python 3.9 or later
- A credential for an endpoint speaking the Anthropic Messages API or the OpenAI Chat Completions API, unless `SUMMARIZER_BACKEND=plain` (see [Standalone use, no API key](#standalone-use-no-api-key))
- A CJK capable TrueType font, for example the `fonts-noto-cjk` package; see [Japanese font](#japanese-font)
- Outbound HTTPS access to `export.arxiv.org`, the configured feeds and, unless running standalone, the Anthropic API

Python dependencies are listed in `requirements.txt`:

| Package | Purpose |
|---|---|
| Flask | Web viewer and Jinja2 templates |
| anthropic | Claude API client |
| feedparser | arXiv Atom and news RSS parsing |
| requests | HTTP transport for the collectors and the scraper |
| beautifulsoup4 | HTML parsing for figure and Open Graph extraction |
| Pillow | Fallback cards and the composite summary image |
| python-dotenv | Loading of the local `.env` file |
| gunicorn | Application server used in production |

## Installation

The following steps assume Debian or Ubuntu. Adjust the package manager commands for other systems.

### 1. Install the system packages

```sh
sudo apt update
sudo apt install python3 python3-venv python3-pip fonts-noto-cjk
```

`fonts-noto-cjk` is not optional in practice. Every string drawn into an image is Japanese, and neither the bitmap font bundled with Pillow nor DejaVuSans contains CJK glyphs, so without it the generated cards and the summary image show empty boxes instead of text.

### 2. Clone the repository

```sh
git clone https://github.com/id774/ai-digest.git
cd ai-digest
```

### 3. Create a virtual environment and install the dependencies

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure the environment

```sh
cp .env.example .env
$EDITOR .env
```

At minimum, set `SUMMARIZER_API_KEY`, or `SUMMARIZER_AUTH_TOKEN` for an endpoint
that authenticates with a Bearer token. The `.env` file is ignored by Git and must
never be committed. Exported variables take precedence over `.env` values.

The settings that address the endpoint are named after the summarization stage
rather than after a vendor, because the same key, base URL and model reach
whichever endpoint is configured. The `ANTHROPIC_*` and `OPENAI_*` names they
replaced are refused at startup and answered with their replacement; see
[Renamed settings](#renamed-settings).

### 5. Verify the installation

```sh
python cli.py --version
python cli.py list
python -m unittest discover -s tests
```

The first command prints the version, the second prints nothing on a fresh installation because no report exists yet. The third runs the whole test suite, which needs no network access, no API key and nothing beyond the standard library and the installed dependencies; see [Tests](#tests).

## Configuration

All settings are read from environment variables, optionally through `.env`. They are collected in `config.py`. Every one of them except the two credentials and `PORT`, which only the viewer reads, also has a command line option on `cli.py` that overrides the environment for one invocation; see [Overriding a setting for one run](#overriding-a-setting-for-one-run).

| Variable | Default | Description |
|---|---|---|
| `SUMMARIZER_BACKEND` | `anthropic-compatible` | Wire protocol of the summarization endpoint. `anthropic-compatible` speaks the Anthropic Messages API. `openai-compatible` speaks the OpenAI Chat Completions API; see [OpenAI-compatible endpoints](#openai-compatible-endpoints). `plain` builds topics mechanically, with no credential and no clustering or translation; see [Standalone use, no API key](#standalone-use-no-api-key). Any other value stops `cli.py run` before it collects anything, rather than falling back on the default. |
| `SUMMARIZER_API_KEY` | none | API key of the endpoint. Mutually exclusive with `SUMMARIZER_AUTH_TOKEN`. |
| `SUMMARIZER_AUTH_TOKEN` | none | Bearer token of the endpoint. Mutually exclusive with `SUMMARIZER_API_KEY`. |
| `SUMMARIZER_BASE_URL` | none | Base URL of the endpoint. Empty means Anthropic itself. The `openai-compatible` backend expects the version path to be part of it, the `anthropic-compatible` one does not. |
| `SUMMARIZER_MODEL` | `claude-sonnet-4-5` on `anthropic-compatible` | Model asked for on the endpoint. Required by `SUMMARIZER_BACKEND=openai-compatible`, whose model names are the endpoint's own. |
| `SUMMARIZER_MAX_RETRIES` | `2` | Retries the SDK may spend on one request, on either API backend. `0` spends exactly one request per run. |
| `SUMMARIZER_THINKING_MODE` | `default` | Read by `anthropic-compatible`. `default` sends no thinking parameter and keeps the provider default. `disabled` sends `thinking.type=disabled`, for a model that would otherwise think until the output budget is gone. |
| `SUMMARIZER_TOOL_CHOICE_MODE` | `forced` | Read by `anthropic-compatible`. `forced` names `build_report` in `tool_choice`. `any` demands a tool without naming one. `auto` lets the model choose the tool and disables parallel tool use. |
| `SUMMARIZER_TEXT_JSON_FALLBACK` | `disabled` | Read by `anthropic-compatible`. `enabled` also accepts a report written as JSON text when no tool call came back; see [When the endpoint returns no tool call](#when-the-endpoint-returns-no-tool-call). |
| `ARXIV_CATEGORIES` | `cs.AI,cs.LG,cs.CL` | arXiv categories to collect, comma separated. |
| `ARXIV_MAX_RESULTS` | `60` | Maximum entries fetched per category. |
| `NEWS_FEED_URLS` | three AI blogs | RSS or Atom feeds to collect, comma separated. |
| `LOOKBACK_HOURS` | `24` | Age limit of the collected entries. |
| `MAX_TOPICS` | `6` | Maximum topics per report. Six fills the summary image grid. |
| `MAX_OUTPUT_TOKENS` | `8000` | Tokens the model may produce in one answer, on either API backend. A model that thinks before answering spends the same budget. |
| `SUMMARIZER_TIMEOUT` | `180` | Seconds allowed for one summarization request, on either API backend. Each retry spends it again; see [Timeouts](#timeouts). |
| `AI_DIGEST_FONT_PATH` | probed | Path of the font used for image generation. |
| `DATA_DIR` | `data/reports` | Directory holding the generated reports. |
| `HTTP_TIMEOUT` | `60` | Timeout in seconds of every collector and scraper request. The summarization request uses `SUMMARIZER_TIMEOUT`. |
| `USER_AGENT` | `ai-digest/1.0 ...` | User-Agent sent with every outgoing request. |
| `PORT` | `3000` | Port of the development server and of gunicorn. |

### Anthropic-compatible APIs

Set a base URL and Bearer token to use an Anthropic-compatible Messages API.
For example, Sakura AI Engine can be configured as follows:

```env
SUMMARIZER_AUTH_TOKEN=<UUID>:<secret>
SUMMARIZER_BASE_URL=https://api.ai.sakura.ad.jp
SUMMARIZER_MODEL=preview/Kimi-K2.6
SUMMARIZER_THINKING_MODE=disabled
SUMMARIZER_TOOL_CHOICE_MODE=auto
SUMMARIZER_BACKEND=anthropic-compatible
```

Do not set `SUMMARIZER_API_KEY` and `SUMMARIZER_AUTH_TOKEN` together.
The provider must support `tools` and `tool_use` responses.

Being compatible with the Messages API does not mean behaving like Anthropic.
Support for a named `tool_choice` and for the thinking output varies from one
model to the next, which is what the two settings above are for. When a run
fails and the log shows `stop_reason=max_tokens` together with
`content_types=thinking`, the model used the whole output budget thinking and
never reached the tool call. Set `SUMMARIZER_THINKING_MODE=disabled` before
raising `MAX_OUTPUT_TOKENS`: more budget only buys more thinking, it does not
buy a tool call.

### When the endpoint returns no tool call

`summarization failed: Model returned no build_report tool call` means the
request was accepted and the answer carried no `tool_use` block. Change one
setting per run, so that the run which succeeds says which setting did it, and
read the `api response:` line the summarizer logs for `stop_reason` and
`content_types`. `--verbose` additionally dumps the whole response body.

1. `SUMMARIZER_TOOL_CHOICE_MODE=any` — the endpoint may drop a named
   `tool_choice` and still honour a demand for some tool. `build_report` is the
   only tool offered, so this reaches the same place.
2. `SUMMARIZER_TOOL_CHOICE_MODE=auto` — leaves the choice to the model. The
   system prompt already tells it to call `build_report`, but nothing forces it.
3. `SUMMARIZER_THINKING_MODE=disabled` — for `content_types=thinking` with
   `stop_reason=max_tokens`.
4. `SUMMARIZER_TEXT_JSON_FALLBACK=enabled` — only once a raw response has shown
   the endpoint answering with the right JSON as text. The report is then read
   from a text block that parses into an object with a `topics` list; anything
   else is still refused, and the run logs a warning naming this setting.
5. `SUMMARIZER_BACKEND=openai-compatible` — when the Anthropic-compatible route stays
   unreliable, below.

`SUMMARIZER_MAX_RETRIES=0` makes each attempt cost exactly one request, which
matters when the endpoint bills per request and two settings are being compared.

### OpenAI-compatible endpoints

`SUMMARIZER_BACKEND=openai-compatible` sends the same prompt and the same tool schema to an
OpenAI-compatible Chat Completions API, reading the answer from
`tool_calls[].function.arguments`. It is a second explicit path rather than a
fallback: both backends validate the parsed arguments identically, so a report
does not differ by the route it took.

```env
SUMMARIZER_BACKEND=openai-compatible
SUMMARIZER_API_KEY=<UUID>:<secret>
SUMMARIZER_BASE_URL=https://api.ai.sakura.ad.jp/v1
SUMMARIZER_MODEL=preview/Kimi-K2.6
```

`SUMMARIZER_BASE_URL` carries the version path on this backend, which the
`anthropic-compatible` one does not expect: switching between the two means
rewriting that line as well as `SUMMARIZER_BACKEND`. This
backend needs the `openai` package, which is deliberately absent from
`requirements.txt` so that a default installation carries one API client rather
than two:

```sh
pip install openai
```

### Renamed settings

The endpoint settings used to be spelled `ANTHROPIC_*` and `OPENAI_*`, one set
per backend. Both prefixes named a vendor for something that is a wire protocol:
an `anthropic-compatible` endpoint is regularly neither Anthropic nor operated
by it, and `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL`
are also the names the Anthropic SDK and other tools read from the environment
on their own, so a value exported for one of those decided where a digest was
sent. One endpoint answers at a time, so there is now one set of settings for
whichever is configured.

| Old | New |
|---|---|
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` | `SUMMARIZER_API_KEY` |
| `ANTHROPIC_AUTH_TOKEN` | `SUMMARIZER_AUTH_TOKEN` |
| `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL` | `SUMMARIZER_BASE_URL` |
| `ANTHROPIC_MODEL`, `OPENAI_MODEL` | `SUMMARIZER_MODEL` |
| `ANTHROPIC_MAX_RETRIES` | `SUMMARIZER_MAX_RETRIES` |
| `ANTHROPIC_THINKING_MODE` | `SUMMARIZER_THINKING_MODE` |
| `ANTHROPIC_TOOL_CHOICE_MODE` | `SUMMARIZER_TOOL_CHOICE_MODE` |
| `ANTHROPIC_TEXT_JSON_FALLBACK` | `SUMMARIZER_TEXT_JSON_FALLBACK` |
| `SUMMARIZER_BACKEND=claude` | `SUMMARIZER_BACKEND=anthropic-compatible` |
| `SUMMARIZER_BACKEND=openai` | `SUMMARIZER_BACKEND=openai-compatible` |

An old name is refused rather than read, and the message names its replacement:

```
ANTHROPIC_API_KEY is no longer read by ai-digest; use SUMMARIZER_API_KEY.
```

Presence is what is refused, not the value: an exported but empty
`ANTHROPIC_BASE_URL` still says the host was set up for the old names. Unset it,
in `.env` and in whatever exported it — a systemd unit, a cron environment, a
shell profile — rather than blanking it. The check runs in `load_config()`, so
it stops the viewer as well as the batch even though the viewer reads none of
these settings: a host half way through the rename is exactly the one where the
old name still decides something, and a viewer that keeps serving would hide
that rather than settle it. The command line options moved the same
way: `--anthropic-model` and `--openai-model` are now `--summarizer-model`.

### Timeouts

Two limits bound the outgoing requests, and they measure different things:

| Setting | Default | Bounds |
|---|---|---|
| `HTTP_TIMEOUT` | 60s | One collector or scraper request: an arXiv page, a feed, an article, an image |
| `SUMMARIZER_TIMEOUT` | 180s | One summarization request, on either API backend |

The summarization request is the longer of the two because it is not streamed:
the client waits until the last token of the answer exists, so what is being
waited for is the writing rather than the network. A day's worth of entries
condensed into `MAX_TOPICS` topics is the same work whether the feeds were busy
or quiet, and raising `MAX_OUTPUT_TOKENS` lengthens it.

Retries widen the window, because the SDK spends the timeout again on each one:

```text
worst case wait = SUMMARIZER_TIMEOUT x (SUMMARIZER_MAX_RETRIES + 1)
```

At the defaults that is nine minutes. Keep it well inside the interval between
two cron runs, so that a hung run has ended before the next one starts. Neither
setting may be zero or negative; `cli.py run` refuses such a value before it
collects anything, rather than letting the SDK reject it after a whole
collection has been spent.

### Japanese font

`AI_DIGEST_FONT_PATH` overrides the font used by the image generators. When it is empty, these locations are probed in order and the first existing file wins:

```
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf
/usr/share/fonts/truetype/fonts-japanese-gothic.ttf
/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf
```

When no CJK font is found, the batch logs a warning once and keeps running with the Pillow bitmap font; the HTML report stays correct, but the images lose their text.

## Standalone use, no API key

Set `SUMMARIZER_BACKEND=plain` to run the whole pipeline without a credential of any kind:

```sh
[ -f .env ] || cp .env.example .env
sed 's/^SUMMARIZER_BACKEND=.*/SUMMARIZER_BACKEND=plain/' .env > .env.new && mv .env.new .env
python cli.py run
```

The copy is guarded because step 4 already created `.env`, and an unconditional `cp` here would overwrite the key configured there. `.env.example` already defines `SUMMARIZER_BACKEND=anthropic-compatible`, so rewrite that line rather than appending a second one: a file carrying the same key twice states two different intentions, and which one wins is a property of the parser rather than of the configuration. The command above is plain POSIX `sed` writing to a new file, because in-place editing is spelled `sed -i` on GNU and `sed -i ''` on BSD and macOS.

For a single run, setting the variable in the environment needs no edit at all, since exported variables take precedence over `.env`:

```sh
SUMMARIZER_BACKEND=plain python cli.py run
```

In this mode:

- No summarization API is called, and `SUMMARIZER_API_KEY` can stay unset.
- Each collected entry becomes its own topic, newest first; there is no cross-entry clustering and no translation, so titles and bullets stay in whatever language the source published them in (English for most feeds, English abstracts for arXiv). The `category` label is taken from the entry's origin (the arXiv category or the feed title) instead of being chosen freely by a model.
- Topic illustrations are unaffected: image scraping and the Pillow fallback cards already run without a key. Add `--no-images` to also skip scraping and only draw local cards, for a run that touches nothing but arXiv and the configured feeds.

This trades the quality of the Japanese summary and the topic grouping for zero setup beyond `pip install -r requirements.txt`. Switch back to `SUMMARIZER_BACKEND=anthropic-compatible` (or unset it, since that is the default) whenever an API key becomes available again; both backends write the same `report.json` shape, and `cli.py render` works on reports produced by either one.

## Usage

### Generate today's report

```sh
python cli.py run
```

The command collects the last 24 hours, summarizes them, writes `data/reports/<today>/` and exits with status 1 when nothing usable could be produced, which makes failures visible in cron mail.

#### "no entry collected"

The error names the cause, so a quiet day and a broken network never look alike. Every source that answered normally but had nothing recent to offer:

```
INFO ai_digest.collectors.arxiv: collected 0 arXiv papers from 3 of 3 categories (150 papers offered, look back 24 hours)
INFO ai_digest.collectors.news_rss: collected 0 news articles from 3 of 3 feeds (60 articles offered, look back 24 hours)
ERROR ai_digest.cli: no entry collected: 6 of 6 sources answered and offered 210 items, none of them published within the last 24 hours; raise --lookback-hours or LOOKBACK_HOURS, or review ARXIV_CATEGORIES and NEWS_FEED_URLS
```

Nothing reachable at all:

```
WARNING ai_digest.collectors.arxiv: arXiv request failed for cs.AI: HTTPConnectionPool(host='export.arxiv.org', port=80): Max retries exceeded
ERROR ai_digest.cli: no entry collected: all 6 sources failed, so nothing was read at all; check the network connection, the proxy settings and the configured URLs (arXiv cs.AI: ...)
```

An empty window is expected, not a bug, and it is unrelated to `SUMMARIZER_BACKEND`, since collection happens before summarization runs. Two causes are common:

- **arXiv does not announce papers on weekends.** Friday through Sunday submissions are all announced on Monday, so `cli.py run` on a Saturday or Sunday routinely collects 0 arXiv papers.
- **The configured news feeds do not publish every day.** The default feeds (OpenAI, Google AI Blog, Hugging Face Blog) can go a day or more between posts.

When only some sources fail, the run continues with the rest and logs a `WARNING ... continuing with N of M sources` line, so a single broken feed neither hides the report nor passes unnoticed.

To work around a quiet day:

```sh
python cli.py run --lookback-hours 72   # widen the window instead of waiting
```

### Useful variants

```sh
python cli.py demo                    # build the bundled sample, no key needed
python cli.py run --date 2026-07-25   # file the report under another date
python cli.py run --no-images         # skip scraping, generate every card
python cli.py run --verbose           # debug level logging
python cli.py render 2026-07-25       # rebuild HTML and PNG from stored JSON
python cli.py list                    # print the stored report dates
```

`render` never calls the API, so it is the cheap way to try a layout change on an existing report.

### Overriding a setting for one run

Every setting listed under [Configuration](#configuration), except the credentials and `PORT`, can be given as an option named after its variable, which wins over the environment and `.env` for that invocation only:

```sh
python cli.py run --lookback-hours 72 --max-topics 4
python cli.py run --summarizer-backend plain --no-images
python cli.py run --summarizer-model claude-opus-4-1 --max-output-tokens 8000
python cli.py render 2026-07-25 --font-path /usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf
python cli.py list --data-dir /srv/ai-digest/reports
```

Which options a subcommand takes follows from what it does: `--data-dir` is accepted everywhere, the collection and summarization settings by `run`, and `--font-path` by the three subcommands that draw images. `cli.py run --help` lists them with the variable each one replaces, and a run that overrides anything logs what it replaced, so the log of a report says how it was produced.

`SUMMARIZER_API_KEY` and `SUMMARIZER_AUTH_TOKEN` deliberately have no option: a command line is readable by every user of the host, through `ps`, so a credential stays in the environment or in `.env`.

Values are validated by the parser, which refuses a look back window of `0` or a model name given to `--summarizer-backend`, and exits with status 2 without collecting anything.

### Browse the reports

```sh
python app.py
```

Then open `http://127.0.0.1:3000/`. `app.py` binds `127.0.0.1` and reads `PORT`,
so the development server and gunicorn answer on the same address. The routes
are:

| Route | Content |
|---|---|
| `/` | List of the stored report dates |
| `/reports/<date>` | Report of one day |
| `/reports/<date>/image` | Composite summary PNG of that day |
| `/reports/<date>/assets/<file>` | Topic illustration of that day |
| `/healthz` | Plain text liveness response |

### Output of one run

```
data/reports/2026-07-25/
├── report.json     topics, sources and run statistics
├── summary.png     composite image of the whole day
├── index.html      standalone HTML copy of the report
├── style.css       stylesheet of the standalone copy
├── topic-1.png     illustration of the first topic
└── ...
```

`index.html` is self contained, so a day can also be published by copying its directory to any static web server.

## When something fails

The batch reports a failure and exits with a status; nothing is retried behind
your back and no half written report is left in the archive. The viewer keeps
serving what is already stored, because it never depends on a run having
succeeded.

### Exit codes of `cli.py`

| Code | Meaning |
|---|---|
| `0` | The command completed. `--help` and `--version` also end here |
| `1` | The command failed: nothing was collected, no topic could be built, a credential is missing, or a setting holds a value no backend can serve |
| `2` | The command line itself was rejected by the parser, for example a count that is not a positive whole number. Nothing was collected and no request was spent |

A cron entry that mails on non-zero output turns these into the only monitoring
the batch needs. `deploy/ai-digest.cron` sets `MAILTO` for that reason.

### What a failure says

Every failure names its cause at `ERROR` level and ends the run:

| Log line | Usually means |
|---|---|
| `SUMMARIZER_BACKEND is 'X'; expected one of: ...` | A typo in a setting. The run stops before collecting, so no request is spent on it |
| `SUMMARIZER_BACKEND is 'claude', which named a vendor ...` | A value from before the rename; the message names its replacement, see [Renamed settings](#renamed-settings) |
| `ANTHROPIC_API_KEY is no longer read by ai-digest; use ...` | A setting from before the rename is still exported; see [Renamed settings](#renamed-settings) |
| `MAX_OUTPUT_TOKENS is 0; expected a positive number.` | Same, for the output budget; `SUMMARIZER_TIMEOUT` is refused the same way |
| `SUMMARIZER_API_KEY or SUMMARIZER_AUTH_TOKEN is required.` | No credential is configured, and `SUMMARIZER_BACKEND` is not `plain` |
| `no entry collected: ...` | The window held nothing, or the sources could not be reached. The message distinguishes the two; see ["no entry collected"](#no-entry-collected) |
| `summarization failed: ...` | The request was made and produced no report. The `api response:` line logged beside it says what came back |
| `Model returned no build_report tool call` | The endpoint answered without calling the tool; see [When the endpoint returns no tool call](#when-the-endpoint-returns-no-tool-call) |
| `... so the report is truncated; lower MAX_TOPICS or raise MAX_OUTPUT_TOKENS` | The answer was cut off mid-object. A truncated report is refused rather than published in part |
| `the model returned no usable topic` | The answer arrived and validated into nothing. `--verbose` dumps the whole response body |
| `no stored report for DATE` | `render` was given a date the archive does not hold |

A degraded source is a `WARNING`, not a failure. An unreachable feed, a page
that does not scrape and an image that is refused each fall back and the run
continues: `continuing with 5 of 6 sources; 1 failed (...)` is a report that was
still written.

The viewer answers `404` for an address it does not serve, for a date that is
not a date, and for a date the archive does not hold. All three are the same
answer on purpose: whether a report exists is not something an unauthenticated
request needs distinguished for it.

### The shape of a log line

Both entry points configure logging once, to standard error, with the same
format:

```text
%(asctime)s %(levelname)s %(name)s: %(message)s
```

so a failure reproduced by hand reads exactly like the one cron mailed:

```text
2026-08-05 06:30:14,882 INFO ai_digest.collectors.arxiv: collected 24 arXiv papers from 3 of 3 categories (150 papers offered, look back 24 hours)
2026-08-05 06:30:52,410 INFO ai_digest.analyzer.summarizer: api response: id=msg_01 model=claude-sonnet-4-5 stop_reason=tool_use content_types=tool_use input_tokens=8123 output_tokens=2044
2026-08-05 06:30:52,415 INFO ai_digest.analyzer.summarizer: summarized 41 entries into 6 topics
```

The `api response:` line is the one to read when a run fails: `stop_reason` and
`content_types` say whether the model called the tool, wrote text instead, or
spent the budget thinking. The response body itself is logged at `DEBUG` only,
which `--verbose` turns on, because it runs into thousands of tokens and would
swamp a cron mail.

No credential appears at any level. A missing key is reported as missing, never
quoted, and neither the key nor the token is included in a message that names a
setting.

## Tests

The suite lives in `tests/` and uses `unittest` from the standard library, so there is nothing to install beyond `requirements.txt`. Every test stubs the network and the API clients: no outbound access, no API key and no `.env` are needed, and nothing under `data/` is touched.

Run everything at once, from the repository root, with the virtual environment active:

```sh
python -m unittest discover -s tests
```

The command discovers every `tests/test_*.py` and reports one summary for all of them. It exits with status 0 only when all tests pass, which is what a cron job or a CI step should check.

The repository root must be the working directory, because the tests import the top level modules (`config`, `cli`, `ai_digest`) from there. Running a file directly as `python tests/test_config.py` fails with `ModuleNotFoundError`, since then only `tests/` lands on the import path; always go through `python -m unittest`.

Narrower selections use the same runner:

```sh
python -m unittest discover -s tests -v                          # name every test as it runs
python -m unittest tests.test_config                             # one module
python -m unittest tests.test_config.SummarizerBackendTest       # one class
python -m unittest tests.test_config.SummarizerBackendTest.test_accepts_plain
python -m unittest discover -s tests -p "test_c*.py"             # modules matching a pattern
```

| Module | Subject |
|---|---|
| `test_config.py` | environment driven settings and backend validation |
| `test_cli_options.py` | the command line overrides: one setting replaced at a time, list splitting, the absolute data directory, that every overridable name is a real field, that no credential has an option, and the values the parser refuses |
| `test_collectors.py` | arXiv and RSS collection, look back window, partial source failures |
| `test_storage.py` | report persistence, corrupt report handling, date validation, path traversal refusal |
| `test_urls.py` | accepted URL schemes and neutralization of unsafe stored links |
| `test_plain.py` | API free mechanical summarizer |
| `test_anthropic_compat.py` | Claude tool use call and its response parsing |
| `test_openai_compat.py` | OpenAI compatible tool call path |
| `test_tool_choice_and_fallback.py` | `SUMMARIZER_TOOL_CHOICE_MODE` and the fallback chain |
| `test_output_budget.py` | output token budget and truncated answers |
| `test_request_timeout.py` | the summarization timeout: its default, its refusal of a non-positive value, and that it reaches both SDKs |
| `test_resolver.py` | ar5iv figure and Open Graph scraping |
| `test_fallback.py` | line breaking of the fallback card: the configured width, an explicit break, the cap on the lines a card gets, and the ellipsis marking what was dropped |
| `test_compose_image.py` | the legend of the composite daily image: the order it keeps, the entries a narrow row drops, and the cap on how many it lists |
| `test_render_command.py` | the window a rebuilt image announces, read from the statistics the run stored rather than from the current configuration |
| `test_demo.py` | bundled demo report build |

A passing suite says nothing about the feeds or the API being reachable; those are exercised only by an actual `python cli.py run`.

## Deployment

### VPS

The viewer runs under gunicorn and systemd; the batch runs from cron. The two
share nothing but `DATA_DIR`, which is what keeps yesterday's report on the site
while a batch fails. gunicorn listens on `127.0.0.1` only, and nginx provides
HTTPS and access control.

[doc/DEPLOYMENT.md](doc/DEPLOYMENT.md) gives the complete Debian procedure:
installation, TLS, reader restrictions, the API compatibility settings, the
request budget, and the routine operations — key rotation, log rotation,
backing up the archive and rolling back.

[deploy/](deploy) holds the matching examples:

| File | Purpose |
|---|---|
| `ai-digest.service` | systemd unit for the viewer |
| `ai-digest.conf` | nginx server block, with TLS and the commented access restrictions |
| `ai-digest.cron` | crontab for the daily batch |

The archive is the one thing that cannot be rebuilt: a report is not
reproducible after the fact, because the feeds have moved on and the model would
answer differently. Back up `DATA_DIR`.

### Heroku

`Procfile` and `.python-version` are provided, so a deploy needs only the API key:

```sh
heroku create
heroku config:set SUMMARIZER_API_KEY=sk-ant-...
git push heroku main
```

The dyno file system is ephemeral. Reports written by a one off dyno disappear on the next restart or deploy, and Heroku alone therefore cannot host the daily archive. Treat a Heroku deployment as a demonstration of the viewer and run the real pipeline on a VPS or locally, where `DATA_DIR` is persistent.

## Repository Structure

```
.
├── app.py                          Flask viewer
├── cli.py                          daily batch entry point
├── config.py                       environment driven settings
├── requirements.txt
├── Procfile                        Heroku process definition
├── .python-version
├── .env.example
├── .gitignore                      generated reports, .env and Python artifacts
├── .gitattributes                  diff settings for the documents under doc/
├── ai_digest/
│   ├── __init__.py                 Entry and Topic dataclasses, category colors
│   ├── dedup.py                    title similarity based deduplication
│   ├── storage.py                  report persistence and path handling
│   ├── collectors/
│   │   ├── arxiv.py                arXiv Atom API collector
│   │   └── news_rss.py             RSS and Atom collector
│   ├── analyzer/
│   │   ├── summarizer.py           Claude tool use call
│   │   ├── openai_compat.py        OpenAI compatible tool call
│   │   └── plain.py                API free mechanical summarizer
│   ├── demo/
│   │   ├── __init__.py             bundled demo report
│   │   └── sample_input.json       its entries and build_report payload
│   ├── images/
│   │   ├── resolver.py             ar5iv figure and Open Graph scraping
│   │   └── fallback.py             locally generated topic cards
│   └── render/
│       ├── build.py                static HTML rendering
│       ├── compose_image.py        composite summary PNG
│       ├── templates/              Jinja2 templates
│       └── static/style.css
├── tools/
│   └── capture_screens.py          screenshots of the viewer
├── deploy/
│   ├── ai-digest.service           example systemd unit for the viewer
│   ├── ai-digest.conf              example nginx server block
│   └── ai-digest.cron              example crontab for the batch
├── tests/                          unittest suite, standard library only
├── data/reports/                   generated reports, not tracked
└── doc/
    ├── REQUIREMENTS.md             what the system is required to do, and why
    ├── BASIC_DESIGN.md             how those requirements are met
    ├── DEPLOYMENT.md               Debian and nginx deployment
    ├── DEMO.md                     demo mode and the screenshots
    ├── POLICY.md                   implementation policy
    ├── VERSIONS                    repository version history
    ├── screenshots/                images embedded in this README
    ├── LICENSE.md
    ├── COPYING
    └── COPYING.LESSER
```

`tools/capture_screens.py` is a documentation helper. It is not imported by the application, and `playwright`, which only that script needs, is deliberately absent from `requirements.txt` so that neither the batch nor the viewer pulls in a browser.

`app.py` imports nothing from `ai_digest.collectors` or `ai_digest.analyzer`. That is what keeps the viewer free of a credential and of outbound access: it cannot call an API because it does not carry the code that would.

### Adding a collector

`ai_digest/collectors/` holds everything that knows where the material comes
from. Above it, the pipeline works from a list of `Entry` objects and does not
care which source produced them.

1. Write `ai_digest/collectors/<name>.py` exposing
   `collect(..., lookback_hours, timeout, user_agent) -> CollectionResult`,
   filling `Entry` with `source_type`, `title`, `url`, `summary`, `published`
   (ISO 8601, UTC) and `origin`.
2. Export it from `ai_digest/collectors/__init__.py`.
3. Call it in `collect_entries()` in `cli.py`, and add its settings to
   `config.py`, to `.env.example` and to the table under
   [Configuration](#configuration).

Two rules are not negotiable, because the whole pipeline rests on them:

- **`collect()` never raises on a network error.** A source that cannot be
  reached contributes nothing, records its failure in the `CollectionResult` and
  lets the run continue. One misbehaving source must not end a run whose other
  sources answered.
- **Every request carries a timeout and the configured User-Agent.** An
  unattended run must not hang until the next one starts, and a host reading its
  own logs is entitled to know who is calling.

Nothing else changes. `dedup.py`, the summarizers, the image resolver and the
renderers are untouched by a new source, which is the point of `Entry`: what a
topic has to look like is not a property of where its material came from.

## The Japanese that stays

The repository is written in English — the code, the comments, the log messages
and the documents. The report is Japanese, because that is what it is for, and
four places carry Japanese as data rather than as text that happens to be
translated:

| Where | Why |
|---|---|
| `ai_digest/analyzer/summarizer.py` | `SYSTEM_PROMPT` and `build_prompt()` ask the model for Japanese titles, bullets and category labels. It is the instruction, so it is written in the language of the answer |
| `ai_digest/render/templates/` | The pages are `lang="ja"`: the viewer shows a Japanese report to a Japanese reader |
| `ai_digest/render/compose_image.py` | The headings, the legend and the disclaimer drawn into the composite image are the image's own text, not the model's, so they are written here |
| `ai_digest/analyzer/plain.py`, `ai_digest/images/fallback.py` | Japanese sentence enders in the sentence splitting pattern, and a Japanese glyph measured to size a line of text. They are load bearing: an English substitute would split the wrong sentences and measure the wrong height |
| `config.py` | One macOS CJK font path among the probed locations |

The screens being Japanese is the difference from a repository whose output is
Japanese but whose interface is not. Here the reader of the site and the reader
of the report are the same person.

## Demo and sample output

### Demo mode

```sh
python cli.py demo
python app.py
```

The demo builds a report from the sample bundled in `ai_digest/demo/`. It collects nothing and calls no API, so it runs on a fresh clone with neither a key nor outbound access, and it is the quickest way to see what a finished report looks like. The result is a normal report under `data/reports/`, which the viewer lists next to the collected ones and marks with `"model": "demo"` in its statistics.

```sh
python cli.py demo --date 2026-08-01   # file it under another date
python cli.py demo --input mine.json   # use another sample
```

The date defaults to the one recorded in the sample, so repeated runs overwrite the same directory. Delete `data/reports/<date>/` to remove the demo again. [`doc/DEMO.md`](doc/DEMO.md) describes what the demo replaces and how it differs from a collected report.

This is not the same as `SUMMARIZER_BACKEND=plain`, which still collects from the network and only skips the API; see [Standalone use, no API key](#standalone-use-no-api-key).

### Sample output

The composite PNG written for one day. It is drawn with Pillow rather than screenshotted from the HTML, so the batch needs no headless browser:

![Composite summary image of one day](doc/screenshots/summary.png)

The same day in the Flask viewer, which shows the composite image first and then one card per topic, each with its category label, its bullet points and its sources:

![Report page of the viewer](doc/screenshots/report-desktop.png)

The archive index, the entry point of the viewer:

![Archive index of the viewer](doc/screenshots/index-desktop.png)

These pages were captured from a demo run, so they can be reproduced without a key and without collecting anything:

```sh
python cli.py demo          # build the bundled sample report
python app.py               # browse it at http://127.0.0.1:3000/
```

See [Demo mode](#demo-mode) above and [`doc/DEMO.md`](doc/DEMO.md), which states exactly which two stages the demo replaces and how it differs from a collected report.

## Contribution

Contributions are welcome. You can help by:

- Adding collectors for further sources
- Improving the layout of the composite image
- Reporting bugs or feature requests

Please follow the style used in this repository: module level header comments describing purpose, requirements and version history, English comments, and documentation updated together with the code.

## License

This repository is dual licensed under the [GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html) or the [LGPL version 3](https://www.gnu.org/licenses/lgpl-3.0.html), at your option.
For full details, please refer to [doc/LICENSE.md](doc/LICENSE.md). See also [doc/COPYING](doc/COPYING) and [doc/COPYING.LESSER](doc/COPYING.LESSER) for the complete license texts.
