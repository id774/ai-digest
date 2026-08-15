# Requirements: a daily AI digest

## 1. Purpose of this document

This document states what the system is for, what it accepts, what it produces
and where its responsibility ends. It states requirements and the reasons behind
them, and deliberately holds no module name, no function name and no algorithm.

How those requirements are met — the composition, the flow of a run, the
structures that carry the material — belongs to
[`BASIC_DESIGN.md`](BASIC_DESIGN.md). How a change is carried out and judged
belongs to [`POLICY.md`](POLICY.md), the deployment procedure to
[`DEPLOYMENT.md`](DEPLOYMENT.md), and the bundled sample to
[`DEMO.md`](DEMO.md).

It stands on its own. Nothing in it is completed by a document in another
repository.

## 2. Name

`ai-digest`. The name is the output, not the technique: the repository exists to
produce a digest, and the collectors, the language model and the image drawing
are how one is produced.

## 3. Purpose

**ai-digest collects AI related papers and news once a day, organizes them into
the topics worth knowing about, and stores the result as a Japanese daily report
that can be read then and later.**

It is not a list of articles and it is not a search system. It exists to remove
work the reader would otherwise repeat every day:

- visiting each source in turn,
- deciding which items are the same story,
- reading English titles and abstracts,
- choosing which of them matter,
- and keeping track of where each one came from.

**Not everything collected is shown.** The material is edited down to a bounded
number of topics that fit into one sitting. A digest that grows with its input
is the problem restated, not a solution to it.

**The report is not a substitute for the original.** It is the entrance to it:
the reader sees what happened, and follows the citation to the paper or the
article when it is worth their time. Every requirement about citations in
section 9 follows from that.

## 4. The problem

AI information is spread across arXiv, company blogs, research institutions and
news sites. Four properties of that material are what the system exists to
handle.

- **One result appears many times.** A paper, its institution's write-up, a
  company blog post and several news articles are published separately about the
  same work. **The number of items collected is not the number of things that
  happened.**
- **Duplication crowds out everything else.** Left in, one story occupies
  several of the report's limited slots and pushes a different, important topic
  out of the report entirely.
- **Translation alone does not help enough.** Rendering each article in Japanese
  leaves the reader with the same comparison, grouping and selection work they
  started with.
- **A human doing this daily is inconsistent.** What was checked and how it was
  judged drift from day to day. The system offers one path with the same inputs
  and the same output shape, run the same way every day.

## 5. What it is not

- **Not a news site.** No audience, no feed of its own, no comment, no account
  and no search.
- **Not a mirror.** It stores a Japanese summary and a citation. It does not
  store, republish or serve the article or the paper it summarizes.
- **Not a scraper of pages written for humans.** Its material comes from the
  arXiv API and from RSS and Atom feeds, published for programmatic use. One
  narrow exception is bounded and optional: an illustration is looked for on the
  source page, and not finding one is an ordinary outcome. See section 14.
- **Not a chatbot.** There is no conversation and nothing a reader types reaches
  a model.
- **Not a fact checker.** The system reports what its sources published; it does
  not verify a claim, and the generated pages say so.
- **Not a database application.** The archive is plain files in a directory.

## 6. Who uses it, and where it runs

One reader, who is also the operator and the maintainer. There are no accounts,
no roles and no multi-user concerns.

A single Linux host — Debian or Ubuntu is the documented case — on Python 3.9 or
later, running two things with different lifetimes: **a batch that runs once a
day and exits**, and **a viewer that runs continuously** behind a web server.
The host needs outbound HTTPS to the sources and, unless the API free mode is
used, to the summarization endpoint, plus a CJK capable TrueType font, because
every string drawn into an image is Japanese.

A platform whose file system does not survive a restart can host the viewer as a
demonstration only. The archive is exactly what must survive.

## 7. Input

**Papers** from a configured set of arXiv categories, and **news** from a
configured list of RSS or Atom feeds. Both lists are settings: adding or
removing a source is configuration, not a code change.

Only material published inside a **look back window** is kept — twenty four
hours by default, and configurable, because a quiet weekend is answered by
widening the window rather than by waiting.

