# Implementation Policies

This document defines the implementation policy for ai-digest. It is a single
Python application, so the policy below is stated directly for Python instead
of separating a shared common section from per-language sections.

This document stands on its own. It is the whole implementation policy of this
repository, and no rule here is completed by a document kept somewhere else. A
subject it does not cover is a gap in this document, to be filled here rather
than looked up in another repository.

The intent is to minimize redundancy while making the design intent explicit
and consistent for all contributors.

---

## 1. General Policy

### 1.1 Design Philosophy
- Prioritize clarity, portability, and explicit control over convenience.
- Favor predictable behavior and long-term maintainability.
- Avoid implicit behavior; make control flow, errors, and side effects explicit.
- Keep the daily batch (`cli.py`) and the read-only viewer (`app.py`) independent,
  so that a failed or slow batch never takes the site down.

### 1.2 Invariants
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

### 1.3 Logging and Output
- Use the standard `logging` module. Do not print status to standard output
  from library modules; obtain a module logger with
  `logging.getLogger(__name__)` and log through it.
- Map severity to levels: `INFO` for normal progress, `WARNING` for a degraded
  but recoverable condition (for example a dropped malformed topic or a failed
  scrape that falls back to a generated card), and `ERROR` for a failure that
  ends the current command.
- Configure logging once, at the entry point, with `logging.basicConfig` writing
  to standard error. The batch uses a fully structured, timestamped format
  (`%(asctime)s %(levelname)s %(name)s: %(message)s`), chosen because every
  message already carries its level and its logger name, which makes a
  separate severity prefix redundant.
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

### 1.4 Control Flow Rules
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

### 1.5 CLI Conventions
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

### 1.6 Error Handling and Exit Codes
- Detect command failures and unmet prerequisites early.
- Always log the reason and the affected target when an error occurs.
- Exit code semantics follow widely accepted UNIX/Linux conventions and remain
  consistent across the repository.

#### 1.6.1 Exit Code Conventions
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

### 1.7 Environment Differences
- Branch on what the environment provides, not on what it is called. A
  distribution name, a release number, a platform string or a Python build
  each answer a question the code is not asking. The question is whether the
  command, the file, the service or the format it needs is there.
- Keep that detection in one place. The same question answered separately in
  several places drifts apart as environments change.
- A capability the application can work without is detected where it is used,
  not declared as a requirement. Detection asks whether the capability is
  usable, not only whether it is present: a package can import while the
  backend it needs is absent, and a command can exist while the option this
  code passes it is not supported.
- Decide in advance what an absent optional capability leads to: use the
  alternative, skip the step and say so once, or refuse the run. Which one is
  right depends on where the code runs. An unattended run in an environment
  that will never supply what it needs says so once and ends with a documented
  status, rather than reporting the same absence on every scheduled run.

### 1.8 Documentation and Versioning
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

#### 1.8.1 When to Bump a Module Version
- These rules apply to the `Version History` in each module header. Repository
  release versions and Git tags follow the separate rules below.
- Do not bump the version mechanically every time a file is touched. Decide
  based on the nature of the change:
  - Documentation-only, comment-only and formatting-only changes (help text,
    README/POLICY/VERSIONS wording, whitespace and layout, with no effect on
    behavior) do not bump the version.
  - Any change that affects code behavior (bug fixes, new options, and refactors
    that change observable behavior) bumps the version.
  - Multiple updates on the same date are consolidated into a single version
    entry; do not increment the version multiple times on the same date.
  - Finalizing only the release date of an entry that already exists, such as
    changing `TBD` to the actual date, is not by itself a change. Classify that
    entry by what it contains, not by the date edit.
- The date of a `Version History` entry is the date of the change, written as
  `vX.Y YYYY-MM-DD`, with the newest entry first.

#### 1.8.2 Module Version Numbering
- Versions use a two-level `major.minor` scheme.
- When incrementing `minor` would reach `10`, roll over instead: increment
  `major` by 1 and reset `minor` to `0` (for example `v0.9` -> `v1.0`,
  `v1.9` -> `v2.0`).
