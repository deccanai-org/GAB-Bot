# Knowledge admin UI

A small web app for the GAB PM to upload a guideline **PDF**, review the FAQ entries drafted from
it, and publish, archive or delete documents, with no image rebuild. The bot reads the published
documents from a database.

## How it fits together

```
PM browser --> admin UI (python -m gab_faq.admin) --> knowledge database <-- bot (read-only)
                  PDF text -> draft entries                                   |
                  review/edit -> Publish                                      v
                                                          output/knowledge-live/*.md  (local copy)
                                                                              |
                                                          KnowledgeBase (unchanged parsing,
                                                          approval policy, secret scan, index)
```

* The bot never writes to the database. It copies the **published** documents into
  `output/knowledge-live/` (at most every 5 s, when a question arrives) and the existing
  `KnowledgeBase` reads that folder exactly as it read `knowledge/current/`.
* Drafts and archived documents are never served.
* If the database is down, or a published document fails validation, the bot keeps the last good
  files. If it has never reached the database it serves the documents built into the image.
* The feature is **off** unless `gab_faq.knowledge_store` (config.yaml) or `GAB_KNOWLEDGE_DB` is set,
  so the image behaves as before.

## Running it (local)

```powershell
pip install -r requirements-admin.txt          # pypdf, admin UI only; the bot image does not need it
$env:GAB_ADMIN_PASSWORD = "a long password"    # 12+ characters, read from the environment only
python -m gab_faq.admin --import-builtin       # http://127.0.0.1:8090, user "pm" (GAB_ADMIN_USER)
```

`--import-builtin` loads the documents in `knowledge/current/` into an empty database (with their
Qwen approvals), so the bot's answers do not change. The default database is
`output/knowledge.sqlite3` (`--store` or `GAB_KNOWLEDGE_DB` to change it).

To point the bot at it: `GAB_KNOWLEDGE_DB=<same file> gigi check`.

## PM workflow

1. **Upload a PDF.** The text is extracted on the server (pypdf: no network, no AI) and drafted into
   numbered entries (`A1. Question` + answer). Questions, `Question? A: answer` lines, headings
   and bullet lists become entries. Page numbers and repeated headers/footers are removed.
2. **Review.** The draft is only a starting point. Fix the question lines, merge or split entries,
   set `audience:` (annotator / qc / qm / all) and `phase:`. The page shows the checks that must
   pass before publishing.
3. **Publish.** Tick *Allow Qwen* only if the document may be sent to Qwen (see below).
4. **Archive** takes a live document offline (restorable). **Delete** is permanent for the
   document but only for drafts/archived ones; saved versions and the activity log are kept.
   **History** restores any earlier version.

### The Qwen tick box

A question whose matching entries come from a document that is not allowed for Qwen is handed to
staff instead of answered (the existing gate in `qwen.py`). The box defaults to **off** and is never
ticked for you.

## Checks before a document can be live

File name safe (`[a-z0-9-]+.md`); header valid and not marked archived/draft; no password/token/API
key in the text; at least one numbered entry; entry IDs unique inside the document **and across all
live documents** (IDs are global: entry-policy, videos and follow-ups refer to them). Text outside a
numbered entry is a warning because the bot ignores it. The last live document cannot be archived.

## Security

* HTTP Basic login from `GAB_ADMIN_PASSWORD` (constant-time compare), 5 wrong passwords per minute
  per address are throttled. It listens on 127.0.0.1 only; any other `--host` needs
  `--behind-tls-proxy` (Basic auth must never cross a network unencrypted).
* POSTs must come from the same origin (CSRF); all text is HTML-escaped; strict CSP; uploads are
  size-limited (25 MB), must start with `%PDF-`, and the original is served only as a sandboxed
  download.
* Every change is in the activity log with the user name.

## Not done yet

* **Production database.** `SqliteKnowledgeStore` is one file. The UI and the bot must share it,
  which works on one machine, but the cluster's volume cannot be shared between two pods. For
  production, implement the same methods for Postgres or MongoDB (the bot only needs `revision`,
  `list_documents`, `get_support`; the UI needs the rest) and set `GAB_KNOWLEDGE_DB` accordingly.
* **Hosting, TLS and single sign-on** for the UI, and database credentials in the cluster secret.
* **Entry provenance.** `entry-policy.yaml` entries (`source_location`, `requires`, `claims`) are
  imported for the built-in documents but are not editable in the UI; new documents get the PDF
  name and the line number as their source.
* **Draft quality.** PDF to FAQ is heuristic. Scanned PDFs (no text) are refused; there is no OCR.
