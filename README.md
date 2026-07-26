# ai-digest

## Overview

**ai-digest** collects AI related papers and news once a day, summarizes and classifies them in Japanese with the Claude API, and publishes the result as a browsable HTML report together with a single composite PNG image.

The batch pipeline and the web viewer are separate processes. `cli.py` performs the daily collection and generation, writes everything under `data/reports/<date>/`, and exits. `app.py` is a read only Flask application that serves what the batch already produced, so a failed or slow run never takes the site down and the web process needs no API key.

Every topic carries an illustration. The application first tries to obtain a real image from the source, an `ar5iv` figure for arXiv papers or the Open Graph image for news articles, and draws a card locally with Pillow when that fails. Scraping is best effort by design; a publisher changing its markup degrades the look of the report, never its availability.

## Features

- **Daily pipeline in a single command**: collect, deduplicate, summarize, illustrate, render
- **Structured summarization**: the Claude API is called through tool use, so the answer is validated JSON rather than prose
- **Japanese output**: English sources are translated and condensed into two to four bullet points per topic
- **Free form categories**: labels are chosen by the model per day, and colors are derived from the label so that they stay consistent within a report
- **Resilient image handling**: scraping is attempted first and falls back to locally generated cards
- **One image per day**: a composite PNG summarizing the whole report, drawn with Pillow, without a headless browser
- **No database**: reports are plain JSON and PNG files under one directory per day
- **Deployable as is**: `gunicorn` and a `Procfile` for Heroku, `systemd` and `cron` for a VPS

## Requirements

- Python 3.9 or later
- An Anthropic API key with access to the Claude Messages API
- A CJK capable TrueType font, for example the `fonts-noto-cjk` package; see [Japanese font](#japanese-font)
- Outbound HTTPS access to `export.arxiv.org`, the configured feeds and the Anthropic API

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

At minimum, set `ANTHROPIC_API_KEY`. The file is listed in `.gitignore` and must never be committed. Variables already exported in the shell take precedence over `.env`, which is what allows a systemd unit or a PaaS to provide the key without a file.

### 5. Verify the installation

```sh
python cli.py --version
python cli.py list
```

The first command prints the version, the second prints nothing on a fresh installation because no report exists yet.

## Configuration

All settings are read from environment variables, optionally through `.env`. They are collected in `config.py`.

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | none | Claude API key. Required by `cli.py run`, unused by the viewer. |
| `ANTHROPIC_MODEL` | `claude-sonnet-4-5` | Model used for summarization. |
| `ARXIV_CATEGORIES` | `cs.AI,cs.LG,cs.CL` | arXiv categories to collect, comma separated. |
| `ARXIV_MAX_RESULTS` | `60` | Maximum entries fetched per category. |
| `NEWS_FEED_URLS` | three AI blogs | RSS or Atom feeds to collect, comma separated. |
| `LOOKBACK_HOURS` | `24` | Age limit of the collected entries. |
| `MAX_TOPICS` | `6` | Maximum topics per report. Six fills the summary image grid. |
| `AI_DIGEST_FONT_PATH` | probed | Path of the font used for image generation. |
| `DATA_DIR` | `data/reports` | Directory holding the generated reports. |
| `HTTP_TIMEOUT` | `15` | Timeout in seconds of every outgoing HTTP request. |
| `USER_AGENT` | `ai-digest/1.0 ...` | User-Agent sent with every outgoing request. |
| `PORT` | `5000` | Port of the development server and of gunicorn. |

### Japanese font

`AI_DIGEST_FONT_PATH` overrides the font used by the image generators. When it is empty, these locations are probed in order and the first existing file wins:

```
/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc
/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf
/usr/share/fonts/truetype/fonts-japanese-gothic.ttf
/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf
```

When no CJK font is found, the batch logs a warning once and keeps running with the Pillow bitmap font; the HTML report stays correct, but the images lose their text.

## Usage

### Generate today's report

```sh
python cli.py run
```

The command collects the last 24 hours, summarizes them, writes `data/reports/<today>/` and exits with status 1 when nothing usable could be produced, which makes failures visible in cron mail.

### Useful variants

```sh
python cli.py run --date 2026-07-25   # file the report under another date
python cli.py run --no-images         # skip scraping, generate every card
python cli.py run --verbose           # debug level logging
python cli.py render 2026-07-25       # rebuild HTML and PNG from stored JSON
python cli.py list                    # print the stored report dates
```

`render` never calls the API, so it is the cheap way to try a layout change on an existing report.

### Browse the reports

```sh
flask --app app run --debug
```

Then open `http://127.0.0.1:5000/`. The routes are:

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

## Deployment

### VPS

Run the viewer under gunicorn and the batch under cron. The two share only the data directory.

`/etc/systemd/system/ai-digest.service`:

```ini
[Unit]
Description=ai-digest web viewer
After=network.target

[Service]
User=ai-digest
WorkingDirectory=/opt/ai-digest
EnvironmentFile=/opt/ai-digest/.env
ExecStart=/opt/ai-digest/.venv/bin/gunicorn app:app --bind 127.0.0.1:5000 --workers 2
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now ai-digest
```

nginx reverse proxy:

```nginx
location / {
    proxy_pass http://127.0.0.1:5000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

Daily batch, as the `ai-digest` user:

```cron
30 6 * * * cd /opt/ai-digest && .venv/bin/python cli.py run >> /var/log/ai-digest/run.log 2>&1
```

### Heroku

`Procfile` and `.python-version` are provided, so a deploy needs only the API key:

```sh
heroku create
heroku config:set ANTHROPIC_API_KEY=sk-ant-...
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
├── ai_digest/
│   ├── __init__.py                 Entry and Topic dataclasses, category colors
│   ├── dedup.py                    title similarity based deduplication
│   ├── storage.py                  report persistence and path handling
│   ├── collectors/
│   │   ├── arxiv.py                arXiv Atom API collector
│   │   └── news_rss.py             RSS and Atom collector
│   ├── analyzer/
│   │   └── summarizer.py           Claude tool use call
│   ├── images/
│   │   ├── resolver.py             ar5iv figure and Open Graph scraping
│   │   └── fallback.py             locally generated topic cards
│   └── render/
│       ├── build.py                static HTML rendering
│       ├── compose_image.py        composite summary PNG
│       ├── templates/              Jinja2 templates
│       └── static/style.css
├── data/reports/                   generated reports, not tracked
└── doc/
    ├── LICENSE
    ├── COPYING
    └── COPYING.LESSER
```

## Contribution

Contributions are welcome. You can help by:

- Adding collectors for further sources
- Improving the layout of the composite image
- Reporting bugs or feature requests

Please follow the style used in this repository: module level header comments describing purpose, requirements and version history, English comments, and documentation updated together with the code.

## License

This repository is dual licensed under the [GPL version 3](https://www.gnu.org/licenses/gpl-3.0.html) or the [LGPL version 3](https://www.gnu.org/licenses/lgpl-3.0.html), at your option.
For full details, please refer to the [LICENSE](doc/LICENSE) file. See also [COPYING](doc/COPYING) and [COPYING.LESSER](doc/COPYING.LESSER) for the complete license texts.
