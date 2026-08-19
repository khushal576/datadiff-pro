# DataDiff Pro

A Dockerized web tool for deep, smart comparison of JSON, XML, and CSV data.
Paste two documents side by side, click **Compare**, and instantly see every
match, mismatch, equivalent value, and extra field — including inside deeply
nested objects and lists.

Both sides can be **different formats** — compare a JSON API response against
an XML export or a CSV file from the same dataset.

This tool now ships as part of the **Toolbox** — one bundled website (see
`main.py` and `CLAUDE.md`) that can host multiple internal tools behind one
home page. DataDiff Pro is tool #1.

---

## Quick Start

```bash
# 1. Clone the repo, then enter the project directory
cd datadiff-pro

# 2. Build and start (this builds the whole Toolbox image, not just this tool)
docker-compose up --build -d

# 3. Open the Toolbox home page, then click the DataDiff Pro card
http://localhost:8000
```

DataDiff Pro itself lives at `http://localhost:8000/tools/datadiff-pro/`.

To stop:
```bash
docker-compose down
```

---

## How to Use

### Basic compare

1. Paste your left-side data into the **Left Input** panel
2. Paste your right-side data into the **Right Input** panel
3. Select the correct format (JSON / XML / CSV) from the dropdown for each side
4. Click **Compare**

The results appear below with:
- A **summary bar** showing counts per status
- A **table** of every field with its status colour-coded and left / right values side by side

### Status colours

| Colour | Status | Meaning |
|--------|--------|---------|
| grey text | MATCH | Values are identical |
| blue row | EQUIVALENT | Different values, but covered by an equivalence rule |
| red row | MISMATCH | Genuinely different values |
| yellow row | EXTRA LEFT | Field/item exists only on the left side |
| yellow row | EXTRA RIGHT | Field/item exists only on the right side |

### Filtering results

- Use the checkboxes above the table to show/hide each status category
- **Hide Matches** is on by default so you only see differences
- Type in the **Filter by path** box to instantly narrow rows by field path

### Export

Click **Export JSON** to download the full diff result as a `.json` file.

---

## Field Mapper (optional)

Use this when the same data has different field names on each side.
Expand the **Field Mapper** panel and paste one mapping per line:

```
source_path,target_path
```

Examples:
```
banks,BankData
nominee.nomineeName,nominee.name
user.address.city,person.location.city
```

- Uses dot notation for nested fields
- Applied to the **left** side before diffing
- Lines starting with `#` are treated as comments and ignored
- Leave blank if both sides already use the same field names — mapping is optional

---

## Environment / Rules (optional)

Expand the **Environment / Rules** panel and paste a YAML config.
See `environments/example.yaml` for the full annotated reference.

### Equivalence rules

Group values that should count as equal:

```yaml
equivalence_rules:
  - [pending, not_started, queued]
  - [USD, usd, "US Dollar"]
  - ["0001-01-01", "1900-01-01", "N/A", ""]
```

Built-in rules (always active):
- `null / none / na / n/a / nil / undefined / ""` are all equivalent
- `true / 1 / yes / y / on` are equivalent
- `false / 0 / no / n / off` are equivalent
- Numbers represented as strings are equivalent to their numeric form (`"1.0"` = `1`)

### List keys

Tell the engine how to pair items in a list of objects:

```yaml
list_keys:
  nominees: [nomineeName, relationship]   # composite key (two fields)
  accounts: [accountId]                   # single key
  products: [sku]
```

If no key is specified, the engine auto-detects one by looking for fields
whose values are unique across the list (tries `id`, `key`, `code`, `name`,
suffix matches like `*_id`, then pairs of candidates).
Falls back to index-based pairing if nothing unique is found.
The strategy used is shown in the results panel.

---

## Supported Input Formats

| Format | Notes |
|--------|-------|
| **JSON** | Any valid JSON — object `{}` or array `[]` |
| **XML** | Single root element; attributes are automatically normalized to plain fields; `xsi:nil="true"` becomes null; mixed-content elements (text + attributes) are correctly hoisted |
| **CSV** | First row is the header; delimiter is auto-detected (comma, tab, semicolon, pipe); JSON-encoded columns (arrays/objects stored as strings) are automatically parsed back to their native types |