**The configured window must be applied consistently.** It governs the actual
collection, what the model is told it is looking at, what the HTML says, what
the summary image announces, and what the stored statistics record. A report
that announces one window and was built from another is wrong even when every
figure in it is right.

**Publication timestamps must be interpreted correctly**, and the host's local
time zone must not silently shorten or lengthen the window. "The last N hours"
must mean N hours on every host.

**arXiv does not announce on weekends.** A run on a Saturday or a Sunday
routinely collects no papers at all. That is an ordinary state and must not look
like a fault.

Nothing a reader submits is an input. The viewer has no form, no upload and no
route that writes.

## 8. The daily process

One run performs the whole sequence, and **generating summary text is not the
end of it**:

1. collect papers and news,
2. absorb the differences between sources into one common form,
3. remove the obvious duplicates,
4. group what covers the same story into topics,
5. select the topics that matter that day,
6. produce a Japanese headline, category and bullet points for each,
7. attach the originating sources to each topic,
8. give each topic an image,
9. store the structured data,
10. generate the HTML report,
11. generate the daily summary image,
12. leave it all readable afterwards.

**A day's report is complete only when the citations, the images, the storage,
the HTML and the image generation have all finished.** A run that summarized
successfully and then failed to store or render has not produced that day's
report.

## 9. Citations

Each topic carries the papers or articles it was built from, and the reader can
follow them to the original.

**The model must never invent a citation URL.** It is asked which of the
numbered input items a topic rests on; the application looks those items up in
what it actually collected and takes the real URL and title from there. The
model supplies the correspondence, the application supplies the address.

- A reference to an input item that does not exist is discarded.
- **A topic with no valid citation is not published.** A block of text without a
  traceable origin is worse than one fewer topic.

## 10. Deduplication

Two kinds of duplication exist and they are handled by two different means, on
purpose.

- **Obvious duplication is removed mechanically, before any model is
  involved**: the same URL, or titles that differ only in how they are written.
- **Duplication that requires understanding** — different titles covering the
  same research or event — is left to the topic editing stage, which compares
  meaning.

Separating them buys four things: less material sent to an endpoint, a smaller
bill, less distortion of the importance judgement by the same story appearing
repeatedly, and no dependence on a model for a decision that can be made
deterministically.

Where a paper and reporting about it collide, **the paper is kept as the primary
source.**

## 11. Topic editing

Where a model is used, it is not asked to summarize each article separately. It
is given the candidates together and asked to compare them. Its responsibilities
are:

- group papers and articles that are semantically close into one topic,
- read the titles and abstracts,
- write a Japanese headline,
- write Japanese bullet points,
- name a category that suits the content,
- rank the candidates by importance relative to each other,
- reduce them to the number of topics that can be displayed,
- and say which input items each topic rests on.

**Importance is relative, not absolute.** It is a ranking within the configured
sources, the configured window and the candidates actually collected — not a
judgement about the AI field as a whole.

**The answer must arrive as validated structure, not prose**, so that nothing
has to be recovered from free text by guesswork, and so that a partial or
malformed answer can be refused rather than published.

## 12. How much is shown

The report is limited to an amount that can be read every day. **These limits
come from what a reader will actually get through, not from what the system
could process.**

| Limit | Value |
|---|---|
| Candidates sent for topic editing | 60 |
| Topics in a report | 6 |
| Bullet points per topic | 2 to 4, one sentence each |
| Citations kept per topic | 3 |
| Headline length asked for | within 40 characters |
| Bullet length asked for | within 60 characters |

Six topics is also what the daily summary image holds, so the report and the
image agree without either being trimmed to fit the other.

## 13. Categories

Category labels are chosen to suit the day's content rather than picked from a
fixed list, because the themes that matter change from day to day and a fixed
enumeration would flatten them.

This favours the readability of one day's report. **It does not promise that a
label means the same thing across months**, and long term statistics keyed on
category names are not something this design supports. See section 21.

Colour must follow from the label, and must be stable — the same label always
the same colour, in every report and after every restart.

Where no model is used, the category comes instead from something mechanically
available: the arXiv category for a paper, the feed's origin for an article.

