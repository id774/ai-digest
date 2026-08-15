# Basic design: a daily AI digest

## 1. Purpose

This document states how the requirements in
[`REQUIREMENTS.md`](REQUIREMENTS.md) are met: what the system is composed of,
what each part is responsible for, how one run and one page proceed, and what is
stored between them.

It does not restate why anything is required, and it is not a walkthrough of the
source. Where a procedure is already written down — installing, operating,
diagnosing — it is named rather than copied: [`DEPLOYMENT.md`](DEPLOYMENT.md)
holds the deployment, [`DEMO.md`](DEMO.md) the bundled sample, and
[`POLICY.md`](POLICY.md) the rules a change is judged against. Where this
document and `POLICY.md` describe the same constraint, `POLICY.md` is the one a
change is measured against.

## 2. Design policy

Six decisions shape everything below.

- **Two processes, one directory.** The batch writes, the viewer reads. The
  viewer cannot call an endpoint because it does not import the code that would,
  which is a stronger guarantee than a rule saying it must not.
- **The archive is plain files.** One directory per day, JSON and PNG. Anything
  that can read a file can read the archive.
- **Two structures are the whole internal interface.** Everything below the
  collectors works from `Entry`, everything above the summarizers works from
  `Topic`. That is what makes a new source a change to one directory.
- **The model answers into a schema, and the application owns the facts.** The
  answer is the arguments of a declared tool call; citations come back as input
  item numbers and the real URLs are restored from collected data.
- **Settings are resolved once, from the environment, in `config.py`.** No module
  below reads `os.environ`, and every batch setting also has a command line
  option.
- **Failure degrades where the material is optional and stops where the
  configuration is wrong.** A source, a scrape and an image each fall back; a
  setting the code has no branch for ends the run before any work is spent.

## 3. Composition

The system separates into stages that each own one concern:

```text
   arXiv ─┐
          ├─ collect ─ normalize ─ deduplicate ─ edit into topics ─ verify
   feeds ─┘                                                    citations
                                                                    │
                                                                    v
                                                              illustrate
                                                                    │
                                                                    v
                                                              persist
                                                              ├─ report.json
                                                              ├─ index.html
                                                              ├─ style.css
                                                              └─ *.png
                                                                    │
                                                                    v
                                                                 viewer
```

Mapped onto processes:

```text
             cron (once a day)              systemd
                    |                          |
                    v                          v
                 cli.py                     gunicorn
        the pipeline above, then exit       └─ app.py, read only
                    |                          |     no credential
                    |         DATA_DIR         |
                    +------>  one dir per  <---+
                              day
                            config.py
              every setting, resolved once, from the
                environment and an optional .env
```

Both entry points call the same settings loader and nothing else configures
either. The batch is the only writer of `DATA_DIR`, and the viewer opens no file
whose path it did not get from `ai_digest/storage.py`.

## 4. Repository layout

```text
.
├── cli.py                   the daily batch: subcommands, options, the pipeline
├── app.py                   the viewer: five routes, read only
├── config.py                every setting, resolved once from the environment
├── requirements.txt         what the batch and the viewer need, and no more
├── .env.example             the settings, with no value that is a credential
├── ai_digest/
│   ├── __init__.py          Entry, Topic, CollectionResult, link guard, colors
│   ├── dedup.py             mechanical duplicate removal
│   ├── storage.py           every path computation, and the report format
│   ├── collectors/          where material comes from
│   │   ├── arxiv.py         the arXiv Atom API
│   │   └── news_rss.py      RSS and Atom feeds
│   ├── analyzer/            how material becomes topics
│   │   ├── summarizer.py    the prompt, the tool schema, the validation
│   │   ├── openai_compat.py the second wire protocol, sharing all three
│   │   └── plain.py         no model, no credential
│   ├── images/              one illustration per topic
│   │   ├── resolver.py      taken from the source, best effort
│   │   └── fallback.py      drawn locally, and the shared text helpers
│   ├── render/              what is published
│   │   ├── build.py         standalone HTML
│   │   ├── compose_image.py the daily summary PNG
│   │   ├── templates/       shared by the batch and the viewer
│   │   └── static/style.css
│   └── demo/                a complete report from bundled data
├── tools/capture_screens.py a documentation helper, not part of the app
├── deploy/                  systemd, nginx and cron examples
├── tests/                   unittest, offline, standard library runner
├── data/reports/            the archive, not tracked
└── doc/                     these documents
```

