# Implementation Policies

This document defines the implementation policy for ai-digest. Unlike the
multi-language policy of the id774/scripts repository, ai-digest is a single
Python application, so the policy below is stated directly for Python instead
of separating a shared common section from per-language sections.

The intent is the same: minimize redundancy while making the design intent
explicit and consistent for all contributors.

---

## General Policy

### Design Philosophy
- Prioritize clarity, portability, and explicit control over convenience.
- Favor predictable behavior and long-term maintainability.
- Avoid implicit behavior; make control flow, errors, and side effects explicit.
- Keep the daily batch (`cli.py`) and the read-only viewer (`app.py`) independent,
  so that a failed or slow batch never takes the site down.

### Invariants
These lines are not crossed by a setting, by an option or by an extension.

- The batch is the only writer of `DATA_DIR`. No route of the viewer collects
  an entry, calls an API or writes a file, so the viewer needs neither a
  credential nor outbound access, and the site keeps serving yesterday's report
  while a batch fails.
- The archive stays plain files, one directory per day, so that it can be
  inspected, backed up or served by any web server. Do not introduce a database
  or a format that only the application can read.
- Every path under `DATA_DIR` is computed in `ai_digest/storage.py`. A date that
  arrives from a URL segment is validated against the anchored `YYYY-MM-DD`
  pattern before it names a directory, and a value that fails is refused, never
  repaired into one that passes.
- A credential is never a command line option, because a command line is
  readable by every user of the host. Credentials are read from the environment
  or from `.env` only.
- A credential is never logged and never quoted in an error message. It is
  reported as present or absent.
- Model output is data, not markup. It is rendered through Jinja autoescaping
  and never with `|safe`, and the viewer and the standalone HTML share the same
  templates so that both are escaped by the same rules.
- A link is published only when it is an absolute `http` or `https` URL. The
  collectors filter what they store and `safe_url` neutralizes what is already
  stored, so that a report written before the filter existed, or edited by hand,
  cannot put another scheme into an `href`.
- One misbehaving source never ends the run. An unreachable feed, a page that
  does not scrape, an image that is refused: each degrades to a warning and a
  fallback, and the run continues with what it has.
- A setting the code has no branch for stops the run and names itself. It is
  never read as the default, because a typo must not silently send a run that
  was meant to stay offline through a paid API.
- Nothing that must stay stable across processes is derived from the builtin
  `hash()`, which is salted per process. Category colors and every comparable
  mapping use a hash written in the module.

### Logging and Output
- Use the standard `logging` module. Do not print status to standard output
  from library modules; obtain a module logger with
  `logging.getLogger(__name__)` and log through it.
- Map severity to levels: `INFO` for normal progress, `WARNING` for a degraded
  but recoverable condition (for example a dropped malformed topic or a failed
  scrape that falls back to a generated card), and `ERROR` for a failure that
  ends the current command.
- Configure logging once, at the entry point, with `logging.basicConfig` writing
  to standard error. The batch uses a fully structured, timestamped format
  (`%(asctime)s %(levelname)s %(name)s: %(message)s`); this is the accepted
  alternative to the `[INFO]`/`[WARN]`/`[ERROR]` prefix style used by shell
  scripts, and is chosen because every message already carries a level and a
  logger name.
- Log messages must be human-readable and suitable for cron execution. Keep them
  low-noise: a single unattended run must not flood the cron mail with per-item
  output at the default level.
- Quiet third-party loggers that add nothing (for example lowering `urllib3` to
  `WARNING`) rather than raising the global level.
- Never log a credential, and never quote one in an error message. Say that a
  key is missing, not what was read.
- `--verbose` lowers the level to debug for one run; it is the only switch that
  does, and no module raises the level on its own.
- When a run replaces a setting from the command line, log which setting took
  which value, so that an unattended run states what it actually ran with.

### Control Flow Rules
- Reserve explicit termination (`sys.exit`) for the process entry point.
  Commands and helpers return their status; they do not call `sys.exit`.
- Normal execution paths must return normally and propagate status explicitly.
- Do not rely on implicit termination or language-specific shortcuts
  (for example a bare `except:` that swallows every error). When a broad
  `except Exception` is genuinely required, such as around a network call whose
  failure modes are open-ended, log the reason before returning a failure code.
