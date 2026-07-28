# Sample report

This directory holds the input of the sample report shown in the
screenshots under [`doc/screenshots/`](../screenshots), together with an
account of how those screenshots were produced.

## What the screenshots show

Everything that shapes the output is the application's own code. The
report was written by `tools/make_sample_report.py`, which calls the
same `_to_topics()` validation, the same Pillow card generator, the same
composite image renderer and the same Jinja2 templates as `cli.py run`,
and the pages were captured from the real Flask viewer by
`tools/capture_screens.py`.

Two stages were replaced, because both need the network:

| Stage | In the batch | In the sample |
|---|---|---|
| Collection | arXiv API and the news feeds | the `entries` array of `sample_input.json` |
| Summarization | a `build_report` tool call to the Claude API | the `build_report` object of `sample_input.json` |

The Japanese titles, bullets and category labels in `build_report` were
written by Claude and checked in, rather than fetched through the API on
every rebuild. The sample therefore illustrates the shape and the
register of the output, not a particular API response: it costs nothing
to rebuild, needs no key, and renders identically on every machine.

Two consequences are visible in the screenshots and are worth knowing
before reading them as a preview of your own runs:

- **The entries are landmark papers, not a day of arXiv.** They are real
  and every URL resolves, but they span 2017 to 2023 instead of the last
  24 hours. A live report covers one day and reads accordingly.
- **Every illustration is a generated card.** The sample never scrapes,
  so `attach_images()` falls back to Pillow for all six topics, which is
  why each card repeats the headline of its topic. A live run first
  tries the `ar5iv` figure of a paper or the Open Graph image of an
  article, and only falls back when that fails.

## Rebuilding the sample

Needs no API key and no outbound access:

```sh
python tools/make_sample_report.py
pip install playwright && playwright install chromium
python tools/capture_screens.py
```

The first command writes the report into `DATA_DIR` like any other
report, so the viewer lists it next to the real ones; the second and
third capture the pages into `doc/screenshots/`. Pass `--data-dir` to
keep the sample out of the working archive.

## Replacing the sample with a run of your own

`tools/capture_screens.py` renders whatever the archive holds and never
calls the Claude API itself, so a real report replaces the sample with
no further work:

```sh
python cli.py run                 # needs ANTHROPIC_API_KEY
python tools/capture_screens.py   # captures the newest report
```

Use `--date` to capture an older report instead of the newest one.