Two absences are deliberate. The documentation helper needs a browser driver and
the second wire protocol needs a second API client; neither is in
`requirements.txt`, so a default installation carries neither.

## 5. The common item form

Source specific structure is absorbed inside a collector. Above it, one
structure carries a collected item:

| Field | Holds |
|---|---|
| `source_type` | `paper` or `news` |
| `title` | the original title, usually English |
| `url` | the canonical URL of the item |
| `summary` | the abstract or feed summary, as plain text |
| `published` | the publication timestamp, ISO 8601, UTC |
| `origin` | a readable origin, such as the arXiv category or the feed title |

Nothing above the collectors knows that arXiv answers Atom or that a feed may be
RSS. A topic likewise carries only what a report needs: category, Japanese
title, bullets, sources as title and URL pairs, the image file name and where
the image came from.

A third structure carries the *outcome* of a collection pass beside its entries
— how many sources were asked, how many failed, how many items they offered, how
many fell outside the window, and one reason line per failure. That is what lets
the batch tell an unreachable network from a quiet weekend without guessing, and
two passes merge into one outcome so the pipeline sees a single result.

## 6. Collection

arXiv and the news feeds are separate collectors with the same shape and the
same two rules.

- **A collector never raises on a network error.** A source that cannot be read
  contributes nothing, records its reason in the outcome, and lets the run
  continue. One misbehaving source never invalidates the others.
- **Every request carries a timeout and the configured User-Agent.**

**arXiv** is queried once per category, sorted newest first, so the age filter
can stop as soon as older entries appear rather than reading a whole page of
results. Requests are spaced to stay inside the rate the API asks for.

**Feeds** are fetched with the HTTP client rather than handed to the parser by
URL, so that the timeout and the User-Agent apply to every source. Markup is
stripped from summaries and their length is capped, because a feed summary is
sometimes the whole article and only its beginning is useful for judging it.

Both drop an item whose link is not an ordinary absolute web URL, so an unsafe
scheme never enters the archive in the first place.

### Time normalization

Parsed publication timestamps are read as **UTC**, which is what the feed parser
returns, and compared against a UTC cut-off derived from the configured window.
Neither collector consults the host's local time zone, so the window is the same
number of hours on every host.

The same setting travels onward — into the prompt, the HTML, the summary image
and the stored statistics — so the window that was applied and the window that
is announced cannot drift apart.

## 7. Mechanical deduplication

Applied to the merged entries before any model is involved, and before the
candidate cap of section 8.

- **Exact URL match** — the first occurrence is kept.
- **Title similarity** — titles are reduced to a comparison key by NFKC
  normalization, case folding, and dropping everything that is neither a letter
  nor a digit, which absorbs full width and half width forms, case, punctuation
  and runs of whitespace. Two keys are the same story when a sequence match
  ratio reaches **0.85**, or when they are identical.

The first occurrence survives, so **input order decides the winner**: the
pipeline collects papers before news, which makes the paper outrank the
reporting about it.

This is a low cost pre-filter, not a semantic judgement. It removes unmistakable
repetition and leaves everything else to the topic editing stage, which is what
section 10 of the requirements asks for.

## 8. The topic editing interface

Topic editing is one interchangeable stage with a fixed contract:

```text
  input   deduplicated entries, in order of preference
  output  a list of topics
```

Every backend satisfies it, so the illustration, storage and rendering stages
never learn which produced the report. A backend is selected by
`SUMMARIZER_BACKEND`, and exactly one runs per invocation — the backends are two
explicit routes plus a mechanical one, never a failover chain.

| Backend | Editing |
|---|---|
| `anthropic-compatible` | a Messages API tool call — the default |
| `openai-compatible` | a Chat Completions tool call |
| `plain` | mechanical, no model and no credential |

**Both API backends cap the candidates at 60 entries** before building the
request, taking them in the order deduplication left them — papers first, then
news, each newest first within its source. Ordering and truncation are part of
the design because they decide what the model is able to consider at all. The
mechanical backend applies no candidate cap, since it selects by date directly.

## 9. The model backends