## 14. Illustrations

Every topic carries an image, and there is no state in which one does not.

An image is taken from the paper or the article when a usable one can be
obtained. When it cannot — unreachable, malformed, too large, too small, not
decodable — **a card is drawn locally from the headline and the category
instead.**

**The condition of an external site or image is never a condition of the run
succeeding.** A publisher changing its markup degrades the look of a report,
never its availability, and a locally drawn card is a normal outcome rather than
a degraded one.

## 15. Running without a model

The system must remain usable where no summarization API is available. A
**plain** mode produces a daily report without any semantic editing and without
any credential.

Available in plain mode: arXiv collection, RSS and Atom collection, mechanical
deduplication, images, structured storage, HTML generation, the daily summary
image, and browsing what is stored.

Not performed in plain mode: semantic grouping, translation and Japanese
editing, content based category naming, and model ranking.

**A model is not a required dependency of the system.** It is an interchangeable
stage that raises the quality of the topic editing, and everything before and
after it is unchanged by its absence.

A bundled sample goes one step further and builds a complete report without
collecting anything either, so that a fresh clone can be seen working — settings
loading, storage, HTML, images, and the viewer reading the result — with no
external service at all. It must be possible to direct that output somewhere
other than the real archive.

## 16. The summarization endpoint

The topic editing backend is interchangeable, and the current design recognizes
three: **plain**, **anthropic-compatible** and **openai-compatible**.

- **A backend names a wire protocol, not a vendor.** An endpoint speaking a
  protocol is regularly neither the company that defined it nor operated by it.
- **One endpoint per run.** Several are not configured at once, and there is no
  automatic failover between them. Selecting a backend is an operator's
  decision, not a recovery mechanism.
- Connection target, credential, model, retry count and timeouts are settings.

**Settings are read strictly**: an unknown value stops the run before anything
is collected, rather than being read as the default, because a typo must not
silently send a run that was meant to stay offline through a paid API. A setting
that has been renamed is refused by its old name, with its replacement named,
rather than being quietly read as its successor.

## 17. What is produced

One directory per day, holding at least:

- the structured report data,
- the HTML report,
- its stylesheet,
- the daily summary image,
- one image per topic.

The HTML copy is self contained enough that a day can be published by copying
its directory to a static web server.

## 18. Browsing what is stored

A stored date can be selected and its report read.

**Browsing re-runs nothing**: no collection, no endpoint call, no summary
generation. It works from stored data alone.

**A failed run must not remove what is already there.** Reports stored
successfully before today keep being readable while today's run is broken.

## 19. Failure

The batch runs unattended, so how it fails is part of what it is.

**Continue** — a partial failure that still leaves a usable report:

- some sources could not be read, but others yielded valid items,
- some external images could not be obtained,
- some individual topics from the model were malformed.

**Fail** — nothing worth storing was produced:

- no valid item was collected from any source,
- no usable topic survived topic editing,
- the required structured answer could not be interpreted,
- storing the report failed,
- a required artifact could not be generated.

An empty report is never written as a success, and no half written report is
left in the archive.

**When nothing was collected, the diagnosis must distinguish at least three
cases** — the sources could not be reached, the sources answered and had nothing
in the window, and no source was configured at all — because the operator's next
action differs in each, and one message covering all three leaves them guessing.

Success and failure must be distinguishable by exit status, and the log must
name the cause.

## 20. Records

Each run records at least: how many items were collected, how many remained
after deduplication, how many topics were produced, which model produced them,
and when it was generated.

**Full auditability is not a goal.** Why each candidate was accepted or rejected,
and how the model reached its ranking, are not reconstructed or stored. The
record exists to show the scale of a run and what it finished with.

## 21. Non-goals

ai-digest is not a search platform that stores everything and indexes it. None
of the following is a central requirement:

- long term storage of the full text of collected articles,
- a full text search index,
- keyword search over past reports,
- long term statistical analysis over a fixed category scheme,
- complete audit or reproduction of the model's reasoning,
- making the report sufficient so that the original need not be read.

**What is stored is that day's reading**, and the archive is a sequence of those
days.