- Do not continue `minor` past `9` as in standard semantic versioning
  (do not use `v1.10`, `v1.11`, ...).

#### 1.8.3 Repository Versioning
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

#### 1.8.4 doc/VERSIONS Structure
- `doc/VERSIONS` reads as a version-level summary of overall changes, not a raw
  commit log. It is a plain text document and follows the rules for one stated
  below, with the one exception of line length described here.
- Write one coherent change on one physical line. This is the rule, qualified
  once below for a file that has already settled on a form of its own. The file
  is read as a list and reviewed as a diff, and both are served by an entry that
  is not wrapped: one line is one change, added, removed or reworded as a whole.
- That rule comes before the roughly 80 columns a plain text document otherwise
  aims at. Near 100 columns is the usual target, and an entry that has to name
  a file, a command, a function, an option or a setting may run to about 120
  columns or beyond.
- These widths are a prompt to check whether an entry explains more than it
  needs to, not a limit to enforce.
- `doc/VERSIONS` carries these guidelines again at its foot, and an entry
  written into it follows the reasons recorded there.
- That qualification is this: where the file has settled on a width of its own,
  a new entry is wrapped to that width and balanced against the lines already
  standing, so that the version history stays of a piece, and that consistency
  comes before the one physical line asked for above. Holding to a form the
  file has established is how the rule is kept there, not a departure from it,
  and the entries already written are not reflowed or rebuilt to suit it.
- When an entry runs long, look first for what can be dropped or abstracted:
  the implementation detail, the example, the detailed reason, the secondary
  effect. Consider that before wrapping the line.
- Keep the changed target, the behavior visible from outside, the effect on
  compatibility, the effect on safety, and the identifiers that matter.
- An entry that is long because it names the identifiers it needs is not
  shortened for its length alone.
- Merge changes that serve one purpose. Related changes to the same file within
  one version are merged as a rule; changes to the same file that mean
  different things are left as separate entries rather than forced together.
- Place entries that touch the same feature, file or purpose near each other,
  and append an independent change to the end of that version. Reading well as
  a version comes before preserving the order the commits happened in.
- Use UTF-8.

#### 1.8.5 Document Format
- The format of a document is decided by what it is for and by the name it
  carries, not by whether part of its content happens to parse as Markdown.
- A document named with `.md` is written, displayed and maintained as Markdown.
- A document that carries no extension is a plain text document, and nothing in
  it assumes a Markdown renderer.
- Underlined headings, dashed lists, backquotes and bare URLs are readable as
  Markdown wherever they appear, and finding them in a plain text document does
  not make it one.
- The name states the format so that nobody has to infer it from the content.
  Reading a file to guess what it is gives a different answer to every reader
  and to every agent; the extension gives all of them the same answer.
- The two formats are kept apart because they are read in different places.
  Markdown is read rendered, in a browser, where the structure carries the
  meaning. Plain text is read raw, in a terminal, a pager or a diff, where the
  bytes are all there is. A rule that serves one damages the other, which is
  why the two sets of rules below are stated separately and are not merged.

#### 1.8.6 Markdown Documents
- A Markdown document may assume that it will be rendered, on GitHub or
  elsewhere.
- Use headings, lists, tables, code blocks, links and emphasis to make the
  structure of the document explicit.
- Name it with `.md`, so that the path states the format.
- `*.md diff=markdown` in `.gitattributes` gives it diff hunk headers that name
  the section, and that is there to be used.
- Both sides count: the structure after rendering, and how easy the source is
  to edit.
- Ordinary prose may be wrapped where that keeps the source readable, near the
  width the document already uses.
- The roughly 80 columns that plain text aims at is not a limit here, and is
  not applied to a Markdown document as one.
- A URL, a table row, a code block, a command, an identifier or a link
  construct may run long. Wrapping one of those costs a copyable line or a
  working table and buys nothing.
- Line length never justifies breaking the meaning of the markup or inserting a
  break the notation does not want.
- In a Markdown document the heading structure, the paragraph structure, the
  correctness of the notation and the rendered result come before the length of
  a physical line.

#### 1.8.7 Plain Text Documents
- A plain text document is read as it is, without GitHub's rendering and
  without any particular viewer.
