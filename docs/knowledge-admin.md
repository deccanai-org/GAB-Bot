# Gigi's updates channel (managing the FAQ from Discord)

The GAB PM manages Gigi's FAQ documents from a **private staff-only Discord channel**
(`#gigi-updates`): drop a guideline PDF, review the drafted entries, press Publish. No separate
website, no image rebuild. The documents live in a database (PostgreSQL in the cluster); the bot
answers from the published ones.

## What the PM does

1. **Drop a PDF** in the channel (optionally with a title as the message text).
2. Gigi replies with a **draft**: an embed (entries found, the checks, warnings) and the draft as
   an attached `<name>.md`. The text is read in a separate, restricted process. **Nothing is live.**
3. To change the draft, edit the `.md` and **post it back** in the channel under the same name.
   Gigi replaces the draft and shows the checks again.
4. Press **Publish** (Gigi won't send it to Qwen) or **Publish & allow Qwen**, or **Discard draft**.
   Gigi answers from a published document on its next question.

Other commands (exact forms, so ordinary chat in the channel is ignored):

| Say | What happens |
| --- | --- |
| `list` | every document: live / draft / archived, entries, whether Qwen may use it |
| `get <name>` | the document as a `.md` file (edit it and post it back to change a live document) |
| `archive <name>` | takes a live document offline; it is kept and can come back |
| `restore <name>` | brings an archived document back, keeping its Qwen setting |
| `delete <name>` | asks for confirmation, then deletes a draft or archived document for good (saved versions and the activity log stay) |
| `qwen <name> on` / `off` | lets Qwen use, or stop using, a document |
| `import builtin` | **once, before the first publish:** loads the FAQ documents built into the image |
| `help` | this list |

Gigi will not archive the last live document, and will not publish into an empty database (see the
first-time step below).

### The Qwen buttons

A question whose matching entries come from a document that Qwen may not use is handed to staff
instead of answered (the gate in `qwen.py`). **Publish** therefore keeps a document away from
Qwen; **Publish & allow Qwen** is a separate, deliberate button. Nothing turns Qwen on for you.

## Setting it up

1. **Create the channel** (for example `#gigi-updates`) and make it private: deny **View Channel**
   to `@everyone`; allow the staff roles and Gigi **View Channel, Send Messages, Attach Files,
   Embed Links, Read Message History**. Gigi **refuses to work** in a channel that `@everyone`
   can read.
2. **Developer Portal:** the **Message Content intent** must be on (the bot already needs it).
   Without it Discord hides attachments and message text from the bot and the channel does nothing.
3. **Database:** the PostgreSQL accounts below. Two secrets in the bot's cluster secret entry
   (merge them in next to `DISCORD_TOKEN`; restart the pod after changing):
   * `GAB_KNOWLEDGE_DB`: the **read-only** account (what Gigi answers from);
   * `GAB_KNOWLEDGE_ADMIN_DB`: the account that **writes** (used only by this channel).
4. **config.yaml:** under `gab_faq`, set `knowledge_updates.enabled: true`, `channel: gigi-updates`
   (a name or an ID) and optionally `allowed_roles` (role names or IDs; empty = anyone who can
   post in the private channel).
5. **First time only:** say `import builtin`. The database is the whole truth once it holds a live
   document, so without this the first publish would replace the FAQ built into the image with just
   that one document. Gigi refuses to publish into an empty database and tells you to import.

The channel runs inside the FAQ answering, so `gab_faq.enabled` must be on (with the Qwen key).
If `GAB_KNOWLEDGE_ADMIN_DB` is missing the channel stays off and the log says why.

## What protects it

* Only the configured channel is used, never a thread or DM, and only if `@everyone` cannot read it.
  Anything said there belongs to this feature: it is never treated as a question for the FAQ.
* `allowed_roles` (if set) is checked on every message and every button press.
* A draft is never served. Publishing is a button or command; Qwen access is its own button.
* Every change is recorded with who made it (Discord name and ID) in the activity log.
* PDF text is read by a **separate process** that receives none of the bot's secrets (no Discord
  token, Qwen key or database URL in its environment), with a 90 s time limit and, on Linux, a
  1 GB memory and a CPU ceiling. A hostile PDF can neither read the bot's secrets nor hang it.
  `pypdf` is kept current (CI runs `pip_audit --strict`).
