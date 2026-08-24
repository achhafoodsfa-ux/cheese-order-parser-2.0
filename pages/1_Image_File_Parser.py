import ast
import io
import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps, ImageFilter
import pytesseract
import fitz
from pypdf import PdfReader
from streamlit_paste_button import paste_image_button

st.set_page_config(page_title="Cheese Image / File Parser", page_icon="📋", layout="wide")

APP_FILE = Path(__file__).resolve().parent.parent / "app.py"

def load_core_from_app():
    source = APP_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted = {"norm", "load_rules", "save_rules", "apply_saved_aliases", "find_product", "parse_quantity", "parse_order", "sap_line", "clean_ocr_text", "ocr_image"}
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets = [x.id for x in node.targets if isinstance(x, ast.Name)]
            if "PRODUCTS" in targets or "RULES_FILE" in targets:
                body.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            body.append(node)
    ns = {
        "io": io, "json": json, "re": re, "Path": Path,
        "pd": pd, "Image": Image, "ImageOps": ImageOps, "ImageFilter": ImageFilter,
        "pytesseract": pytesseract, "fitz": fitz, "PdfReader": PdfReader,
    }
    exec(compile(ast.Module(body=body, type_ignores=[]), str(APP_FILE), "exec"), ns)
    ns["RULES"] = ns["load_rules"]()
    return ns

CORE = load_core_from_app()
PRODUCTS = CORE["PRODUCTS"]
find_product = CORE["find_product"]
parse_order = CORE["parse_order"]
sap_line = CORE["sap_line"]
ocr_image = CORE["ocr_image"]

IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "bmp", "tif", "tiff"}


def show_result(customer, rows, source):
    ok = [r for r in rows if r["Status"] == "OK"]
    bad = [r for r in rows if r["Status"] != "OK"]
    if customer:
        st.markdown(f"### {customer}")
    st.subheader("SAP Paste Format")
    merged = {}
    for row in ok:
        merged[row["FG Code"]] = merged.get(row["FG Code"], 0) + int(row["SAP Qty (PKT)"])
    if merged:
        sap = "\n".join(sap_line(code, qty) for code, qty in merged.items())
        st.code(sap, language="text")
        st.download_button("Download SAP Order", sap, file_name="SAP_Order.txt", mime="text/plain", key=f"dl_{abs(hash(source))}")
    else:
        st.warning("No mapped order lines found.")
    if bad:
        st.error("These lines need manual checking")
        st.dataframe(pd.DataFrame(bad), use_container_width=True)
    if ok:
        st.subheader("Triple-check")
        st.dataframe(pd.DataFrame(ok)[["Source", "FG Code", "Product", "Input Qty", "Input Unit", "SAP Qty (PKT)"]], use_container_width=True)

st.title("📋 Cheese Order — Image / File Parser")
st.caption("Product mapping only. Customer codes are ignored by the product matcher.")

col1, col2 = st.columns([1, 1])
with col1:
    st.subheader("📋 Paste WhatsApp Screenshot")
    st.write("Copy the screenshot from WhatsApp, then click **Paste Image**.")
    pasted = paste_image_button("📋 Paste Image from Clipboard", key="paste_image", errors="raise")

with col2:
    st.subheader("📎 Drag / Drop File")
    uploaded = st.file_uploader(
        "Drop image here or browse",
        type=sorted(IMAGE_EXTS),
        accept_multiple_files=False,
        key="image_drop",
    )

st.divider()
st.subheader("📝 Or paste WhatsApp text")
text_input = st.text_area("Order text", height=150, placeholder="Customer Name\n2 CTN 50/50 shredd\n1 CTN Classic shredd")
process_text = st.button("🚀 Process Text", type="primary")

if pasted is not None and getattr(pasted, "image_data", None) is not None:
    image = pasted.image_data
    st.image(image, caption="Clipboard image", use_container_width=True)
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    extracted = ocr_image(buf.getvalue())
    with st.expander("🔎 OCR Text", expanded=False):
        st.text(extracted[:12000])
    if extracted.strip():
        customer, rows = parse_order(extracted)
        show_result(customer, rows, "clipboard")
    else:
        st.error("No readable text detected in the pasted image.")

elif uploaded is not None:
    data = uploaded.getvalue()
    st.image(data, caption=uploaded.name, use_container_width=True)
    extracted = ocr_image(data)
    with st.expander("🔎 OCR Text", expanded=False):
        st.text(extracted[:12000])
    if extracted.strip():
        customer, rows = parse_order(extracted)
        show_result(customer, rows, uploaded.name)
    else:
        st.error("No readable text detected in the uploaded image.")

elif process_text and text_input.strip():
    customer, rows = parse_order(text_input)
    show_result(customer, rows, "text")

st.divider()
st.info("Rule: only product text is mapped. A customer code such as CFS-XXXX is not searched or matched to any product.")