## 22. Configuration

Settings are managed in one place, and the summarization settings are one
`SUMMARIZER_*` family rather than one family per vendor — a variable named after
a vendor is also the one other tools read from the environment on their own, so
a value exported for something else could decide where a digest was sent and
what it was billed to.

The settings cover at least: the backend, the credential, the endpoint base URL,
the model, the retry count, the summarization timeout, the protocol compatibility
options, the look back window, the output token limit, the HTTP timeout, the
viewer port, the archive directory, the sources, and the display limits.

**The main settings can be overridden from the command line for one run**, so
that a change can be tried without editing anything, and a run that overrode
something says so in its log. Credentials are the exception in section 23.

Two limits bound the outgoing requests and they measure different things: one
for a collector or scraper request, and a longer one for a summarization
request, where what is being waited for is the writing rather than the network.
Retries multiply the second, and the product must stay well inside the interval
between two scheduled runs, so that a hung run has ended before the next one
starts. **A daily job must never wait indefinitely for an API.**

## 23. Security

- **Only the batch needs the endpoint credential.** The viewer is built so that
  it does not need one and cannot use one.
- **A credential is not passed on the command line**, because a command line is
  readable by every user of the host. It comes from the environment or from a
  local ignored file.
- A file holding a credential has restricted permissions.
- A credential is never committed, never logged at any level, and never quoted
  in an error message. Its absence is reported as absence.
- **Where the viewer is exposed, access control belongs to the layer in front of
  it** — TLS, authentication, an address restriction, a VPN — as the environment
  requires. The application provides none of its own.

Three further rules follow from rendering other people's text in a browser:

- **Text from outside is material, never instruction.** A feed entry, a scraped
  page, an abstract and a model answer are summarized or stored as data; a
  sentence inside one of them that addresses the system is part of the material.
- **A link is published only when it is an absolute ordinary web URL**, whatever
  route put it into the archive.
- **A date arriving from a URL is validated before it names anything on disk**,
  and a value that fails is refused rather than repaired.

## 24. Operation

The batch runs on a schedule, unattended, and the viewer runs independently of
it. Neither waits on the other.

**A stored report cannot be assumed to be regenerable.** The sources change what
they publish and a model's answer is not deterministic, so a day that must be
kept is kept by backing up the generated data itself, not by planning to rebuild
it later.

## 25. Tests

The suite runs offline: no network, no credential, no local configuration file,
and nothing in the archive is touched. A passing suite says nothing about the
sources or the endpoint being reachable, and must not be read as if it did.

## 26. Simplicity

The system is one person's daily batch job and a page to read it on, and should
stay that size. Not wanted: a database, a queue, a scheduler beyond the system
one, a client side framework, a build step, an account system, or a second
archive format. Every dependency earns its place, and one that only an optional
route or a documentation helper needs is not installed by default.

A new source of material is the one extension the design invites, and it must
stay a change that touches collection and nothing else: **what a topic looks
like is not a property of where its material came from.**

## 27. Acceptance conditions

1. A run on a fresh clone with no credential produces a complete report, and the
   bundled sample produces one with no network at all.
2. A run collects, deduplicates, edits into topics, cites, illustrates, stores
   and renders, and exits with a success status only when all of that finished.
3. A run that collected nothing fails, and its message distinguishes unreachable
   sources, an empty window, and no source configured.
4. A run whose sources partly failed still produces a report and says which
   failed.
5. Every topic in every report has at least one valid citation, at least one
   bullet point, and an image.
6. No citation URL in any report originates from a model rather than from
   collected data.
7. The configured window is the one applied, named in the request, shown in the
   HTML and the image, and recorded in the statistics.
8. The window means the same number of hours regardless of the host's time zone.
9. A misconfigured endpoint stops the run before anything is collected, and a
   setting from before a rename is refused by name.
10. The viewer serves the whole archive with no credential and no outbound
    access available, and keeps serving the previous day while a run fails.
11. A corrupt stored report does not break the viewer.
12. No credential appears in any log line, error message, report or committed
    file.
13. A stored day can be re-rendered without calling any endpoint.
14. The whole test suite passes offline.
