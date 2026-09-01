"""Cheese Order Parser -> SAP (Streamlit UI).

All parsing rules live in core.py; this file only renders them.
"""

from __future__ import annotations

import io
import os

import pandas as pd
import streamlit as st

import core
import extractors
from core import PRODUCTS, Order, load_rules, parse_order, process_tabular, tabular_to_orders, teach_rule

st.set_page_config(page_title="Cheese SAP Order Parser", page_icon="🧀", layout="wide")

RULES = load_rules()


# ---------------------------------------------------------------- helpers


def ai_available() -> bool:
    """True when a Grok/OpenAI key is configured (image reading + segmentation)."""
    for name in ("XAI_API_KEY", "GROK_API_KEY", "OPENAI_API_KEY"):
        try:
            if st.secrets.get(name):
                return True
        except Exception:
            pass
        if os.getenv(name):
            return True
    return False


def ai_text_from_image(data: bytes) -> str:
    """Ask the vision model to transcribe/segment a screenshot into parser text."""
    from ai_order_parser import ai_parse_order_image, ai_to_parser_text

    result = ai_parse_order_image(data)
    return ai_to_parser_text(result)


def ai_clean_text(text: str) -> str:
    from ai_order_parser import ai_parse_order_text, ai_to_parser_text

    result = ai_parse_order_text(text)
    return ai_to_parser_text(result) or text


def orders_to_frame(orders, only_ok: bool = True) -> pd.DataFrame:
    rows = []
    for order in orders:
        for line in order.lines:
            if only_ok and not line.ok:
                continue
            rows.append({
                "Customer": order.title,
                "Order line": line.source,
                "FG Code": line.code or "UNMAPPED",
                "Product": line.product,
                "Read as": line.quantity_text,
                "SAP Qty (PKT)": line.sap_units,
                "Status": line.status,
                "Note": line.note,
            })
    return pd.DataFrame(rows)


def render_order(order: Order, key: str) -> None:
    st.markdown(f"### 🧾 {order.title}")
    merged = order.merged()
    if merged:
        st.caption("SAP paste block — FG code + 2 tabs + qty + 5 tabs + HO-WH + 2 tabs + CHEESE")
        st.code(order.sap_text(), language="text")
        columns = st.columns([1, 1, 3])
        columns[0].download_button(
            "⬇️ Download SAP block",
            order.sap_text(),
            file_name=f"{(order.customer or 'order').replace(' ', '_')}_SAP.txt",
            mime="text/plain",
            key=f"dl_{key}",
        )
        columns[1].metric("SAP units", sum(merged.values()))
    else:
        st.warning("Nothing could be mapped safely for this customer.")

    if order.review_lines:
        st.error(f"{len(order.review_lines)} line(s) need a human decision — they are NOT in the SAP block above.")
        st.dataframe(
            pd.DataFrame([{
                "Order line": line.source,
                "Read as": line.quantity_text or "—",
                "What to check": line.note,
            } for line in order.review_lines]),
            width="stretch",
            hide_index=True,
        )

    if order.ok_lines:
        with st.expander(f"🔍 Triple-check ({len(order.ok_lines)} mapped lines)", expanded=not order.review_lines):
            st.dataframe(
                pd.DataFrame([{
                    "Order line": line.source,
                    "FG Code": line.code,
                    "Product": line.product,
                    "Read as": line.quantity_text,
                    "SAP Qty (PKT)": line.sap_units,
                    "Why": line.note,
                } for line in order.ok_lines]),
                width="stretch",
                hide_index=True,
            )
    if order.ignored:
        with st.expander(f"🗑️ Ignored text ({len(order.ignored)})", expanded=False):
            st.write(", ".join(order.ignored))


def render_result(result: dict, index: int) -> None:
    orders = result["orders"]
    st.markdown(f"## 📥 {result['label']}")
    if result.get("info"):
        st.caption(result["info"])
    if not orders:
        st.warning("No order lines were detected.")
    total_ok = sum(len(order.ok_lines) for order in orders)
    total_review = sum(len(order.review_lines) for order in orders)
    summary = st.columns(3)
    summary[0].metric("Customers", len(orders))
    summary[1].metric("Mapped lines", total_ok)
    summary[2].metric("Needs review", total_review)
    for position, order in enumerate(orders):
        render_order(order, key=f"{index}_{position}")
        st.divider()
    if len(orders) > 1:
        combined = "\n\n".join(f"### {order.title}\n{order.sap_text()}" for order in orders if order.merged())
        st.download_button(
            "⬇️ Download every customer (one file)",
            combined,
            file_name="SAP_orders_all_customers.txt",
            mime="text/plain",
            key=f"dl_all_{index}",
        )
    if result.get("raw_text"):
        with st.expander("📄 Text the parser read", expanded=False):
            st.text(result["raw_text"][:12000])


def add_result(label: str, orders, raw_text: str = "", info: str = "") -> None:
    st.session_state.results.append({"label": label, "orders": orders, "raw_text": raw_text, "info": info})


# ---------------------------------------------------------------- sidebar