`summarizer.py` owns the material both API routes share: the system prompt, the
prompt builder, the `build_report` tool schema, and the validation. The
OpenAI-compatible module imports all four, translates the tool definition into
the other protocol's function-tool form, reads the answer from the tool call
arguments, and validates identically — so **a report does not differ by the
route it took.** Its SDK is imported inside the call, because only that backend
needs it.

### What the model is asked for

The prompt numbers every candidate and asks for topics in decreasing importance.
The tool schema requires four fields per topic:

| Field | Asked for |
|---|---|
| `category` | a short Japanese label suited to the day, not from a fixed list |
| `title` | a Japanese headline, within 40 characters |
| `bullets` | 2 to 4 Japanese bullets, each one sentence within 60 characters |
| `source_indexes` | the numbers of the input items it rests on, most important first, up to 3 |

The prompt names the configured window and the configured topic count, because a
prompt announcing a window the request does not carry describes material the
model cannot see.

### Compatibility settings

Endpoints that speak a protocol do not all behave like the vendor that defined
it, so three behaviours are named settings rather than inferred:

| Setting | Shapes |
|---|---|
| `SUMMARIZER_THINKING_MODE` | whether a thinking parameter is sent at all |
| `SUMMARIZER_TOOL_CHOICE_MODE` | whether the tool is named, merely demanded, or left to the model |
| `SUMMARIZER_TEXT_JSON_FALLBACK` | whether a report written as JSON text is read when no tool call came back |

The defaults leave the request unchanged from what the reference implementation
expects. The text fallback stays off until a raw response has shown that an
endpoint really answers that way, and a run that takes it logs a warning naming
the setting that allowed it.

### The mechanical backend

Each deduplicated entry becomes one topic. Entries are ordered by publication
time, newest first, and taken up to the topic limit. The title is the original,
unchanged. Bullets are the summary split into sentences — on both English and
Japanese terminators — capped at 4 and truncated with an ellipsis beyond 160
characters, falling back to the title when a summary yields nothing. The
category is the entry's origin: the arXiv category for a paper, the feed for an
article.

The difference from the API backends is confined to this stage and nowhere else.

## 10. Validating the answer and restoring citations

The parsed tool arguments pass through **one validation function**, which every
backend and the bundled sample share, so nothing is stored on the strength of a
model's word.

It enforces, in order:

- topics beyond the configured limit are dropped;
- bullets are whitespace-normalized, non-strings and blanks discarded, and the
  remainder capped at 4;
- **each source index must be an integer inside the range of the candidate
  list**; anything else is ignored;
- **a topic with no usable bullet, or no usable source, is dropped** with a
  logged warning;
- a missing or blank category becomes a neutral label rather than an empty one.

Citation restoration is the point of the index scheme:

```text
   model        returns source_indexes  ->  [3, 17]
   application  looks them up in the candidate list it sent
                takes each entry's real title and url
                writes those into the topic
```

The model never supplies a URL, so it cannot invent one, and an index pointing
outside the candidate list simply yields no source. A topic that loses all of
its sources this way is dropped rather than published without provenance.

An answer carrying no usable topic at all is a failed run, not an empty report.

## 11. Illustration

Per topic, the sources are tried in order until one yields an image; otherwise a
card is drawn.

The resolver reads the figure of a paper from its HTML rendering, or the image an
article declares for social sharing. Three bounds are enforced **while reading**
rather than after buffering — a cap on page bytes, a cap on image bytes, and a
minimum side below which an image is not worth showing — and a decoder refusing
an image is an ordinary "no image" rather than the end of a run.

The fallback draws a panel in the category colour with the label and the
headline wrapped to the width, and it also owns the font loading, measuring and
wrapping helpers the summary image reuses. It is where the missing-CJK-font
warning is emitted once; without such a font the HTML stays correct and only the
images lose their text.

Every topic ends this stage with an image file name and a credit recording which
of the two routes produced it.

## 12. Persistence

`ai_digest/storage.py` owns **every path computation of the application** and
the report format.

```text
<DATA_DIR>/<YYYY-MM-DD>/report.json    the structured record of the day
<DATA_DIR>/<YYYY-MM-DD>/summary.png    the daily summary image
<DATA_DIR>/<YYYY-MM-DD>/topic-N.<ext>  one illustration per topic
<DATA_DIR>/<YYYY-MM-DD>/index.html     the standalone copy
<DATA_DIR>/<YYYY-MM-DD>/style.css      its stylesheet
```

