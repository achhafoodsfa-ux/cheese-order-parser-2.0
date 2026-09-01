"""Screenshot / file only parser page (paste a WhatsApp screenshot or drop a file)."""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

import extractors
from core import PRODUCTS, load_rules, parse_order
from streamlit_paste_button import paste_image_button

st.set_page_config(page_title="Cheese Image / File Parser", page_icon="📋", layout="wide")

RULES = load_rules()


def render(orders, key: str) -> None:
    if not orders:
        st.warning("No order lines were detected.")
        return
    for position, order in enumerate(orders):
        st.markdown(f"### 🧾 {order.title}")
        if order.merged():
            st.code(order.sap_text(), language="text")
            st.download_button(
                "⬇️ Download SAP block",
                order.sap_text(),
                file_name=f"{(order.customer or 'order').replace(' ', '_')}_SAP.txt",
                mime="text/plain",
                key=f"dl_{key}_{position}",
            )
        else:
            st.warning("Nothing could be mapped safely for this customer.")
        if order.review_lines:
            st.error("These lines need a human decision:")
            st.dataframe(
                pd.DataFrame([{"Order line": line.source, "Read as": line.quantity_text or "—",
                               "What to check": line.note} for line in order.review_lines]),
                width="stretch", hide_index=True,
            )
        if order.ok_lines:
            with st.expander("🔍 Triple-check", expanded=False):
                st.dataframe(
                    pd.DataFrame([{"Order line": line.source, "FG Code": line.code, "Product": line.product,
                                   "Read as": line.quantity_text, "SAP Qty (PKT)": line.sap_units}
                                  for line in order.ok_lines]),
                    width="stretch", hide_index=True,
                )
        st.divider()


st.title("📋 Cheese Order — Image / File Parser")
st.caption("Local OCR only (no AI key needed). Customer codes such as CFS-1234 are never matched to a product.")

if not extractors.tesseract_available():
    st.warning("Tesseract OCR is not installed in this environment, so images cannot be read here. "
               "Use the main page (AI vision) or paste the order as text below.")

left, right = st.columns(2)
with left:
    st.subheader("📋 Paste a screenshot")
    pasted = paste_image_button("📋 Paste image from clipboard", key="paste_image")
with right:
    st.subheader("📎 Drag & drop an image")
    uploaded = st.file_uploader("Image file", type=sorted(extractors.IMAGE_EXTS),
                                accept_multiple_files=False, key="image_drop")

st.divider()
st.subheader("📝 Or paste the order as text")
text_input = st.text_area("Order text", height=160,
                          placeholder="Customer Name\n2 ctn 50/50 shredd\n1 ctn classic shredd")
process_text = st.button("🚀 Process text", type="primary")

image_bytes = None
caption = ""
if pasted is not None and getattr(pasted, "image_data", None) is not None:
    buffer = io.BytesIO()
    pasted.image_data.save(buffer, format="PNG")
    image_bytes, caption = buffer.getvalue(), "Clipboard image"
elif uploaded is not None:
    image_bytes, caption = uploaded.getvalue(), uploaded.name

if image_bytes:
    st.image(image_bytes, caption=caption, width="stretch")
    try:
        extracted = extractors.ocr_image(image_bytes)
    except Exception as error:  # noqa: BLE001
        st.error(f"OCR failed: {error}")
        extracted = ""
    with st.expander("🔎 OCR text", expanded=False):
        st.text(extracted[:12000])
    if extracted.strip():
        render(parse_order(extracted, RULES), key="image")
    else:
        st.error("No readable text was detected in this image.")
elif process_text and text_input.strip():
    render(parse_order(text_input, RULES), key="text")

st.info(f"Item master loaded: {len(PRODUCTS)} SAP items. The parser can never output a code outside this list.")