---

## XML Attribute Handling

XML attributes are automatically converted to plain fields so they match their
JSON equivalents without any mapping:

| XML | Parsed as |
|-----|-----------|
| `<address type="home">` | `{"type": "home", ...}` |
| `<amount currency="INR">2599.75</amount>` | `{"amount": 2599.75, "currency": "INR"}` |
| `<last_login xsi:nil="true"/>` | `null` |

Namespace declarations (`xmlns:*`) are silently ignored. Unknown namespace
prefixes (e.g. `xsi:`) are auto-declared so the parser never fails on
real-world XML.

---

## CSV Complex Columns

When a CSV file contains JSON-encoded values in a column (common when exporting
from databases or APIs), they are parsed automatically:

| CSV cell value | Parsed as |
|----------------|-----------|
| `["Python","SQL"]` | Python list |
| `{"city":"Ahmedabad"}` | Python dict |
| `true` / `false` | Boolean |
| `42` / `3.14` | Number |
| `null` / `""` | None |

This means a JSON array field and its CSV export will compare as **MATCH**
rather than MISMATCH.

---

## Project Structure

```
datadiff-pro/
├── core/
│   ├── normalizer.py     # parses JSON / XML / CSV → Python dict/list
│   ├── equivalence.py    # equivalence rule engine
│   ├── mapper.py         # field renaming before diff
│   ├── list_resolver.py  # smart list item pairing (key auto-detect)
│   └── diff_engine.py    # recursive deep comparison logic
├── api/
│   └── app.py            # FastAPI app — /compare endpoint + static UI
├── ui/
│   └── index.html        # single-file frontend (no build step)
├── environments/
│   └── example.yaml      # annotated config template
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## API Reference

The UI talks to one endpoint. You can also call it directly from any HTTP client.

### `POST /compare`

**Request body (JSON):**

```json
{
  "left_data":        "<raw text>",
  "right_data":       "<raw text>",
  "left_format":      "json | xml | csv",
  "right_format":     "json | xml | csv",
  "mapper_csv":       "<optional mapping lines>",
  "environment_yaml": "<optional YAML config>"
}
```

**Success response:**

```json
{
  "ok": true,
  "summary": {
    "MATCH": 5,
    "MISMATCH": 2,
    "EQUIVALENT": 1,
    "EXTRA_LEFT": 0,
    "EXTRA_RIGHT": 1
  },
  "records": [
    {
      "path":        "nominees[nomineeName=John,relationship=Son].percent",
      "left_value":  50,
      "right_value": 60,
      "status":      "MISMATCH"
    }
  ],
  "list_strategies": [
    "List 'nominees': environment key (nomineeName, relationship)"
  ],
  "meta": {
    "left_format":         "json",
    "right_format":        "xml",
    "mapping_applied":     true,
    "environment_applied": true
  }
}
```

**Error response:**

```json
{
  "ok": false,
  "error": "Left side — JSON parse error on line 4, column 12: Expecting ',' delimiter.\n  Near: '\"score\": 95'\nHint: Check for missing commas..."
}
```

---

## Development (without Docker)

```bash
# Install dependencies
pip install -r requirements.txt

# Run from the datadiff-pro/ directory
PYTHONPATH=. uvicorn api.app:app --host 0.0.0.0 --port 8089 --reload
```

`--reload` watches for file changes and restarts automatically — useful when
editing the backend. For frontend changes, just refresh the browser.

---

## Requirements

- Docker 20.10+ and docker-compose 1.29+ (or Docker Desktop)
- No other dependencies — everything runs inside the container

---

## Built with Claude

This project was designed and built entirely with
[Claude](https://claude.ai) (Anthropic's AI) using
[Claude Code](https://claude.ai/claude-code) — including the architecture,
all backend modules, the frontend, and the Docker setup.
