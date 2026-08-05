# Debian Deployment

This guide deploys ai-digest on Debian: the read only viewer behind nginx and
HTTPS, and the daily batch under cron. Run the commands from an account with
`sudo` access.

The two processes share nothing but `DATA_DIR`. The batch writes it and exits;
the viewer reads it and never calls an API. That separation is what this guide
installs, and it is why a failed batch leaves yesterday's report on the site.

## Before you begin

Prepare these values first:

- A DNS name whose `A` or `AAAA` record points to the server
- An Anthropic API key, or the token, base URL and model of a compatible
  endpoint — unless the host is to run `SUMMARIZER_BACKEND=plain`
- A TLS certificate for the DNS name
- A decision about who may read the archive: nobody outside, Basic
  authentication, an IP range, or a VPN

Allow inbound TCP ports 80 and 443, and outbound HTTPS to `export.arxiv.org`,
to the configured feeds, to the publisher sites the scraper visits and to the
API endpoint. Do not expose gunicorn's port to another host.

## Install the service

Install the required packages:

```sh
sudo apt update
sudo apt install nginx git python3 python3-venv python3-pip fonts-noto-cjk
```

`fonts-noto-cjk` is not optional in practice. Every string drawn into an image
is Japanese, and without a CJK font the generated cards and the composite
summary image show empty boxes where the text should be. The HTML report stays
correct either way, so this failure is visible only in the images.

Create an unprivileged account and install the repository:

```sh
sudo adduser --system --group --home /opt/ai-digest ai-digest
sudo -u ai-digest git clone https://github.com/id774/ai-digest.git /opt/ai-digest
cd /opt/ai-digest
sudo -u ai-digest python3 -m venv .venv
sudo -u ai-digest .venv/bin/pip install --upgrade pip
sudo -u ai-digest .venv/bin/pip install -r requirements.txt
```

`SUMMARIZER_BACKEND=openai` additionally needs the `openai` package, which is
deliberately absent from `requirements.txt` so that a default installation
carries one API client rather than two:

```sh
sudo -u ai-digest .venv/bin/pip install openai
```

Create the environment file and edit it:

```sh
sudo -u ai-digest cp .env.example .env
sudo chmod 600 .env
sudo -u ai-digest sensible-editor .env
```