- It stays readable on an old fixed-width terminal, under `less` or `cat`, in
  an editor and in a diff.
- Ordinary prose stays near 80 columns as far as it practically can.
- Near 80 columns is a guideline for readability on a terminal, not an absolute
  mechanical limit.
- A URL, a legal formula, a command, a required identifier, a table, or a line
  that is clearer left unbroken may exceed the usual width.
- Exceeding that width is not by itself a defect, and not by itself something
  that has to be corrected.
- Markdown-compatible headings and lists may be used to give such a document
  structure, but nothing in it assumes Markdown rendering.
- Judge it as raw text: how readable and how stable it is line by line, not
  what a renderer would make of it.

#### 1.8.8 Document File Naming
- A document written in Markdown takes a `.md` extension when it is newly
  created. ai-digest is a recent repository, so its Markdown documents carry
  the extension from the moment they are written: `doc/POLICY.md`,
  `doc/LICENSE.md`, and the design and operation documents beside them.
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
- An older repository may keep an extensionless `POLICY` or `GUIDELINES`
  because history, a published path, an outside reference or compatibility
  weighs more there than rendering does. A name that differs between
  repositories is not by itself a policy that differs: the rule for naming a
  new document and the rule for keeping an existing path hold at the same time.
- The naming of a recent repository is not applied backwards to an older one,
  and the historical naming of an older repository is not copied into a recent
  one. Each name is decided where it lives.

#### 1.8.9 The Extensionless Documents Here
- `doc/VERSIONS` is the version history, plain text, without an extension.
- `doc/COPYING` and `doc/COPYING.LESSER` hold the official licence texts as
  plain text.
- None of the three is a `.md` document, and none of them is meant to be
  rendered as Markdown.
- Their official names, their legal wording and their published paths come
  first. Uniformity of form is not on its own a reason to rename them.
- `doc/LICENSE.md` carries `.md` because it is the Markdown document this
  repository presents to a reader.
- `LICENSE.md` and the `COPYING` texts have different roles, so having both is
  neither a duplicate nor an inconsistency.
- Do not rename `doc/VERSIONS`, `doc/COPYING` or `doc/COPYING.LESSER` to `.md`
  because they contain a symbol a Markdown renderer would accept.

#### 1.8.10 Document File Attributes
- What `.gitattributes` says about a diff does not decide the format of a
  document. It describes documents whose format their names have already
  settled.
- `.gitattributes` gives `diff=markdown` to `*.md`, so that a diff hunk header
  names the section it falls in. A document named with `.md` is covered by that
  line and needs no entry of its own.
- `doc/VERSIONS` is excluded. It is underlined plain text, and `diff=markdown`
  empties the hunk headers that otherwise name the version; leaving it out
  agrees with treating it as a plain text version history.
- `doc/COPYING` and `doc/COPYING.LESSER` are excluded as the licence texts,
  which agrees with their role as the official legal wording.
- No file is given `linguist-language`. Nothing in `.gitattributes` makes GitHub
  render a document that carries no extension; that is what the `.md` names are
  for, and an extensionless document is not dressed up as Markdown.
- How a document appears on GitHub is not a reason on its own to change its
  format or its attributes.

#### 1.8.11 Form and Role
- Bringing every document to one extension, one line width and one way of being
  displayed is not a goal in itself.
- Choose the form from the role of the document, where it is read, the path it
  is published under, what it must stay compatible with, and how it is edited.
- What is kept uniform is not the appearance of the documents but the criterion
  by which their form is chosen.
- Markdown documents and plain text documents living side by side in one
  repository is the intended design, not an untidiness to be resolved.
- Modernizing or unifying a format must not cost an existing path, a legal
  text, readability on a terminal, or the legibility of a diff.
- Before changing a file name or a line width, find out why the current form
  was chosen.

### 1.9 Comments, Docstrings and Language
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
- Name a thing by what it is, not by a part of it. The shell is the interpreter
  that runs a shell script, so a script is not "a shell", in the same way that
  a USB memory stick is not "a USB". The same loss happens wherever a shorthand
  reaches for the interface, the format or the container instead of the thing
  itself. This applies to the headers, the documents and the commit messages as
  much as to the comments.

