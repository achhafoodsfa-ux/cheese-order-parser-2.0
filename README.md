# 🧀 Cheese Order Parser → SAP

Turns WhatsApp orders, screenshots, PDFs, Word files and order sheets into
clean, customer-wise SAP paste blocks.

```
FG-01-0042		25					HO-WH		CHEESE
```

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Optional (only for reading screenshots):

* **Local OCR** – install Tesseract (`apt install tesseract-ocr`, see `packages.txt`).
* **AI vision** – set `XAI_API_KEY` (Grok) or `OPENAI_API_KEY` in `.streamlit/secrets.toml`
  or as an environment variable. Without a key the app still works: text orders are
  parsed locally and screenshots fall back to Tesseract.

The AI is only ever used to **read/segment** messy input. Product mapping,
quantity conversion and SAP output are 100 % deterministic code.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q          # 128 rule tests derived from MASTER_TRAINING_...V2.txt
```

## Project layout

| File | Purpose |
| --- | --- |
| `item_master.py` | The 128 SAP items + the regular → W.Poly pairs. The parser can never output a code that is not here. |
| `core.py` | All business logic: normalisation, quantity parsing, product resolution, customer segmentation, SAP output, sheet import, teaching. No Streamlit import, fully unit tested. |
| `extractors.py` | File readers (image OCR, PDF, DOCX, Excel, CSV). |
| `app.py` | Streamlit UI. |
| `pages/1_Image_File_Parser.py` | Screenshot/file-only page (local OCR, no AI key needed). |
| `smart_brain_v4.py`, `ai_order_parser.py` | Optional AI reading/segmentation layer. |
| `rules.json` | Saved aliases and taught rules. |
| `tests/` | Rule regression suite. |

## Rules the parser enforces

**Customers**

* Customers are never merged — each block gets its own SAP paste area.
* The same FG code is merged only inside one customer.
* `CFS-…` / `BP-…` codes are captured as customer codes and are never matched to a product.
* Timestamps, “Forwarded”, “Self Pick”, greetings, phone numbers etc. are ignored (and listed, so nothing disappears silently).

**Quantities**

* `CTN` is converted with the item packing; `PKT/PCS` is never multiplied.
  2kg block = 10/CTN, 2kg shred/dice = 5/CTN, slice = 18/CTN, Nivora 2.5kg = 4/CTN.
* `KG` is converted with the pack weight (90 kg of 2kg shred = 45 PKT).
* “2 kg burger slice” = **2 PKT**, “2 ctn burger slice” = **36 PKT**.
* Numbers that belong to the product — `70/30`, `50/50`, `800gm`, `82 fat`, `2kg`,
  timestamps, dates, phone numbers — are never read as quantities.
* A quantity with **no unit** is flagged for review (a sidebar switch can force CTN or PKT).

**Products**

* Priority: explicit FG code → alias you taught → brand + type rules → saved aliases → item-master keywords.
* **W.Poly**: a WP code is used *only* when WP / W.P / W.Poly / W-Poly / W/P is written.
  If WP is written for an item that has no WP code, the line goes to review with the regular code as a hint.
* Top Cow shred = Top Cow dice (same SKU). **Nivora shred ≠ Nivora dice** — a Nivora line without
  dice/shredded goes to review (a sidebar switch can default it to Dice).
* Red Mozz Blk = Achha Mozz Block, Blue Shredd = Achha Mozz Shredded,
  Danish Mozz Block is Danish (never Achha), generic “mozzarella block” defaults to Achha.
* Burger/Orange = Yellow Slice; slices default to 1kg unless 800gm is written.
* Salted butter = Yellow, Unsalted = White; a salted+white style conflict is flagged.
* Typos are normalised (accha/acha, chadder, shared/shrd, blk, lockl, mozz, coton, …).
* Anything ambiguous is **flagged, never guessed** — review lines stay out of the SAP block.

## Teaching new names

In the **Teach the parser** tab write, for example:

```
mf white dice = FG-02-0102
Customer ABC calls Nivora Pro White Shredded 'pro w shred' = FG-02-0105
```

Aliases you teach are stored in `rules.json` and are applied **before** the built-in rules,
so a customer's private shorthand always wins. Codes that are not in the item master are rejected.