At minimum set one Anthropic authentication value — `ANTHROPIC_API_KEY`, or
`ANTHROPIC_AUTH_TOKEN` with `ANTHROPIC_BASE_URL` for a compatible endpoint.
Set `SUMMARIZER_BACKEND=plain` instead to run without any key at all, at the
cost of translation and clustering. Every setting is listed in
[`.env.example`](../.env.example) and under
[Configuration](../README.md#configuration).

`chmod 600` is part of the step rather than an afterthought. The file holds a
credential and is read by one service user. `.env` is ignored by Git and must
never be committed.

Give the archive a home. The default `DATA_DIR` is `data/reports` under the
installation directory, which the service user already owns; point it elsewhere
when the archive belongs on another volume:

```sh
sudo -u ai-digest mkdir -p /opt/ai-digest/data/reports
```

Run the offline checks, then build a report without spending an API call:

```sh
sudo -u ai-digest .venv/bin/python cli.py --version
sudo -u ai-digest .venv/bin/python -m unittest discover -s tests
sudo -u ai-digest .venv/bin/python cli.py demo
sudo -u ai-digest .venv/bin/python cli.py list
```

`demo` builds a report from the sample bundled in the repository: it collects
nothing, calls no API and needs no key, so it confirms the installation, the
font and `DATA_DIR` before a credential is involved. `list` printing a date is
the success condition. See [`DEMO.md`](DEMO.md).

## Start the viewer

Review [`deploy/ai-digest.service`](../deploy/ai-digest.service) before copying
it. Its user, paths and port must match the installation and `.env`.

```sh
sudo cp deploy/ai-digest.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ai-digest
sudo systemctl status ai-digest
curl --fail --silent http://127.0.0.1:3000/healthz
```

The expected health response is `ok`. It reads no report and calls no API, so
it answers even on a host whose archive is empty.

Read startup and request errors with:

```sh
sudo journalctl -u ai-digest --since today
```

The viewer needs no credential. It is worth confirming that: a viewer that
cannot reach the API cannot spend one, and an `.env` readable only by the batch
would be the stricter arrangement on a host where the two run as different
users.

## Schedule the batch

The batch is not a systemd service. It runs once, writes one day and exits, and
cron is what says when.

```sh
sudo mkdir -p /var/log/ai-digest
sudo chown ai-digest:ai-digest /var/log/ai-digest
sudo -u ai-digest crontab deploy/ai-digest.cron
sudo -u ai-digest crontab -l
```

[`deploy/ai-digest.cron`](../deploy/ai-digest.cron) runs `cli.py run` at 06:30
local time. Two properties of that entry matter:

- It `cd`s into the installation directory first, because `.env` is found
  relative to the repository root and cron loads no profile.
- It sets `MAILTO`, so a run that exits non-zero is mailed. The batch exits `1`
  when nothing usable could be produced, which is what makes a broken feed or an
  expired key visible without anyone watching the site.

Run it once by hand before trusting the schedule. This spends one API request:

```sh
sudo -u ai-digest sh -c 'cd /opt/ai-digest && .venv/bin/python cli.py run'
```

A second run for the same date replaces that day's report rather than appending
to it, so repeating the command is safe.

## Configure nginx and TLS

Edit a copy of [`deploy/ai-digest.conf`](../deploy/ai-digest.conf) before
enabling it. Replace the server name and the certificate paths with real values.

```sh
sudo cp deploy/ai-digest.conf /etc/nginx/sites-available/ai-digest.conf
sudo sensible-editor /etc/nginx/sites-available/ai-digest.conf
sudo ln -s /etc/nginx/sites-available/ai-digest.conf /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

The sample assumes a certificate already exists and redirects port 80 to HTTPS.
Debian's Certbot packages can obtain and renew one when that is preferred;
follow the certificate provider's current instructions rather than copying an
old command. Run `nginx -t` before every reload.

## Restrict access

The archive is a read only site with no login and no form. Decide who may read
it before it is published, because the reports quote and link the sources they
were built from.

- **Nobody outside**: bind gunicorn to `127.0.0.1` and reach it over an SSH
  tunnel or a VPN. Then no nginx block is needed at all.
- **Basic authentication**: the commented `auth_basic` block in the sample.
  Create the file with `htpasswd -c /etc/nginx/ai-digest.htpasswd NAME`.
- **An IP range**: the commented `allow`/`deny` block in the sample.

Whichever is chosen, gunicorn keeps listening on `127.0.0.1` only, so the
restriction cannot be walked around by addressing the port directly.

## Verify the complete path

```sh
curl --fail --silent http://127.0.0.1:3000/healthz
curl --fail --silent -o /dev/null https://digest.example.net/
sudo -u ai-digest sh -c 'cd /opt/ai-digest && .venv/bin/python cli.py list'
```

Then open the site and follow a date from the archive index. A report page shows
the composite image first and one card per topic. Cards whose illustration is a
generated card rather than a scraped image are expected: scraping is best
effort, and a publisher changing its markup degrades the look of a report, never
its availability.

## API integration

### What the batch asks of the endpoint

The Claude backend calls the Messages API with a tool named `build_report`, and
reads the answer from the `tool_use` block. An Anthropic-compatible endpoint
must therefore support `tools` and return `tool_use` responses; being compatible
with the Messages API is not enough on its own.

Where an endpoint differs, the difference is a setting rather than a code path:

| Setting | For an endpoint that |
|---|---|
| `ANTHROPIC_TOOL_CHOICE_MODE=any` | drops a named `tool_choice` but honours a demand for some tool |
| `ANTHROPIC_TOOL_CHOICE_MODE=auto` | honours neither, and must be asked through the prompt |
| `ANTHROPIC_THINKING_MODE=disabled` | thinks until the output budget is gone and never reaches the tool call |
| `ANTHROPIC_TEXT_JSON_FALLBACK=enabled` | writes the right JSON as text instead of calling the tool |
| `SUMMARIZER_BACKEND=openai` | is more reliable over Chat Completions than over the Messages API |

Change one setting per run, so that the run which succeeds says which setting
did it. [When the endpoint returns no tool
call](../README.md#when-the-endpoint-returns-no-tool-call) gives the order to
try them in.

### Request budget

One `cli.py run` spends one summarization request, plus whatever the SDK retries.

| What | Requests |
|---|---:|
| One `cli.py run` | 1 |
| Each SDK retry (`ANTHROPIC_MAX_RETRIES`, default 2) | 1 more |
| `cli.py demo`, `cli.py render`, `cli.py list` | 0 |
| Every page of the viewer | 0 |

`ANTHROPIC_MAX_RETRIES=0` makes a run cost exactly one request, which is what
comparing two endpoint settings needs on a plan that counts them.

Collection, deduplication, image scraping, the fallback cards and the composite
image all run without an API key. Only the summarization stage calls the API,
which is why `SUMMARIZER_BACKEND=plain` removes the cost entirely.

### Timeouts

`SUMMARIZER_TIMEOUT` (default 180 seconds) bounds one summarization request, and
each retry spends it again:

```text
worst case wait = SUMMARIZER_TIMEOUT x (ANTHROPIC_MAX_RETRIES + 1)
```

At the defaults that is nine minutes. Keep it comfortably below the interval
between two cron runs, so that a hung run has ended before the next one starts.
`HTTP_TIMEOUT` (default 60 seconds) is a separate limit and applies to the
collectors and the scraper, whose requests are many and short.

### Calling ai-digest from another system

ai-digest exposes no JSON API. The viewer's routes return HTML and images and
are not a contract.

What is stable is the archive on disk. `data/reports/<date>/report.json` holds
the topics, the sources and the run statistics, and `index.html` in the same
directory is self contained, so one day can be published by copying its
directory to any static web server. Read the files; do not scrape the viewer.

## Routine operations

After changing Python code, pull and restart the viewer. The batch picks up the
change at its next run:

```sh
cd /opt/ai-digest
sudo -u ai-digest git pull
sudo systemctl restart ai-digest
```

After changing dependencies, install them before restarting:

```sh
sudo -u ai-digest .venv/bin/pip install -r requirements.txt
sudo systemctl restart ai-digest
```

Changing `.env` requires a restart of the viewer for the settings it reads
(`DATA_DIR`, `PORT`); the batch reads the file on every run. Changing the unit
requires `systemctl daemon-reload`. Changing the nginx block requires
`nginx -t` and a reload.

**Rotate the API key** by replacing it in `.env` and restarting. The viewer does
not use it, so the next batch run is the first thing that exercises the new one;
run `cli.py run` by hand to confirm it rather than waiting for cron. Never put a
key on a command line: `ps` is readable by every user of the host, which is why
no credential has a command line option.

**Rotate the batch log.** `deploy/ai-digest.cron` appends to
`/var/log/ai-digest/run.log`, which nothing truncates on its own:

```sh
sudo tee /etc/logrotate.d/ai-digest >/dev/null <<'EOF'
/var/log/ai-digest/run.log {
    weekly
    rotate 8
    compress
    missingok
    notifempty
    create 0640 ai-digest ai-digest
}
EOF
```

**Back up `DATA_DIR`.** It is the archive, and nothing else holds it: a report
is not reproducible after the fact, because the feeds have moved on and the
model would answer differently. It is plain files, so any file level backup
serves:

```sh
sudo -u ai-digest tar czf /var/backups/ai-digest-$(date +%F).tar.gz \
    -C /opt/ai-digest data/reports
```

Back up `.env` securely as well. The virtual environment and the clone are both
reproducible and need no backup.

**Roll back** by checking out the previous revision and restarting. Reports
already written are not touched by a rollback; `cli.py render DATE` redraws one
from its stored JSON when a rendering change has to be undone in place.

## When a run fails

The batch says why in its log and exits `1`. Three failures are worth telling
apart before reaching for a setting:

- **`no entry collected`** — the sources were reached and had nothing recent,
  or could not be reached at all. The message distinguishes the two. arXiv
  announces nothing on weekends, so this is expected on a Saturday and a Sunday.
- **`summarization failed`** — the request was made and did not produce a
  report. The `api response:` line logged next to it carries the stop reason and
  the block types, which is what decides the next setting to try.
- **`the model returned no usable topic`** — the answer arrived and validated
  into nothing. Read it with `--verbose`, which dumps the whole response body.

`cli.py render DATE` and `cli.py demo` never call the API, so they are the cheap
way to test everything downstream of the summarizer while it is being sorted
out. [When something fails](../README.md#when-something-fails) lists the exit
codes and the log lines in full.
