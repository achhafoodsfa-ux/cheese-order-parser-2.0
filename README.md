# Cheese Order Parser

## Run locally

1. Install Python 3.10+.
2. Open a terminal in this folder.
3. Run:

```bash
pip install -r requirements.txt
streamlit run app.py
```

The browser will open the Streamlit application.

## Deploy free on Streamlit Community Cloud

1. Create a GitHub repository.
2. Upload:
   - app.py
   - requirements.txt
   - packages.txt
3. Go to Streamlit Community Cloud.
4. Sign in with GitHub.
5. Create a new app.
6. Select your repository and `app.py`.
7. Deploy.

No API key is required for this version.

## What this version does

- Accepts WhatsApp-style text orders.
- Accepts XLSX/XLS/CSV files.
- Maps product names/short names/typos to SAP FG codes.
- Converts CTN to SAP PKT/Units.
- Keeps each customer's order separate.
- Never combines the same product between different customers.
- Produces the exact SAP paste structure:
  FG-CODE [2 tabs] QTY [5 tabs] HO-WH [2 tabs] CHEESE
- Provides a triple-check table before copying.
- Supports the latest special mappings:
  - Red mozz blk -> Achha Mozzarella Block
  - Blue shredd -> Achha Mozzarella Shredded
  - Danish Mozz Block -> Danish Mozzarella Block
  - Burger/Orange -> Yellow Slice
  - Explicit 800gm slice -> 800gm SKU
  - Otherwise slice defaults to 1kg
  - 2kg Burger Slice -> 2 packets of Yellow Slice