- `RuntimeError` is the failure a configuration check or an analyzer raises when
  the run cannot go on. The command catches it, logs its message and returns a
  failure code; it never reaches the top level as a traceback.
- `ValueError` stays what it is in Python: a value that is wrong on its own
  terms, such as a date that is not a date. The caller that received the value
  from outside decides whether that means a refusal or a `404`.

### CLI Conventions
- Command-line tools must provide consistent options:
  - `-h`, `--help` to display usage information and exit with code `0`.
  - `-v`, `--version` to display version information and exit with code `0`.
- Build the parser with `argparse`; `-h`/`--help` is provided by it, and
  `-v`/`--version` is declared explicitly.
- Help or version output represents a successful, user-requested termination.
- Invalid or unsupported options must result in usage output.
- Exit codes must be consistent and documented in the module header.
- Every setting of `config.py` may also be given as an option that names the
  variable it replaces, except the credentials and `PORT`. An option that is
  left out changes nothing, so an existing cron entry keeps behaving as before.
- An option value the pipeline cannot use is refused by the parser, before
  anything is collected and before an API call is spent.
- Subcommands carry the verbs of the batch (`run`, `demo`, `render`, `list`).
  A new mode of operation becomes a subcommand; it does not become a flag that
  changes what an existing subcommand means.

### Error Handling and Exit Codes
- Detect command failures and unmet prerequisites early.
- Always log the reason and the affected target when an error occurs.
- Exit code semantics follow widely accepted UNIX/Linux conventions and remain
  consistent across the repository.

#### Exit Code Conventions
- **0: Success**
  The command completed successfully. This includes terminating after displaying
  help or version information without encountering an error.
- **1: General failure**
  The default failure code. Use it for invalid arguments, missing resources,
  processing errors, or any failure that does not require explicit classification
  (for example a missing API key, no entry collected, or a summarization error).
- **2: The command line was rejected**
  What `argparse` returns for an unknown option, a missing subcommand or an
  argument it cannot convert, such as a count that is not a positive whole
  number. Do not raise it from application code.
- **126, 127, 128 and above**
  Reserved by the shell and by signal convention. Do not redefine them for
  application errors.

### Documentation and Versioning
- Every module must contain a structured header, in this order:
  `Description`, `Routes` (the viewer only), the standard `Author`,
  `Source Code`, `License`, `Contact` block used across the repository,
  `Usage` and `Options` (executables and modules that take options only),
  `Exit Codes` (a module that can end the process with more than one status),
  `Requirements`, `Environment Variables` (`config.py` only),
  `Version History`.
- `Routes` sits next to `Description` because it says what the module serves,
  which is part of what it is; `Usage`, `Options` and `Exit Codes` say how the
  module is driven, and follow the identifying block.
- `Requirements` names `Python Version: 3.9 or later` first, then what the
  module needs beyond it: the third-party packages by name, `See
  requirements.txt` for an executable that needs the whole set, or
  `Standard library only` when it needs nothing else.
- "Test Cases" belong in the test code under `tests/`, never in the application
  modules.
- Documentation must be updated in sync with behavior changes. A change of
  behavior that a reader would look for in the README, in `.env.example` or in
  `doc/VERSIONS` is not finished until it is there as well.

#### When to Bump a Module Version
- These rules apply to the `Version History` in each module header. Repository
  release versions and Git tags follow the separate rules below.
- Do not bump the version mechanically every time a file is touched. Decide
  based on the nature of the change:
  - Documentation-only changes (comments, help text, README/POLICY/VERSIONS
    wording with no effect on behavior) do not bump the version.
  - Any change that affects code behavior (bug fixes, new options, and refactors
    that change observable behavior) bumps the version.
  - Multiple updates on the same date are consolidated into a single version
    entry; do not increment the version multiple times on the same date.
  - Finalizing only the release date of an entry that already exists, such as
    changing `TBD` to the actual date, is not by itself a change. Classify that
    entry by what it contains, not by the date edit.
- The date of a `Version History` entry is the date of the change, written as
  `vX.Y YYYY-MM-DD`, with the newest entry first.

