import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st

st.set_page_config(
    page_title="Cheese SAP Order Parser",
    page_icon="🧀",
    layout="wide",
)

# ============================================================
# MASTER PRODUCT DATABASE
# ============================================================
PRODUCTS = {
    "FG-02-0012": {"name": "Classic Cheddar Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["classic cheddar", "classic chadder", "classic cheddar block"]},
    "FG-02-0068": {"name": "Top Cow Cheddar Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["top cow cheddar block", "top cow chadder block"]},
    "FG-02-0006": {"name": "Achha Pizza Cheddar Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["pizza cheddar", "pizza chadder", "pizza cheddar block"]},
    "FG-02-0018": {"name": "Regular Cheddar Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["regular cheddar block"]},

    "FG-02-0028": {"name": "Yellow Slice 1kg", "pack": "slice", "pcs_ctn": 18, "kg": 1, "keywords": ["yellow slice", "orange slice", "burger slice", "burger/orange"]},
    "FG-02-0023": {"name": "White Slice 1kg", "pack": "slice", "pcs_ctn": 18, "kg": 1, "keywords": ["white slice"]},
    "FG-02-0039": {"name": "Jalapeno Cheddar Slice 1kg", "pack": "slice", "pcs_ctn": 18, "kg": 1, "keywords": ["jalapeno slice", "jalapeno cheddar slice"]},
    "FG-02-0038": {"name": "Yellow Slice 800gm", "pack": "slice800", "pcs_ctn": 18, "kg": 0.8, "keywords": ["yellow slice 800", "yellow 800"]},
    "FG-02-0037": {"name": "White Slice 800gm", "pack": "slice800", "pcs_ctn": 18, "kg": 0.8, "keywords": ["white slice 800", "white 800"]},

    "FG-02-0060": {"name": "Top Cow Mozzarella Block White", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["top cow mozzarella block", "top cow block"]},
    "FG-02-0048": {"name": "Top Cow White Dice/Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["top cow white dice", "top cow white shred", "top cow white shredded", "top cow shred white"]},
    "FG-02-0049": {"name": "Top Cow Yellow Dice/Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["top cow yellow dice", "top cow yellow shred", "top cow yellow shredded"]},

    "FG-02-0072": {"name": "Classic 70/30 Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["classic 70/30", "classic 70.30"]},
    "FG-01-0012": {"name": "Classic Mozzarella Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["classic mozzarella block", "classic mozz block", "classic mozz blk"]},
    "FG-02-0036": {"name": "Classic Mozzarella Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["classic mozzarella shred", "classic mozzarella shredded", "classic shred"]},
    "FG-02-0082": {"name": "Classic Mozzarella Shredded DC", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["classic mozzarella shredded dc"]},
    "FG-01-0018": {"name": "Danish Mozzarella Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["danish mozzarella block", "danish mozz block", "danish mozz blk"]},
    "FG-01-0030": {"name": "Danish Mozzarella Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["danish mozzarella shred", "danish mozzarella shredded"]},
    "FG-01-0036": {"name": "Imported/UK Mozzarella Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["imp uk mozzarella", "imported mozzarella shred", "uk mozzarella shred"]},
    "FG-03-0006": {"name": "Imported 70/30 Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["imp 70/30", "imported 70/30"]},
    "FG-03-0026": {"name": "Imported 70/30 Dice", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["imp 70/30 dice", "imported 70/30 dice"]},

    # IMPORTANT USER-SPECIFIC MAPPING:
    # red mozzarella block = Achha Mozzarella Block
    "FG-01-0006": {"name": "Achha Mozzarella Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["achha mozzarella block", "achha mozz block", "achha mozz blk", "red mozz blk", "red mozzarella block", "mozzarella block"]},
    # blue shredd = Achha Mozzarella Shredded
    "FG-01-0042": {"name": "Achha Mozzarella Shredded White", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["achha shred", "achha shredded", "achha shared", "achha shared white", "blue shredd", "blue shred", "achha mozzarella shred", "achha mozzarella shredded"]},
    "FG-01-0054": {"name": "Achha Mozzarella Shredded Yellow", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["achha shred yellow", "achha shared yellow"]},
    "FG-01-0124": {"name": "Achha White Dice", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["achha white dice"]},
    "FG-01-0125": {"name": "Achha Yellow Dice", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["achha yellow dice"]},

    "FG-03-0018": {"name": "Local 70/30 Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["local 70/30", "local 70.30", "locl 70/30", "lockl 70/30", "lockl 70.30"]},
    "FG-02-0051": {"name": "New/M3 70/30 Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["new 70/30", "new 70.30", "m3 70/30", "m3 shred", "m3 70/30"]},
    "FG-03-0024": {"name": "50/50 Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["50/50 shred", "50/50 shredded"]},
    "FG-01-0066": {"name": "Latina Mozzarella Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["latina mozzarella shred", "latina shred"]},
    "FG-01-0111": {"name": "Silver Mozzarella Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["silver mozzarella block", "silver mozz block", "silver"]},
    "FG-01-0110": {"name": "Silver Mozzarella Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["silver mozzarella shred"]},
    "FG-03-0025": {"name": "Verona Mozzarella Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["verona mozzarella block", "verona mozz block"]},
    "FG-01-0072": {"name": "Verona Mozzarella Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["verona shred", "verona mozzarella shred"]},
    "FG-02-0065": {"name": "Pizza Topping Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["pizza topping block"]},
    "FG-02-0064": {"name": "Pizza Topping Shredded", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["pizza topping shred"]},

    "FG-06-0004": {"name": "Butter White 82 FAT 1kg", "pack": "unit", "pcs_ctn": 1, "kg": 1, "keywords": ["butter white 82", "butter white"]},
    "FG-06-0011": {"name": "Butter Yellow 82 FAT 1kg", "pack": "unit", "pcs_ctn": 1, "kg": 1, "keywords": ["butter yellow 82", "butter yellow"]},
    "FG-06-0017": {"name": "Butter White 87 Fat 1kg", "pack": "unit", "pcs_ctn": 1, "kg": 1, "keywords": ["butter white 87"]},
    "FG-06-0018": {"name": "Butter Yellow 87 Fat 1kg", "pack": "unit", "pcs_ctn": 1, "kg": 1, "keywords": ["butter yellow 87"]},
    "FG-06-0003": {"name": "Butter White 500gm", "pack": "unit", "pcs_ctn": 1, "kg": 0.5, "keywords": ["butter white 500"]},
    "FG-06-0010": {"name": "Butter Yellow 500gm", "pack": "unit", "pcs_ctn": 1, "kg": 0.5, "keywords": ["butter yellow 500"]},
    "FG-05-0002": {"name": "Desi Ghee Tin 500gm", "pack": "unit", "pcs_ctn": 1, "kg": 0.5, "keywords": ["desi ghee 500"]},
    "FG-05-0011": {"name": "Desi Ghee Tin 1kg", "pack": "unit", "pcs_ctn": 1, "kg": 1, "keywords": ["desi ghee 1kg", "desi ghee"]},
    "FG-05-0005": {"name": "Desi Ghee Tin 16kg", "pack": "unit", "pcs_ctn": 1, "kg": 16, "keywords": ["desi ghee 16kg"]},

    # Nivora
    "FG-02-0110": {"name": "Nivora Max White Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["max white dice", "max w dice"]},
    "FG-02-0109": {"name": "Nivora Max White Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["max white shred", "max white shredded"]},
    "FG-02-0112": {"name": "Nivora Max Yellow Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["max yellow dice"]},
    "FG-02-0111": {"name": "Nivora Max Yellow Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["max yellow shred"]},
    "FG-02-0102": {"name": "Nivora MF White Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["mf white", "mf white dice"]},
    "FG-02-0101": {"name": "Nivora MF White Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["mf white shred"]},
    "FG-02-0104": {"name": "Nivora MF Yellow Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["mf yellow", "mf yellow dice"]},
    "FG-02-0103": {"name": "Nivora MF Yellow Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["mf yellow shred"]},
    "FG-02-0106": {"name": "Nivora Pro White Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["pro white", "pro w", "pro white dice"]},
    "FG-02-0105": {"name": "Nivora Pro White Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["pro white shred"]},
    "FG-02-0108": {"name": "Nivora Pro Yellow Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["pro yellow dice"]},
    "FG-02-0107": {"name": "Nivora Pro Yellow Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["pro yellow shred"]},
    "FG-02-0118": {"name": "Nivora PT White Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["pt white", "pt w", "pizza topping white"]},
    "FG-02-0117": {"name": "Nivora PT White Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["pt white shred"]},
    "FG-02-0120": {"name": "Nivora PT Yellow Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["pt yellow", "pt y", "pizza topping yellow"]},
    "FG-02-0119": {"name": "Nivora PT Yellow Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["pt yellow shred"]},
    "FG-02-0114": {"name": "Nivora VF White Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["vf white dice"]},
    "FG-02-0113": {"name": "Nivora VF White Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["vf white shred"]},
    "FG-02-0116": {"name": "Nivora VF Yellow Dice", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["vf yellow dice"]},
    "FG-02-0115": {"name": "Nivora VF Yellow Shredded", "pack": "nivora", "pcs_ctn": 4, "kg": 2.5, "keywords": ["vf yellow shred"]},
}

# Allana
PRODUCTS.update({
    "FG-02-0094": {"name": "Allana Cheddar Cheese Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["allana cheddar block"]},
    "FG-02-0096": {"name": "Allana Mozzarella Cheese Block", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["allana mozzarella block"]},
    "FG-02-0097": {"name": "Allana Mozzarella Cheese Shredded White", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["allana mozzarella shred white"]},
    "FG-02-0100": {"name": "Allana Pizza Cheese 70/30 Shredded White", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["allana 70/30", "allana pizza 70/30"]},
    "FG-02-0162": {"name": "Allana Mozzarella Block W.Poly", "pack": "block", "pcs_ctn": 10, "kg": 2, "keywords": ["allana wpoly mozzarella block"]},
    "FG-02-0164": {"name": "Allana Mozzarella Shredded White W.Poly", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["allana wpoly mozzarella shred white"]},
    "FG-02-0166": {"name": "Allana Mozzarella Shredded Yellow W.Poly", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["allana wpoly mozzarella shred yellow"]},
    "FG-02-0174": {"name": "Allana Pizza Cheese 70/30 White W.Poly", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["allana wpoly 70/30"]},
    "FG-02-0182": {"name": "Allana Pizza Cheese 50/50 White W.Poly", "pack": "regular", "pcs_ctn": 5, "kg": 2, "keywords": ["allana wpoly 50/50"]},
})

# ============================================================
# NORMALIZATION / PARSING
# ============================================================
def norm(s):
    s = str(s).lower().strip()
    replacements = {
        "shared": "shred", "shraded": "shredded", "shrad": "shred",
        "shrd": "shred", "shreded": "shredded",
        "chadder": "cheddar", "chaddar": "cheddar", "cheder": "cheddar",
        "cheedar": "cheddar", "chesse": "cheese",
        "accha": "achha", "acha": "achha",
        "locl": "local", "lockl": "local",
        "70.30": "70/30",
        "70.30": "70/30",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s)

def find_product(text):
    t = norm(text)

    # Explicit / high-priority mappings first.
    priority = [
        ("red mozz blk", "FG-01-0006"),
        ("red mozzarella block", "FG-01-0006"),
        ("blue shredd", "FG-01-0042"),
        ("blue shred", "FG-01-0042"),
        ("danish mozzarella block", "FG-01-0018"),
        ("danish mozz block", "FG-01-0018"),
        ("classic mozzarella block", "FG-01-0012"),
        ("classic mozz block", "FG-01-0012"),
        ("burger slice", "FG-02-0028"),
        ("orange slice", "FG-02-0028"),
    ]
    for key, code in priority:
        if key in t:
            return code

    # Slice: 800gm takes priority; otherwise 1kg.
    if "slice" in t:
        is_white = "white" in t
        is_yellow = ("yellow" in t or "orange" in t or "burger" in t)
        is_jal = "jalapeno" in t or "jal" in t
        is_800 = any(x in t for x in ["800", "800gm", "800 gm", ".8", "0.8"])
        if is_jal:
            return "FG-02-0039"
        if is_white:
            return "FG-02-0037" if is_800 else "FG-02-0023"
        if is_yellow:
            return "FG-02-0038" if is_800 else "FG-02-0028"

    # Explicit 2kg burger slice means 2 packets of yellow slice.
    if "burger" in t and "2 kg" in t:
        return "FG-02-0028"

    # Specific families.
    if "local" in t and "70/30" in t:
        return "FG-03-0018"
    if ("new" in t or "m3" in t) and "70/30" in t:
        return "FG-02-0051"
    if "imp" in t and "70/30" in t:
        return "FG-03-0006"
    if "classic" in t and "70/30" in t:
        return "FG-02-0072"
    if "achha" in t and "yellow" in t and "dice" in t:
        return "FG-01-0125"
    if "achha" in t and "white" in t and "dice" in t:
        return "FG-01-0124"
    if "achha" in t and "yellow" in t and "shred" in t:
        return "FG-01-0054"
    if "achha" in t and "shred" in t:
        return "FG-01-0042"
    if "top cow" in t and "yellow" in t:
        return "FG-02-0049"
    if "top cow" in t and "white" in t:
        return "FG-02-0048"
    if "top cow" in t and "cheddar" in t and "block" in t:
        return "FG-02-0068"
    if "top cow" in t and "block" in t:
        return "FG-02-0060"
    if "verona" in t and "block" in t:
        return "FG-03-0025"
    if "verona" in t:
        return "FG-01-0072"
    if "silver" in t and "shred" in t:
        return "FG-01-0110"
    if "silver" in t:
        return "FG-01-0111"
    if "danish" in t and "shred" in t:
        return "FG-01-0030"
    if "danish" in t:
        return "FG-01-0018"
    if "classic" in t and "shred" in t:
        return "FG-02-0036"
    if "classic" in t and "cheddar" in t and "block" in t:
        return "FG-02-0012"
    if "pizza cheddar" in t or ("pizza" in t and "cheddar" in t and "block" in t):
        return "FG-02-0006"

    # Nivora
    for key, code in [
        ("mf white", "FG-02-0102"), ("mf yellow", "FG-02-0104"),
        ("pro white", "FG-02-0106"), ("pro w", "FG-02-0106"),
        ("pro yellow", "FG-02-0108"),
        ("max white", "FG-02-0110"), ("max yellow", "FG-02-0112"),
        ("pt white", "FG-02-0118"), ("pt w", "FG-02-0118"),
        ("pt yellow", "FG-02-0120"), ("pt y", "FG-02-0120"),
        ("vf white", "FG-02-0114"), ("vf yellow", "FG-02-0116"),
    ]:
        if key in t:
            return code

    # Generic mozzarella block default = Achha, but ONLY if Danish/Classic/etc.
    # did not match above.
    if "mozzarella block" in t or "mozz block" in t or "mozz blk" in t:
        return "FG-01-0006"

    # Exact dictionary keyword fallback, longest first.
    candidates = []
    for code, p in PRODUCTS.items():
        for k in p["keywords"]:
            if k in t:
                candidates.append((len(k), code))
    if candidates:
        return sorted(candidates, reverse=True)[0][1]
    return None

def parse_quantity(line):
    t = norm(line)

    # Special case: "2 kg burger slice" = 2 packets, not 2 ctn.
    m = re.search(r"(\d+(?:\.\d+)?)\s*kg\s+.*burger\s*(?:/|or)?\s*(?:orange)?\s*slice", t)
    if m:
        return int(float(m.group(1))), "PKT"

    # Generic quantity.
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ctn|carton|cartons|pkt|packet|packets|pcs|pc|units?|kg)?\b", t)
    if not m:
        return None, None
    qty = float(m.group(1))
    unit = (m.group(2) or "").lower()

    if qty.is_integer():
        qty = int(qty)

    if unit in ("ctn", "carton", "cartons"):
        return qty, "CTN"
    if unit in ("pkt", "packet", "packets", "pcs", "pc", "unit", "units"):
        return qty, "PKT"
    if unit == "kg":
        return qty, "KG"

    # Historical default: ambiguous larger quantities are treated as CTN.
    return qty, "CTN" if qty > 10 else "PKT"

def parse_order(text):
    lines = [x.strip() for x in str(text).splitlines() if x.strip()]
    rows = []
    customer = ""
    for i, line in enumerate(lines):
        # If first line is not an order line, treat it as customer.
        if i == 0 and not re.search(r"\d", line):
            customer = line.strip()
            continue

        code = find_product(line)
        qty, unit = parse_quantity(line)

        if not code or qty is None:
            rows.append({
                "Source": line,
                "Customer": customer,
                "FG Code": "UNMAPPED",
                "Product": "",
                "Input Qty": qty,
                "Input Unit": unit,
                "SAP Qty (PKT)": "",
                "Status": "CHECK MAPPING",
            })
            continue

        p = PRODUCTS[code]

        # KG input.
        if unit == "KG":
            sap_qty = round(qty / p["kg"])
        elif unit == "CTN":
            sap_qty = int(qty * p["pcs_ctn"])
        else:
            sap_qty = int(qty)

        rows.append({
            "Source": line,
            "Customer": customer,
            "FG Code": code,
            "Product": p["name"],
            "Input Qty": qty,
            "Input Unit": unit,
            "SAP Qty (PKT)": sap_qty,
            "Status": "OK",
        })
    return customer, rows

def sap_line(code, qty):
    # EXACT requested SAP format:
    # FG CODE + 2 TABS + QTY + 5 TABS + HO-WH + 2 TABS + CHEESE
    return f"{code}\t\t{int(qty)}\t\t\t\t\tHO-WH\t\tCHEESE"

def extract_excel(file):
    xls = pd.ExcelFile(file)
    frames = []
    for sheet in xls.sheet_names:
        df = pd.read_excel(file, sheet_name=sheet)
        if not df.empty:
            df["__sheet__"] = sheet
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

def normalize_columns(df):
    d = df.copy()
    d.columns = [str(c).strip().lower() for c in d.columns]
    return d

def process_tabular(df):
    d = normalize_columns(df)
    code_col = next((c for c in d.columns if "sap" in c and "code" in c), None)
    product_col = next((c for c in d.columns if "product" in c or "description" in c or "item" in c), None)
    ctn_col = next((c for c in d.columns if "carton" in c or c == "ctn"), None)
    unit_col = next((c for c in d.columns if c in ("units", "unit", "pcs", "qty", "quantity")), None)
    customer_col = next((c for c in d.columns if "customer" in c or "party" in c), None)

    output = []
    for _, r in d.iterrows():
        customer = str(r.get(customer_col, "")).strip() if customer_col else ""
        code = str(r.get(code_col, "")).strip() if code_col else ""
        product = str(r.get(product_col, "")).strip() if product_col else ""

        if code not in PRODUCTS:
            code = find_product(product)

        if not code:
            continue

        try:
            units = float(r.get(unit_col, 0)) if unit_col else 0
        except Exception:
            units = 0

        try:
            ctn = float(r.get(ctn_col, 0)) if ctn_col else 0
        except Exception:
            ctn = 0

        # Units column is preferred because SAP needs packets/units.
        if units > 0:
            sap_qty = int(units)
        elif ctn > 0:
            sap_qty = int(ctn * PRODUCTS[code]["pcs_ctn"])
        else:
            continue

        output.append({
            "Customer": customer,
            "FG Code": code,
            "Product": PRODUCTS[code]["name"],
            "SAP Qty (PKT)": sap_qty,
            "Source": "Excel",
            "Status": "OK",
        })
    return pd.DataFrame(output)

# ============================================================
# UI
# ============================================================
st.title("🧀 Cheese Order Parser → SAP")
st.caption("Paste WhatsApp orders or upload Excel/CSV files. Every customer is kept separate.")

with st.sidebar:
    st.header("Rules")
    st.write("• SAP quantity = PKT/Units")
    st.write("• CTN is converted automatically")
    st.write("• 2kg block = 10 PKT/CTN")
    st.write("• 2kg shred/dice = 5 PKT/CTN")
    st.write("• Nivora 2.5kg = 4 PKT/CTN")
    st.write("• Slice = 18 PKT/CTN")
    st.write("• 800gm slice preferred when explicitly stated")
    st.write("• Top Cow white/yellow dice and shred use the same FG family mapping")
    st.write("• Red mozz blk = Achha Mozz Block")
    st.write("• Blue shredd = Achha Mozz Shredded")
    st.write("• Danish Mozz Block = Danish, never Achha")

tab1, tab2 = st.tabs(["📱 WhatsApp / Text", "📊 Excel / CSV"])

with tab1:
    st.subheader("Paste order")
    text = st.text_area(
        "Customer + order lines",
        height=260,
        placeholder="Customer Name\n3 CTN 70/30 local\n1 CTN 70/30 new\n1 CTN mozzarella shredded",
    )

    if st.button("Parse Text", type="primary"):
        if not text.strip():
            st.warning("Paste an order first.")
        else:
            customer, rows = parse_order(text)

            if customer:
                st.markdown(f"### {customer}")

            ok = [r for r in rows if r["Status"] == "OK"]
            bad = [r for r in rows if r["Status"] != "OK"]

            # Merge duplicate products within the SAME customer only.
            merged = {}
            for r in ok:
                merged[r["FG Code"]] = merged.get(r["FG Code"], 0) + int(r["SAP Qty (PKT)"])

            st.subheader("SAP Paste Format")
            if merged:
                sap = "\n".join(sap_line(c, q) for c, q in merged.items())
                st.code(sap, language="text")
                st.download_button(
                    "Download SAP Order",
                    sap,
                    file_name=f"{customer or 'order'}_SAP.txt",
                    mime="text/plain",
                )

            if bad:
                st.error("These lines need manual checking:")
                st.dataframe(pd.DataFrame(bad), use_container_width=True)

            st.subheader("Triple-check")
            check_df = pd.DataFrame(ok)
            if not check_df.empty:
                st.dataframe(
                    check_df[["Source", "FG Code", "Product", "Input Qty", "Input Unit", "SAP Qty (PKT)"]],
                    use_container_width=True,
                )

with tab2:
    st.subheader("Upload Excel / CSV")
    uploaded = st.file_uploader(
        "Supported: XLSX, XLS, CSV",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
    )

    if uploaded and st.button("Process Files", type="primary"):
        all_frames = []
        for f in uploaded:
            try:
                if f.name.lower().endswith(".csv"):
                    df = pd.read_csv(f)
                else:
                    df = extract_excel(f)
                result = process_tabular(df)
                if not result.empty:
                    result["Source File"] = f.name
                    all_frames.append(result)
            except Exception as e:
                st.error(f"{f.name}: {e}")

        if all_frames:
            final = pd.concat(all_frames, ignore_index=True)

            # IMPORTANT: customer-wise separation.
            # Never combine the same product across different customers.
            grouped = (
                final.groupby(["Customer", "FG Code", "Product"], dropna=False)["SAP Qty (PKT)"]
                .sum()
                .reset_index()
            )

            st.success(f"Processed {len(grouped)} customer/product lines.")
            st.dataframe(grouped, use_container_width=True)

            st.subheader("Customer-wise SAP Orders")
            customers = grouped["Customer"].fillna("").replace("nan", "").unique()

            txt_parts = []
            for cust in customers:
                cust_df = grouped[grouped["Customer"].fillna("") == cust]
                title = cust if cust else "UNKNOWN CUSTOMER"
                st.markdown(f"#### {title}")

                lines = [
                    sap_line(row["FG Code"], row["SAP Qty (PKT)"])
                    for _, row in cust_df.iterrows()
                ]
                block = "\n".join(lines)
                st.code(block, language="text")

                txt_parts.append(f"### {title}\n{block}")

            combined = "\n\n".join(txt_parts)
            st.download_button(
                "Download All Customer Orders",
                combined,
                file_name="SAP_Orders_All_Customers.txt",
                mime="text/plain",
            )
        else:
            st.warning("No valid order rows found.")

st.divider()
st.caption("SAP format: FG CODE + 2 tabs + QTY in PKT + 5 tabs + HO-WH + 2 tabs + CHEESE")
