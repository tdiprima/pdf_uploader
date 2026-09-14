# PDF Uploader

A command-line tool that pushes a folder of local PDFs into a Drupal site through its core JSON:API, printing the public URL Drupal assigns to each one.

## Getting PDFs onto a Drupal site shouldn't require SSH access

Drupal sites that store reference PDFs (library archives, policy documents, course materials) usually only expose a web UI for adding files one at a time. Bulk uploads mean either clicking through the admin form dozens of times, or asking someone with server access to `scp` files into `sites/default/files/` and register them in the database by hand. Neither scales past a handful of files, and the manual route is easy to get wrong: mistype a node ID, forget to check a file actually is a PDF, and you find out only when a link breaks on the live site.

## A thin, auditable layer over Drupal's own API

This project automates the same thing a site editor would do by hand, using only the standard `JSON:API` and `HTTP Basic Authentication` core modules — no server access, no custom Drupal module, no database access. It validates every candidate file (extension, magic bytes, non-empty) before it ever leaves your machine, authenticates over HTTPS, resolves the target node's UUID, and streams each PDF into the node's file field one at a time. Every upload and failure is logged as structured JSON, and the whole thing fails fast and loudly on bad configuration or a bad file rather than silently skipping it.

The code is split into small, single-purpose files: `pdf_files.py` does pure local validation with no network calls, `reconcile.py` decides which PDFs are already on the node, `drupal_jsonapi.py` owns all the HTTP side effects, `config.py` loads and validates settings from the environment, `env_file.py` reads the optional `.env` file, and `main.py` wires them together and prints results.

## Example

```bash
$ python main.py
{"time": "2026-09-14 09:02:11", "level": "INFO", "component": "pdf_uploader", "message": "files selected", "event": "files_selected", "count": 2, "files": ["annual_report.pdf", "policy.pdf"]}
annual_report.pdf -> https://example.com/sites/default/files/annual_report_0.pdf
policy.pdf -> https://example.com/sites/default/files/policy.pdf
{"time": "2026-09-14 09:02:12", "level": "INFO", "component": "pdf_uploader", "message": "all uploads complete", "event": "done", "count": 2, "uploaded": 2, "skipped": 0}
```

Drupal renamed `annual_report.pdf` to `annual_report_0.pdf` because a file with that name already existed — the tool trusts the URL Drupal hands back, not the local filename, so nothing gets lost.

## Usage

**One-time site setup** (via the Drupal admin UI, no server access needed):

1. Enable the core **JSON:API** and **HTTP Basic Authentication** modules at `/admin/modules`.
2. At `/admin/config/services/jsonapi`, choose "Accept all JSON:API create, read, update, and delete operations".
3. Create (or pick) a content type with a File field that allows the `pdf` extension, and one node of that type to act as the upload target. On the field's settings:
   - Set **Allowed number of values** to **Unlimited**. Drupal defaults new fields to one value; with a single-value field each upload replaces the previous file, so the tool refuses to run against one. A limited count (for example 5) works until the field is full, after which Drupal rejects the upload.
   - Leave **File directory** blank so files land in `/sites/default/files/` alongside your existing PDFs.

**Install dependencies:**

```bash
uv sync
# or
pip install -r requirements.txt
```

**Configure** by copying `.env.example` to `.env` in the directory you run the tool from (or exporting the variables directly) and filling in the values. The tool reads `.env` on startup; a variable already exported in your shell takes precedence over the same one in `.env`. The file format is plain `KEY=value` lines (optional `export ` prefix, optional surrounding quotes, `#` comment lines); values are taken literally, with no variable expansion or inline comments. `.env` is git-ignored — keep it that way, and run `chmod 600 .env` since it holds a password (the tool warns if other users can read it).

| Variable | Required | Description |
|---|---|---|
| `DRUPAL_BASE_URL` | yes | Site root, e.g. `https://example.com` (must be HTTPS) |
| `DRUPAL_USER` | yes | Drupal account that can edit the target node |
| `DRUPAL_PASSWORD` | yes | Password for that account |
| `DRUPAL_NODE_TYPE` | yes | Content type machine name, e.g. `pdf_library` |
| `DRUPAL_NODE_ID` | yes | nid of the node that holds the uploaded files |
| `DRUPAL_FILE_FIELD` | yes | File field machine name, e.g. `field_pdf` |
| `LOCAL_PDF_DIR` | no | Folder to scan (default: current directory) |
| `DRUPAL_TIMEOUT_SECONDS` | no | Per-request timeout (default: 120) |
| `LOG_LEVEL` | no | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL` (default: `INFO`) |

**Run it:**

```bash
python main.py             # upload every valid PDF in LOCAL_PDF_DIR
python main.py --dry-run   # list the files that would be uploaded; no network calls
```

Only files directly inside `LOCAL_PDF_DIR` (no subfolders) that end in `.pdf`, don't start with a dot, and start with the `%PDF-` magic bytes are considered. Anything that looks like a PDF by name but fails the header check stops the run with a clear error instead of uploading a broken file. Each file is checked again when it is opened for upload, so a file that changes after the scan is also caught.

Filenames must use only ASCII letters, digits, spaces, `.`, `_` and `-`, start with a letter or digit, and be at most 240 characters. The name travels in an HTTP header, which cannot carry arbitrary Unicode or quotes, so a name like `报告.pdf` or `it's.pdf` stops the run with an error. Rename such files before uploading.

**Reruns after a failure are safe.** Each upload is committed to Drupal on its own, so a run that fails partway leaves the earlier files attached. Before uploading, the tool lists the files already on the node and skips any local PDF that matches one by name (including Drupal's collision rename, `x.pdf` → `x_0.pdf`, compared case-insensitively) and by exact byte size. This also covers the ambiguous case: if a request times out or the server returns a 5xx error, Drupal may or may not have stored the file. Rerun the same command; if Drupal did store it, the file is skipped and its URL is printed. Skipped files still print a `name -> URL` line and are logged with `"event": "upload_skipped"`.

Limitations of the name-and-size match: a changed PDF that happens to keep the same name and exact size is treated as already uploaded, and two runs started at the same time against the same node can both upload the same file.

**Exit codes:**

| Code | Meaning |
|---|---|
| 0 | Success (or nothing to upload) |
| 2 | Configuration error (missing/invalid variable, unreadable `.env`, bad `LOG_LEVEL`) |
| 3 | Invalid input file (empty, bad PDF header, unsupported filename) |
| 4 | Drupal request failed or returned an unexpected response |
| 5 | Local file or directory could not be read |

**Run the tests** (standard library `unittest`, no network access):

```bash
python -m unittest discover -s tests -t .
```

<br>