#### Module Version Numbering
- Versions use a two-level `major.minor` scheme.
- When incrementing `minor` would reach `10`, roll over instead: increment
  `major` by 1 and reset `minor` to `0` (for example `v0.9` -> `v1.0`,
  `v1.9` -> `v2.0`).
- Do not continue `minor` past `9` as in standard semantic versioning
  (do not use `v1.10`, `v1.11`, ...).

#### Repository Versioning
- Repository release versions are independent of individual module versions.
- Record repository release versions in `doc/VERSIONS` and use the same versions
  for Git tags.
- Repository release versions may use a three-level `major.minor.patch` scheme.
- Work that is not released yet takes no version of its own: it belongs to the
  entry already standing at the top of `doc/VERSIONS`.
- An unreleased entry carries `(Release Date: TBD)` until it ships. Replacing
  that with the actual date is the release itself, not a change to record.
- The package version exposed by `ai_digest.__version__` and `cli.py --version`
  tracks the application, and is bumped when a release warrants it, not on every
  change.

#### doc/VERSIONS Structure
- `doc/VERSIONS` reads as a version-level summary of overall changes, not a raw
  commit log:
  - When multiple changes to the same file within one version are really one
    coherent change, merge them into a single bullet.
  - When changes are independent, place entries that touch the same file or
    feature near each other, so that each version reads as a coherent whole.
- Use UTF-8.

#### Document File Naming
- A document written in Markdown takes a `.md` extension when it is newly
  created.
- The licence texts keep the extensionless names by which they are recognised:
  `COPYING` and `COPYING.LESSER`.
- A document that is not Markdown takes no extension, or `.txt`.
- An existing document is not renamed to add or change an extension. A path
  here is a public URL that the README, the other repositories, and pages
  outside them link to. Renaming breaks those links, and the ones outside can
  be neither found nor repaired.
- Rename only when the current name causes a failure that outweighs the links
  it breaks, and only after examining the references to it. `doc/POLICY.md` and
  `doc/LICENSE.md` were renamed under that exception: GitHub does not render a
  Markdown document that carries no extension, nothing in `.gitattributes`
  changes that, and every reference to these two files was inside this
  repository, where it was corrected in the same change.
- `doc/VERSIONS` keeps its name. It is not Markdown, so rendering does not
  apply to it.
- A repository whose extensionless document is linked from outside, such as
  id774/scripts with `doc/POLICY.md`, keeps its name. There the broken links would
  cost more than the rendering gains.

#### Document File Attributes
- `.gitattributes` gives `diff=markdown` to `*.md`, so that a diff hunk header
  names the section it falls in. A document named with `.md` is covered by that
  line and needs no entry of its own.
- `doc/VERSIONS` is excluded. It is underlined plain text, and `diff=markdown`
  empties the hunk headers that otherwise name the version.
- `doc/COPYING` and `doc/COPYING.LESSER` are excluded as the licence texts.
- No file is given `linguist-language`. Nothing in `.gitattributes` makes GitHub
  render a document that carries no extension; that is what the `.md` names are
  for.

### Comments, Docstrings and Language
- Comments must be written in English only.
- Comments must be imperative, concise, and action-oriented
  (for example `# Validate input`, `# Initialize environment`), avoiding
  redundant lead-ins such as `# Function to ...`.
- A comment says why, not what. Where a decision looks arbitrary (an anchored
  regular expression, a hand-written hash, a byte limit), the comment gives the
  reason, so that a later change does not quietly undo it.
- Every public function, class and method carries a docstring stating what the
  call returns or does.
- A one-line docstring stays on one line, with a space inside each pair of
  quotes: `""" Return True when the string is a plain YYYY-MM-DD date. """`.
- A longer docstring opens on the line after the quotes, and describes the
  non-obvious parameters under `Args:` and the result under `Returns:`.

### Testing and Operation
- Tests live under `tests/` as `test_*.py` and run with
  `python -m unittest discover -s tests`.
- Use only the standard library for tests: `unittest` and `unittest.mock`.
- Tests must not perform network access or call the Claude API; stub the client
  and feed collectors fixed input instead.
- A test needs no credential, no `.env` and no reachable endpoint.
- A test writes nothing outside a temporary directory. Nothing under `data/` is
  touched by the suite.