if "results" not in st.session_state:
    st.session_state.results = []

with st.sidebar:
    st.header("⚙️ Parser settings")
    unit_choice = st.selectbox(
        "Quantity written without a unit",
        ["Flag for review (safest)", "Treat as CTN", "Treat as PKT"],
        help="Example: “20 achha shredd”. The master rules say an unknown unit must be reviewed, not guessed.",
    )
    assume_unit = {"Treat as CTN": "CTN", "Treat as PKT": "PKT"}.get(unit_choice)
    nivora_dice = st.toggle(
        "“MF White” style Nivora lines mean Dice",
        value=False,
        help="Nivora Shredded and Dice are different SKUs. Off = a Nivora line without Dice/Shredded is "
             "sent to review; on = it is treated as Dice.",
    )
    default_form = "dice" if nivora_dice else None

    ai_on = False
    if ai_available():
        ai_on = st.toggle("Use AI to read screenshots / messy text", value=True,
                          help="Grok/OpenAI vision is used to transcribe screenshots. Mapping always stays deterministic.")
    else:
        st.info("No AI key configured — screenshots are read with local OCR (Tesseract).")
    if not extractors.tesseract_available():
        st.caption("⚠️ Tesseract OCR is not installed here, so local image reading is unavailable.")

    st.divider()
    st.header("🧠 Parser memory")
    st.metric("Item master SKUs", len(PRODUCTS))
    st.metric("Saved aliases", len(RULES.get("product_aliases", [])))
    st.metric("Saved rules", sum(len(RULES.get(key, [])) for key in ("general_rules", "customer_rules", "quantity_rules")))
    with st.expander("Locked business rules", expanded=False):
        st.markdown(
            "- SAP quantity is always **PKT / units**\n"
            "- 2kg block **10 PKT/CTN**, 2kg shred/dice **5**, slice **18**, Nivora 2.5kg **4**\n"
            "- **CTN** is converted, **PKT is never multiplied**\n"
            "- Red mozz blk → Achha Mozz Block, Blue shredd → Achha Mozz Shredded\n"
            "- Danish Mozz Block is Danish, **never** Achha\n"
            "- Top Cow shred = Top Cow dice (same SKU); **Nivora shred ≠ dice**\n"
            "- Burger / Orange = Yellow Slice; slice defaults to 1kg unless 800gm is written\n"
            "- “2 kg burger slice” = **2 PKT**, not 2 CTN\n"
            "- Salted butter = Yellow, Unsalted = White\n"
            "- **WP / W.Poly codes only when WP is written**\n"
            "- Customers are never merged; unknown items go to review"
        )
    if st.button("🧹 Clear results"):
        st.session_state.results = []
        st.rerun()

# ---------------------------------------------------------------- main

st.title("🧀 Cheese Order Parser → SAP")
st.caption("Paste a WhatsApp order, drop screenshots, PDFs, Word, Excel or CSV. "
           "Every customer is kept separate and anything unclear is flagged instead of guessed.")

order_tab, excel_tab, teach_tab, master_tab = st.tabs(
    ["🤖 Smart order input", "📊 Excel / CSV", "🎓 Teach the parser", "📚 Item master"]
)

with order_tab:
    submission = st.chat_input(
        "Type/paste the order — or attach screenshots, PDF, Word, Excel, CSV",
        accept_file="multiple",
        file_type=sorted(extractors.ALL_EXTS),
        max_upload_size=200,
        key="smart_order_input",
    )

    if submission is not None:
        message = (getattr(submission, "text", "") or "").strip()
        files = list(getattr(submission, "files", []) or [])
        st.session_state.results = []
        progress = st.progress(0.0, text="Starting…")

        if message:
            text = message
            info = ""
            if ai_on:
                try:
                    progress.progress(0.2, text="AI is tidying the message…")
                    cleaned = ai_clean_text(message)
                    if cleaned.strip():
                        text, info = cleaned, "AI segmented the message; mapping and quantities are deterministic."
                except Exception as error:
                    info = f"AI unavailable ({type(error).__name__}) — the built-in parser was used."
            progress.progress(0.5, text="Mapping products…")
            add_result("Typed order", parse_order(text, RULES, assume_unit=assume_unit, default_form=default_form), text, info)

        for number, uploaded in enumerate(files, 1):
            progress.progress(min(0.9, number / max(1, len(files))), text=f"Reading {uploaded.name}…")
            try:
                kind, content = extractors.read_uploaded_file(uploaded)
                if kind in ("excel", "csv"):
                    frame = process_tabular(content, RULES)
                    add_result(uploaded.name, tabular_to_orders(frame),
                               info=f"{len(frame)} row(s) read from the sheet.")
                    continue
                if kind == "image":
                    text, info = "", ""
                    if ai_on:
                        try:
                            text = ai_text_from_image(content)
                            info = "Screenshot read by the vision model."
                        except Exception as error:
                            info = f"Vision unavailable ({type(error).__name__}) — local OCR was used."
                    if not text.strip():
                        if not extractors.tesseract_available():
                            st.error(f"{uploaded.name}: no AI key and Tesseract OCR is not installed, so this image cannot be read.")
                            continue
                        text = extractors.ocr_image(content)
                        info = info or "Screenshot read with local OCR — please check the quantities."
                else:
                    text, info = str(content), ""
                if not text.strip():
                    st.warning(f"{uploaded.name}: no readable text found.")
                    continue
                add_result(uploaded.name, parse_order(text, RULES, assume_unit=assume_unit, default_form=default_form), text, info)
            except Exception as error:  # noqa: BLE001 - surfaced to the user
                st.error(f"{uploaded.name}: {error}")
        progress.progress(1.0, text="Done")
        progress.empty()

    if st.session_state.results:
        for index, result in enumerate(st.session_state.results):
            render_result(result, index)
    else:
        st.info(
            "**Example**\n\n"
            "```\nBabar Ali\n3 ctn 70/30 lockl\n2 ctn blue shredd\n1 ctn danish mozz blk\n2 kg burger slice\n\n"
            "Cheese Wala Traders\n4 ctn top cow yellow shred\n```"
        )

