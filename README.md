# 🐲 PDF Drupal Uploader

This little Python tool takes PDFs from your computer, uploads them to Drupal, and tells you where Drupal put them.

Basically:

**PDF on your Mac → Python does its thing → Drupal gets PDF → you get the new URL** ✨

## 🧩 What's in here?

* **`main.py`** — The boss. Runs the whole operation.

  * Supports `--dry-run` so you can test without actually uploading anything.
  * Logs useful info/errors.
  * Prints the old PDF → new Drupal URL.

* **`config.py`** — Handles your environment variables and makes sure required settings exist before anything starts.

* **`pdf_files.py`** — Finds your local PDFs and makes sure they're valid.

* **`drupal_jsonapi.py`** — Talks to Drupal.

  * Logs in with Basic Auth.
  * Finds the Drupal node's UUID from its node ID (`nid`).
  * Uploads the PDF into the node's file field.

* **`.env.example`** — Template for your Drupal settings and credentials.

* **`requirements.txt`** — Python dependencies. `requests 2.32.5` is already installed.

# 🚚 How the Upload Works

The script uses Drupal's JSON:API.

It essentially sends:

```text
POST /jsonapi/node/{type}/{uuid}/{field}
```

along with the raw PDF.

The request tells Drupal:

```text
Hey Drupal 👋
Here's a PDF named x.pdf.
Please stick it in this file field.
```

Because the PDF is attached directly to an existing Drupal node, Drupal automatically treats the file as **permanent**.

### What if the filename already exists?

No drama. 😎

If this already exists:

```text
x.pdf
```

Drupal can rename the new one:

```text
x_0.pdf
```

The script grabs whatever final filename Drupal chose and prints the new URL.

So you'll see something like:

```text
local.pdf → https://example.com/sites/default/files/local_0.pdf
```

Then you can update the old PDF links in the editor.

# 🛠️ One-Time Drupal Setup

Good news: **you don't need server access for this part.**

Everything can be done through the Drupal admin UI.

### 1️⃣ Enable the required modules

Go to:

```text
/admin/modules
```

Enable:

* **JSON:API**
* **HTTP Basic Authentication**

### 2️⃣ Allow JSON:API operations

Go to:

```text
/admin/config/services/jsonapi
```

Choose:

**Accept all JSON:API create, read, update, and delete operations**

### 3️⃣ Create a content type for the PDFs

For example:

```text
pdf_library
```

Add a **File** field:

```text
field_pdf
```

Recommended settings:

```text
Allowed extensions: pdf
Number of values: Unlimited
File directory: [leave blank]
Maximum file size: larger than your biggest PDF
```

Leaving **File directory** blank means the PDFs land in:

```text
/sites/default/files/
```

alongside the existing PDFs.

### 4️⃣ Create one node

Create a node using your new content type.

Then edit it and look at the URL.

For example:

```text
/node/123/edit
```

That means your **nid** is:

```text
123
```

📌 Keep that number. The uploader needs it.

### 5️⃣ Check permissions

The Drupal account you're using must have permission to **edit that node/content type**.

Otherwise Drupal will basically say:

🚫 Nice try.

# 🚀 Running the Uploader

Open Terminal:

```sh
cd pdf_uploader
```

Create your real `.env` file:

```sh
cp .env.example .env
```

Now edit `.env` and fill in the required values.

⚠️ **Never commit `.env` to Git.**  
That's where credentials live.

Load the settings:

```sh
set -a
source .env
set +a
```

## 🧪 First: Dry Run

Before touching Drupal:

```sh
python3 main.py --dry-run
```

This lets you make sure everything looks sane without actually uploading PDFs.

**Current status:** ✅ Dry run passes.

## 🔥 Then: The Real Deal

Once JSON:API is enabled on the Drupal site:

```sh
python3 main.py
```

And off the PDFs go. 🚀

# 🧠 What We Still Need

The real upload hasn't been tested yet because the site still needs JSON:API enabled.

Once the Drupal setup is finished, we need three things:

```text
Node ID (nid)
Content type
File field name
```

Example:

```text
nid:          123
content type: pdf_library
field:        field_pdf
```

Then we can test with **one PDF first** before unleashing the whole army. 🫡

# 🕵️ Side Quest: Other Upload Methods

A few other possible routes were checked:

* IMCE
* Media
* CKEditor 5 upload routes

They all returned:

```text
404 💀
```

So whatever editor plugin currently handles PDF uploads doesn't appear to expose a usable public API.

**JSON:API is the cleanest HTTP route we've found.**

<br>
