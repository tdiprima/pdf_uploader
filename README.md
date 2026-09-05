# PDF Drupal Uploader

- main.py orchestration, --dry-run, JSON logs to stderr, prints local.pdf -> https://.../new.pdf to stdout
- config.py env vars, fail-fast validation
- pdf_files.py find and validate local PDFs (unchanged)
- drupal_jsonapi.py Basic Auth session, nid → UUID lookup, POST file to node field 
- .env.example, requirements.txt (requests 2.32.5, already installed)

## How upload works.
Core JSON:API file upload endpoint: POST /jsonapi/node/{type}/{uuid}/{field}, raw bytes,
Content-Disposition: file; filename="x.pdf". Posting to existing node attaches file at once, so Drupal marks it
permanent. Response returns final filename and URL. Drupal renames on collision (x.pdf becomes x_0.pdf). You said
new name OK, so script prints new URL per file. You then update links in editor.

## One-time site setup, admin UI only, no server:
1. /admin/modules: enable core JSON:API and HTTP Basic Authentication.
2. /admin/config/services/jsonapi: pick "Accept all JSON:API create, read, update, and delete operations".
3. Create content type, e.g. pdf_library, with File field field_pdf. Allowed extensions pdf. Number of values:
 Unlimited. "File directory" blank, so files land in /sites/default/files/ next to current PDFs. Max size above
 your biggest PDF.
4. Create one node of that type. Note its nid from URL /node/123/edit.
5. Your account needs edit permission on that node type.

## Run:

```sh
cd /Users/tdiprima/Desktop/lala/pdf_uploader
cp .env.example .env# fill in values; never commit .env
set -a; source .env; set +a
python3 main.py --dry-run
python3 main.py
```

Dry run passes. Real path untested until site has JSON:API on. Send me nid, content type, field name after setup
and I test with one PDF.

Side note: probes for IMCE, Media, CKEditor 5 upload routes all 404. Whatever editor plugin uploads PDFs today has
no public API I can find. JSON:API is cleanest HTTP route.

<br>