### 1.10 Testing and Operation
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
- Anything else that changes state on the host is safe to run twice as well,
  the deployment steps and the utilities under `tools/` included. Check the
  current state before changing it, rather than assuming the state a previous
  run left behind.
- The batch, the viewer and the utilities run with the privileges their work
  needs and no more. A step that needs a raised privilege takes it for that
  step; the process does not run its whole body under it.

### 1.11 Pull Request Scope and History
A pull request presents the change it proposes, not the sequence of corrections
that produced it. It carries one purpose, and when the direction is revised part
way through a review, the branch is rewritten so that it reads as the change
finally intended, and merges as if it had been written that way.

#### 1.11.1 One Purpose to a Pull Request
- Changes that serve different purposes are proposed separately, as a rule,
  even when they touch one file and even when one was noticed while the other
  was being made. A pull request is accepted or rejected whole, and a mixed one
  leaves no way to take the part that is wanted.
- A change noticed in passing is proposed on a branch of its own. It is not
  carried along because the working tree happened to be open at it, and it does
  not enlarge the request already under review.
- Tidying, renaming and reformatting that the change does not require are a
  change of their own. Attached to something else, they bury the change the
  reviewer came to read.
- Work that cannot stand without the change is not a second purpose. Its
  `doc/VERSIONS` entry, the `Version History` entry in the header of the module
  it changes, the test that fails without it, and the README or `.env.example`
  line a change of behavior requires, belong to the change that requires them.
- Where the separation is genuinely artificial, because neither part is correct
  or reviewable without the other, they are proposed together and the request
  says why.

#### 1.11.2 Keeping a Branch to Its Change
- A branch that carries one coherent change carries it as one commit. That
  commit is amended and force pushed with `--force-with-lease`, rather than
  gaining a further commit for each remark received.
- Commits such as "fix review comment", "address feedback" or "resolve
  conflict" describe the review rather than the change, and do not belong in
  the history that is merged.
- A branch is split into several commits only when it genuinely carries several
  independent changes. The reasoning is the one that decides a `doc/VERSIONS`
  bullet: coherence, not chronology.

#### 1.11.3 Leaving No Trace of the Correction
- Each revision is read against the base branch, not against the revision
  before it, so that a correction leaves no residue in the diff that is merged.
- A correction withdraws what it replaces. Code, comments and wording
  introduced by an earlier revision and since abandoned are removed, not left
  standing beside their replacement.
- Conflicts with the base branch are resolved by rebasing onto it, so that no
  merge commit enters the branch.
- A rewritten branch invalidates the copies others have fetched. Force pushing
  is confined to the branch under review, and the rewrite is stated whenever
  the branch is shared.

### 1.12 License
- The repository is dual licensed under the GPL version 3 or the LGPL version 3,
  at the user's option. The full texts live in `doc/LICENSE.md`, `doc/COPYING` and
  `doc/COPYING.LESSER`.
- Every module header repeats the license line of the standard block, so that a
  file read on its own still states its terms.
- Add a dependency only when its license is compatible with that choice.

---

## 2. Python Implementation Policy

### 2.1 Supported Versions and Compatibility
- Target Python 3.9 or later, and state `Python Version: 3.9 or later` in module
  headers. Do not state a minimum higher than the code actually requires.
- Type hints are used throughout and are part of the house style; they are not
  avoided for backward compatibility, because the supported floor is 3.9.
- Prefer `str.format()` over f-strings, consistent with the existing code base.

### 2.2 Header Formatting Rules
- The shebang must be `#!/usr/bin/env python`. Do not use `python3`.
- Include the encoding header:
  `# -*- coding: utf-8 -*-`

### 2.3 Program Structure
- Define `main() -> int` as the entry point of an executable and terminate with
  `sys.exit(main())`.
- Use early returns to simplify control flow.
- Group imports as standard library, third party, then local, and import a
  third-party package inside the function that needs it only when that package
  is optional, so that the module still imports without it.

### 2.4 Configuration
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

### 2.5 Dependencies and I/O
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