with excel_tab:
    st.subheader("Order sheets (XLSX / XLS / CSV)")
    st.caption("Reads SAP code / product / cartons / units columns and verifies Units = Cartons × PCS per CTN.")
    uploads = st.file_uploader("Upload one or more sheets", type=["xlsx", "xls", "csv"],
                               accept_multiple_files=True, key="excel_upload")
    if uploads and st.button("Process sheets", type="primary"):
        frames = []
        for uploaded in uploads:
            try:
                kind, content = extractors.read_uploaded_file(uploaded)
                frame = process_tabular(content, RULES)
                if not frame.empty:
                    frame["Source File"] = uploaded.name
                    frames.append(frame)
            except Exception as error:  # noqa: BLE001
                st.error(f"{uploaded.name}: {error}")
        if frames:
            combined = pd.concat(frames, ignore_index=True)
            st.dataframe(combined, width="stretch", hide_index=True)
            for position, order in enumerate(tabular_to_orders(combined)):
                render_order(order, key=f"sheet_{position}")
                st.divider()
        else:
            st.warning("No mappable rows were found in these sheets.")

with teach_tab:
    st.subheader("🎓 Teach the parser a new name")
    st.write("Write the rule once and it is remembered in `rules.json`. "
             "Aliases you teach are applied **before** the built-in rules.")
    rule_text = st.text_area(
        "Rule",
        height=150,
        placeholder="Examples:\nmf white dice = FG-02-0102\nCustomer ABC calls Nivora Pro White Shredded 'pro w shred' = FG-02-0105",
        key="teach_text",
    )
    left, right = st.columns(2)
    category = left.selectbox("Rule type", ["product alias", "general", "customer", "quantity / conversion"])
    customer = right.text_input("Customer (optional)", placeholder="Only for a customer-specific rule")
    if st.button("💾 Save rule", type="primary"):
        ok, message = teach_rule(rule_text, "general" if category == "product alias" else category, customer)
        if ok:
            st.success(message)
            RULES = load_rules()
        else:
            st.warning(message)

    st.divider()
    st.subheader("Saved memory")
    aliases = RULES.get("product_aliases", [])
    if aliases:
        st.dataframe(
            pd.DataFrame([{
                "Alias": entry.get("alias", ""),
                "FG Code": entry.get("code", ""),
                "Product": PRODUCTS.get(entry.get("code", ""), {}).get("name", ""),
                "Taught by you": "yes" if entry.get("source") == "user" or entry.get("note") else "built-in",
            } for entry in aliases]),
            width="stretch",
            hide_index=True,
        )
    for label, key in (("General rules", "general_rules"), ("Customer rules", "customer_rules"),
                       ("Quantity rules", "quantity_rules")):
        items = RULES.get(key, [])
        if items:
            st.markdown(f"**{label}**")
            for position, entry in enumerate(items, 1):
                suffix = f" — {entry.get('customer')}" if entry.get("customer") else ""
                st.write(f"{position}. {entry.get('rule', '')}{suffix}")

with master_tab:
    st.subheader("📚 SAP item master")
    query = st.text_input("Search product or FG code", placeholder="e.g. top cow, slice, FG-01-0042")
    frame = pd.DataFrame([{
        "FG Code": code,
        "Product": product["name"],
        "PKT / CTN": product["pcs_ctn"],
        "KG / PKT": product["kg"],
        "Packing": product["pack"],
    } for code, product in sorted(PRODUCTS.items(), key=lambda item: item[1]["name"])])
    if query.strip():
        mask = frame.apply(lambda row: query.strip().lower() in " ".join(map(str, row.values)).lower(), axis=1)
        frame = frame[mask]
    st.dataframe(frame, width="stretch", hide_index=True, height=520)
    st.caption(f"{len(frame)} of {len(PRODUCTS)} items shown. The parser can never output a code outside this list.")

st.divider()
st.caption("SAP format: FG CODE + 2 tabs + QTY (PKT) + 5 tabs + HO-WH + 2 tabs + CHEESE — real tab characters.")