- Run the suite from the repository root, because the tests import the top-level
  modules (`config`, `cli`, `ai_digest`) from there.
- The runner exits `0` only when every test passed, which is what a cron job or
  a CI step checks. A passing suite says nothing about the feeds or the API
  being reachable; only an actual run does.
- A fix for a defect arrives with the test that fails without it.
- Assume cron execution by default; the batch reads its configuration from the
  environment or `.env`, so required variables are defined explicitly there.
- The batch must be safe to run twice for the same date: a second run replaces
  the report of that day rather than appending to it or refusing to start.

### License
- The repository is dual licensed under the GPL version 3 or the LGPL version 3,
  at the user's option. The full texts live in `doc/LICENSE.md`, `doc/COPYING` and
  `doc/COPYING.LESSER`.
- Every module header repeats the license line of the standard block, so that a
  file read on its own still states its terms.
- Add a dependency only when its license is compatible with that choice.

---

## Python Implementation Policy

### Supported Versions and Compatibility
- Target Python 3.9 or later, and state `Python Version: 3.9 or later` in module
  headers. Do not state a minimum higher than the code actually requires.
- Type hints are used throughout and are part of the house style; they are not
  avoided for backward compatibility, because the supported floor is 3.9.
- Prefer `str.format()` over f-strings, consistent with the existing code base.

### Header Formatting Rules
- The shebang must be `#!/usr/bin/env python`. Do not use `python3`.
- Include the encoding header:
  `# -*- coding: utf-8 -*-`

### Program Structure
- Define `main() -> int` as the entry point of an executable and terminate with
  `sys.exit(main())`.
- Use early returns to simplify control flow.
- Group imports as standard library, third party, then local, and import a
  third-party package inside the function that needs it only when that package
  is optional, so that the module still imports without it.

### Configuration
- Keep configuration in `config.py`: every setting lives in the `Config`
  dataclass, read from environment variables and optionally from `.env`. The
  module performs no network access and touches no file beyond `.env`, so it is
  safe to import from anywhere, including the viewer and the tests.
- Validation belongs where the meaning of a setting is decided: `load_config()`
  converts and normalizes values, and the `validate_*` methods refuse a
  configuration no backend can serve. A command runs the checks it needs before
  it collects anything; `--version` and the tests run none.
- An empty or whitespace-only string setting reads as unset, so that a bare
  `NAME=` line in `.env` behaves exactly like the absent line.
- Every setting is documented in three places that must agree: the
  `Environment Variables` block of `config.py` (the name, what it decides,
  whether it is required, and the default when it has one), `.env.example` as a
  file to copy, and the README for a reader who is not editing code.
- `.env.example` ships no placeholder credential. An empty value is honest about
  being unset; a fake key would pass the authentication check and fail only
  after a whole run has been spent.

### Dependencies and I/O
- Runtime dependencies are declared and version-pinned in `requirements.txt`
  with compatible ranges, so that a future major release cannot break an
  unattended cron run. Add a dependency only when it earns its place; prefer the
  standard library otherwise.
- A package that only one backend or one developer tool needs stays out of
  `requirements.txt` and is named where it is required (in the comment at the
  end of that file, in the README, or in the header of the tool that drives it),
  so that a default installation carries one API client rather than two. Import
  such a package inside the call that uses it, and name the package to install
  in the error message raised when it is missing.
- Always pass `encoding="utf-8"` for text file operations.
- Treat scraping and every external fetch as best effort: enforce timeouts and
  size limits, and fall back rather than failing the whole run when a single
  source misbehaves.
- Every outbound request carries an explicit timeout and the configured
  User-Agent. There is no request without a timeout, because an unattended run
  must not hang until the next one starts.
- Treat everything fetched as untrusted input: a feed entry, a scraped page and
  a model answer are validated before they are stored, and a value that does not
  validate is dropped with a warning rather than repaired into something that
  passes.
- A decoder is a fetch too. Reading an image or parsing a document can fail or
  refuse its input outside the exceptions of the fetch, and those failures
  belong to the best-effort path as well, not to the traceback that ends a run
  whose summarization has already been paid for.
- `tools/` holds developer utilities that belong to neither the batch nor the
  viewer. They follow the same header, logging and exit code rules, and they may
  require a package that `requirements.txt` does not install.