* **Trade-off to know about:** the bot now holds a database account that can write. It is used
  only by this channel; answering keeps the read-only one.
* Text checks before anything can be published: safe file name, valid header, no password/token/key
  in the text, at least one numbered entry, entry IDs unique inside the document **and across all
  live documents**.

## PostgreSQL setup

Two accounts: the writer (`gab_admin`) and the bot's reader (`gab_bot`).

```sql
-- as a superuser / the RDS master user
CREATE ROLE gab_admin LOGIN PASSWORD '<generated>';
CREATE ROLE gab_bot   LOGIN PASSWORD '<generated>';
CREATE DATABASE gab_knowledge OWNER gab_admin;
```

1. Connect once as `gab_admin` (start the bot with the channel on, or run the web admin below). It
   creates the tables (`documents`, `versions`, `pdfs`, `support`, `audit`, `meta`).
2. Give the reader the least it needs (connected to `gab_knowledge`):

```sql
GRANT USAGE ON SCHEMA public TO gab_bot;
GRANT SELECT ON documents, support, meta TO gab_bot;   -- NOT pdfs, versions or audit
```

`tests/test_knowledge_store_postgres.py` runs the bot against exactly these grants. URL form:
`postgresql://gab_bot:<password>@<host>:5432/gab_knowledge?sslmode=require` (for RDS use
`sslmode=verify-full&sslrootcert=<RDS CA bundle>`). The URLs hold passwords: they never go in
`config.yaml`, a command line or a log (`gigi check` shows them without the password).

* Writers are serialised with a PostgreSQL advisory lock inside each transaction. Without it, two
  publishes of drafts that reuse an entry ID at the same moment both went live in 25 of 25 trial
  rounds; with it, in 0 of 25.
* The bot's reading session is also set read-only with a 3 s statement timeout through the
  connection `options` parameter. **A connection pooler that rejects `options` (PgBouncer by
  default; set `ignore_startup_parameters = options`) will refuse the connection.** The SELECT-only
  grants are the real protection; the session setting is a second layer.
* If the database is down, or a document fails validation, Gigi keeps answering from the last good
  files (or, if it never reached the database, from the documents built into the image). Reads
  from the bot time out after 3 s and are retried at most every 30 s.

## Optional: the same documents from a web page

`python -m gab_faq.admin` runs a small local web page over the same database (same checks, same
Draft/Publish/Archive/Delete, an Upload tab). It listens on 127.0.0.1 only and is not part of the
bot. Set `GAB_ADMIN_PASSWORD` (12+ characters) and `GAB_KNOWLEDGE_DB` (the writer's URL; `--store`
refuses a URL that contains a password) in the environment. Nothing needs it.

## Not verified yet

* **Against real Discord.** The tests fake Discord (messages, attachments, buttons) around the real
  database, embeds and button views. GIGI was in no server at the last check, so the first real run
  should be in a test channel: attachments, embeds, the buttons and the typing indicator have not
  been seen working against Discord itself.
* **PostgreSQL on RDS** (TLS to RDS, IAM authentication, RDS Proxy, PgBouncer). Tested on
  PostgreSQL 16 in Docker.
* **The production image with the new libraries** was not built here (this laptop's network blocks
  it). The Linux / Python 3.11 wheels were checked against the lock with
  `pip install --dry-run --require-hashes`, and the PDF reader was run in a Linux Python 3.11
  container, including its memory ceiling.
* **Draft quality.** PDF to FAQ is heuristic: expect to edit. Scanned PDFs (no text) are refused;
  there is no OCR.
* `entry-policy.yaml` entry details (`source_location`, `requires`, `claims`) are imported for the
  built-in documents but cannot be edited from the channel.
