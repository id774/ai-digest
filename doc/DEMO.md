# Demo mode

`python cli.py demo` builds a report from data shipped with the
repository. It collects nothing, calls no API and needs no key, so a
fresh clone can show what a finished report looks like before anything
is configured.

## Running the demo

```sh
python cli.py demo
flask --app app run
```

Then open `http://127.0.0.1:5000/` and follow the date in the archive
index. The demo writes a normal report into `DATA_DIR`, so the viewer,
the standalone `index.html` and the composite `summary.png` all work as
they do for a collected report.

Options:

```sh
python cli.py demo --date 2026-08-01   # file it under another date
python cli.py demo --input mine.json   # use another sample
python cli.py list                     # confirm it was stored
```

The date defaults to the one recorded in the sample, so repeated runs
overwrite the same directory instead of filling the archive. Delete
`data/reports/<date>/` to remove the demo again.

## What the demo replaces

Everything that shapes the output is the pipeline itself. Only the two
stages that need outbound access are replaced:

| Stage | `cli.py run` | `cli.py demo` |
|---|---|---|
| Collection | arXiv API and the news feeds | the `entries` array of the sample |
| Summarization | a `build_report` tool call to the Claude API | the `build_report` object of the sample |

The stored payload goes through `summarizer.to_topics()`, the same
validation a live tool call passes, and the topics are then illustrated,
stored and rendered by the same code as any other report. `report.json`
records `"model": "demo"`, which distinguishes a demo from a collected
report in the archive.

The sample lives in
[`ai_digest/demo/sample_input.json`](../ai_digest/demo/sample_input.json).
Its Japanese titles, bullets and category labels were written by Claude
and checked in rather than requested on every run, so the demo costs
nothing, works offline and renders identically on every machine.

## How the demo differs from a live report

Two differences are visible on screen and are worth knowing before
reading the demo as a preview of your own runs:

- **The entries are landmark papers, not a day of arXiv.** They are real
  and every URL resolves, but they span 2017 to 2023 instead of the last
  24 hours. A live report covers one day and reads accordingly.
- **Every illustration is a generated card.** The demo never scrapes, so
  `attach_images()` falls back to Pillow for all six topics, which is
  why each card repeats the headline of its topic. A live run first
  tries the `ar5iv` figure of a paper or the Open Graph image of an
  article, and only falls back when that fails.

A CJK font is required all the same, since the cards and the composite
image draw Japanese text; see [Japanese font](../README.md#japanese-font).

## Screenshots

The images under [`doc/screenshots/`](screenshots) were captured from a
demo run by `tools/capture_screens.py`, which starts the read only
viewer on a loopback port and drives a headless Chromium over it.
Playwright is not in `requirements.txt`, because neither the batch nor
the viewer needs a browser:

```sh
pip install playwright && playwright install chromium
python tools/capture_screens.py
```

The script renders whatever the archive holds and never calls the API
itself, so a collected report replaces the screenshots with no further
work:

```sh
python cli.py run                 # needs ANTHROPIC_API_KEY
python tools/capture_screens.py   # captures the newest report
```

Use `--date` to capture an older report instead of the newest one.