`report.json` is the authoritative record; the HTML and the images are derived
from it and are kept in the same directory.

```json
{
  "date": "2026-07-25",
  "topics": [
    {
      "category": "...",
      "title": "...",
      "bullets": ["...", "..."],
      "sources": [{"title": "...", "url": "https://..."}],
      "image": "topic-1.png",
      "image_credit": "generated"
    }
  ],
  "stats": {
    "collected": 41,
    "deduplicated": 38,
    "topics": 6,
    "model": "...",
    "lookback_hours": 24,
    "generated_at": "2026-07-25T21:30:14+00:00"
  }
}
```

`stats.model` records how a report was produced — a model name, `plain`, or
`demo` — which lets all three kinds of day sit in one archive as one format.

Two properties of this module carry weight:

- **The date pattern is anchored** so that a trailing newline cannot make a date
  from a URL name a directory of its own.
- **The reader is defensive.** A missing file, an unreadable one, a syntax
  error, a payload that is not a mapping, topics that are not a list of
  mappings, statistics that are not a mapping, or a topic that will not rebuild
  all mean "no report". The viewer turns that into a 404, so one corrupt day
  cannot take the archive down.

Listing returns only directories that are named like a date *and* hold a report,
newest first.

## 13. HTML and the summary image

Both are generated from the stored topics, so the page and the image cannot be
assembled from different material.

The HTML renderer uses the same templates as the viewer and copies the
stylesheet beside the output; one flag decides whether asset URLs point at
neighbouring files or at the viewer's routes. Autoescaping and the link filter
are registered where the environment is created, and the viewer registers the
same two on its own, so both escape by identical rules.

The summary image is drawn directly with Pillow rather than screenshotted from
HTML, which is what keeps a browser out of the dependencies, at the cost of
computing the layout instead of leaving it to a CSS engine. It carries a header
with the date and the configured window, a legend mapping each category to its
colour, a three column grid of numbered cards, and a footer with the run's
metadata and a disclaimer. Legend entries are chosen before they are drawn, so a
row too narrow for every category drops the trailing ones rather than the
leading, most important ones. Three columns is why six topics fills the grid
exactly.

Category colour is derived from the label by a hash written in the package
rather than the builtin one, which is salted per process and would recolour the
archive on every restart.

## 14. The batch

Four subcommands:

| Subcommand | Does |
|---|---|
| `run` | the whole pipeline for one date |
| `demo` | the same from the bundled sample, collecting nothing and calling nothing |
| `render` | rebuild the HTML and the image from a stored report |
| `list` | print the stored dates |

`--version` and `--help` print and exit. Every setting except the two
credentials and the viewer's port also has an option named after its variable,
applied over the resolved settings for one invocation; a test asserts that every
overridable name is a real settings field and that no credential appears among
them. Which options a subcommand takes follows from what it does: the archive
directory everywhere, the collection and endpoint settings on `run`, the font on
the three subcommands that draw. A run that overrode something logs what it
replaced, so the log of a report says how it was produced.

### One run, in order

1. **Validate the settings the selected backend needs** — the backend name
   first, then the credential, model, retry budget, output budget and timeout,
   and for the anthropic-compatible backend the three protocol options. Nothing
   has been collected and no request spent at this point.
2. **Collect**, papers then news, merged into one outcome.
3. **Nothing collected?** Log which of the four cases it was, and fail.
4. **Some sources failed?** Warn, naming how many, and continue.
5. **Deduplicate.**
6. **Edit into topics** through the selected backend. Any exception — network,
   quota, protocol alike — is a logged summarization failure. An answer that
   validates into no topic fails too.
7. **Create the report directory**, only now that there is something to put in
   it.
8. **Illustrate**, so that the stored topics carry their image file names.
9. **Store** `report.json` with the topics and the run statistics.
10. **Render** the summary image and the standalone HTML.
11. **Succeed.**

`demo` enters at step 7 with topics built from the sample and validated by the
same function. `render` enters at step 10 with topics loaded from storage, which
is why it costs nothing and is the cheap way to try a layout change; the window
it announces is read from the statistics the original run stored, not from the
current configuration, so a rebuild does not relabel history.

### The sample

The bundled sample replaces exactly the two stages that need outbound access —
collection, and topic editing — and nothing downstream. Its payload is the tool
call arguments a live endpoint would have returned, so it goes through the same
validation, and it is data rather than a recording of one response, so a demo
run costs nothing and renders identically everywhere. `--data-dir` directs the
output somewhere other than the real archive. [`DEMO.md`](DEMO.md) states what
it replaces and how it differs from a collected report.

## 15. The viewer

Five routes, no credential, no outbound access, nothing that writes:

| Route | Serves |
|---|---|
| `/` | the stored dates, newest first |
| `/reports/<date>` | one report, rendered from its JSON |
| `/reports/<date>/image` | the summary image of that day |
| `/reports/<date>/assets/<file>` | one illustration of that day |
| `/healthz` | a plain text liveness response |

It imports nothing from the collectors or the analyzers. **That absence is the
design**: the viewer cannot call an endpoint because it does not carry the code
that would.

One page is: validate the date, load the stored report, 404 when it is missing
or corrupt, rebuild the topics, render through the autoescaping environment with
every link passed through the guard. There is no query, no cache and no state
between requests — one settings object resolved at import, and the file system
for everything else.

A missing route, an invalid date and an absent report are all the same 404,
because whether a report exists is not something an unauthenticated request needs
distinguished for it.

## 16. Settings

Resolved once from the environment, with an optional `.env` read underneath it,
so that **an exported variable takes precedence over the file**. Command line
options sit above both and apply to one invocation:

```text
   command line option  >  exported environment variable  >  .env  >  default
```

The settings module performs no network access and touches no file beyond
`.env`, so it is safe to import anywhere. Beyond holding values it does three
things.

- **Refuses superseded names.** A variable from before the `SUMMARIZER_*` rename
  is refused with its replacement named, and *presence* is refused rather than
  value — an exported but empty one still says the host was set up for the old
  names. The check runs in the loader, so it stops the viewer as well as the
  batch: a host part way through a rename is exactly the one where an old name
  still decides something, and a viewer that kept serving would hide that.
  Superseded backend values are answered the same way.
- **Validates by concern, on demand.** Backend, credential, model, retry budget,
  output budget, timeout and protocol options are separate checks, and the batch
  calls the ones the selected backend needs before collecting.
- **Resolves the font**, honouring the explicit setting and otherwise probing the
  usual CJK locations for the first that exists.

One defaulting decision lives here: the anthropic-compatible backend falls back
on a known model where none is configured, the openai-compatible one has nothing
to fall back on, and the empty value travels to the validator that refuses the
run by name.

### Request budgets

Two timeouts, because they measure different things: `HTTP_TIMEOUT` bounds one
collector or scraper request, and `SUMMARIZER_TIMEOUT` bounds one summarization
request. The second is the longer because the answer is not streamed — what is
being waited for is the writing rather than the network. Retries multiply it:

```text
worst case wait = SUMMARIZER_TIMEOUT x (SUMMARIZER_MAX_RETRIES + 1)
```

Neither may be zero or negative, and `run` refuses such a value before
collecting. The full table of settings and defaults is in the README.

## 17. Failure isolation and exit status

Isolation is arranged per stage: a collector localizes failure to one source, the
image stage localizes it to one topic through the fallback card, validation
localizes a malformed answer to one topic, the mechanical backend allows
operation with no endpoint at all, and the viewer keeps serving stored days
while a run fails.

| Situation | Result |
|---|---|
| one source unreachable | warning, run continues, report written |
| a page that will not scrape | warning, a card is drawn |
| an image refused or too large | a card is drawn |
| one malformed topic in the answer | warning, that topic dropped |
| no CJK font installed | one warning, images lose text, HTML stays correct |
| every source unreachable | error, run fails |
| no item inside the window | error, run fails |
| no usable topic after editing | error, run fails |
| a structured answer that cannot be read | error, run fails |
| a setting the code has no branch for | error before collecting, run fails |

| Exit code | Meaning |
|---|---|
| `0` | the command completed; `--help` and `--version` end here too |
| `1` | the command failed: nothing collected, no topic, a missing credential, or a setting no backend can serve |
| `2` | the command line was rejected by the parser; nothing collected, no request spent |

Exit 2 is the parser's, which is what makes a typo in an option cost nothing.
Exit 1 always follows a logged error naming the cause. A schedule entry that
mails on non-zero output turns these into the only monitoring the batch needs.

## 18. Logging

Both entry points configure logging once, to standard error, in one format, so
that a failure reproduced by hand reads exactly like the one that was mailed.
Status never goes to standard output.

The line recording what an endpoint answered — its stop reason and content types
— is at info level, because it is the line an operator reads when a run fails.
The response body is at debug level only, because it runs to thousands of tokens
and would swamp a mail. No credential appears at any level.

## 19. Security design

Four measures, each in one place so that none can be half applied.

- **Untrusted text is material.** Feed entries, scraped pages, abstracts and
  model answers are quoted into a prompt or stored as data, never followed as
  instructions.
- **Untrusted text is not markup.** Both renderers escape by the same rules and
  never bypass escaping.
- **Links are guarded twice.** The collectors refuse to store one that is not an
  absolute ordinary web URL, and the template filter neutralizes one that is
  already stored, so a report written before the filter existed, or edited by
  hand, cannot put another scheme into an anchor.
- **Paths are computed in one module**, and a date from a URL is validated
  before it names a directory.

The credential is needed by the batch alone and is read from the environment or
`.env` only, never from an option. The application provides no authentication of
its own; restricting who may read the viewer belongs to the reverse proxy, which
is where the deployment examples put it.

## 20. Deployment shape

Enough to understand the structure; the procedure is
[`DEPLOYMENT.md`](DEPLOYMENT.md).

```text
   cron ──> cli.py run ──> writes DATA_DIR
                              ^
                              │ reads
   nginx ──> gunicorn ──> app.py
```

An unprivileged dedicated user, a virtual environment, the batch on a schedule,
the viewer under an application server bound to localhost, a reverse proxy in
front for TLS and access control, a persistent `DATA_DIR`, and log rotation.
`deploy/` holds the three examples this shape needs — a unit, a server block and
a crontab — and nothing else.

**The two share nothing but `DATA_DIR`**, which is what keeps yesterday's report
on the site while a batch fails.

### Backup

`DATA_DIR` is the unit of history. Feeds change what they publish and a model's
answer is not deterministic, so a past report cannot be assumed reproducible;
keeping a day means backing up the generated data rather than planning to
regenerate it.

## 21. Test design

The suite runs on the standard library's runner from the repository root, and
every test stubs the network and the API clients: no outbound access, no
credential, no `.env`, and nothing under the archive touched.

The modules map onto this design one for one — settings and backend validation,
the command line overrides, collection and partial failure, persistence and its
refusals, link schemes, each of the three backends, the protocol options and the
fallback chain, the output budget, the request timeout, scraping, the card's
line breaking, the summary image legend, the window a rebuild announces, and the
sample. A passing suite says nothing about the sources or the endpoint being
reachable.

## 22. Mapping to the requirements

| Requirement | Where it is met |
|---|---|
| §7 sources and the window | the two collectors; the window setting carried into prompt, HTML, image and statistics |
| §7 time zone correctness | timestamps read as UTC, compared against a UTC cut-off |
| §8 the daily process | the eleven ordered steps of §14, with the report directory created last-but-four |
| §9 citations | the index scheme and its restoration in §10 |
| §10 deduplication | §7 mechanically; the model for the rest |
| §11 topic editing | the tool schema and the shared prompt in §9 |
| §12 display limits | 60 candidates, 6 topics, 4 bullets, 3 citations, enforced at validation |
| §13 categories | freely chosen labels; colour from a package-local hash |
| §14 illustrations | resolver then fallback card, per topic |
| §15 running without a model | the mechanical backend and the bundled sample |
| §16 the endpoint | one backend per run; strict settings and refused legacy names |
| §17 what is produced | the five artifacts per day in §12 |
| §18 browsing | the viewer, reading stored data only |
| §19 failure | the isolation table and the exit codes in §17 |
| §20 records | the statistics block of `report.json` |
| §22 configuration | the precedence chain and the two budgets in §16 |
| §23 security | the four measures in §19 |
| §24 operation | the deployment shape and the backup unit in §20 |
| §25 tests | §21, offline by construction |
