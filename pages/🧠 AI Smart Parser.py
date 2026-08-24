import io
from pathlib import Path
import streamlit as st

from streamlit_paste_button import paste_image_button
from ai_order_parser import ai_parse_order_text, ai_parse_order_image, ai_to_parser_text

# Reuse the exact parser engine without executing the main page UI.
_app_source = Path("app.py").read_text(encoding="utf-8")
_core_source = _app_source.split('st.title("🧀 Cheese Order Parser → SAP")', 1)[0]
_core = {"__name__": "parser_core"}
exec(_core_source, _core)

parse_order = _core["parse_order"]
show_order_result = _core["show_order_result"]
read_uploaded_file = _core["read_uploaded_file"]
process_tabular = _core["process_tabular"]

st.title("🧠 AI Smart Order Parser")
st.caption("OpenAI AI understands messy WhatsApp orders/screenshots. Your existing product master + rules remain the final authority for FG mapping.")
st.info("Customer codes/IDs are ignored for product mapping. AI only interprets the order; the local parser decides the final FG code.")

use_ai = st.checkbox("Use AI Smart Parsing", value=True)

paste_result = paste_image_button("📋 Paste WhatsApp Screenshot", key="ai_paste_image", errors="ignore")
files = st.file_uploader(
    "📎 DROP FILES / IMAGES HERE",
    type=["png","jpg","jpeg","webp","bmp","tif","tiff","pdf","txt","docx","xlsx","xls","csv"],
    accept_multiple_files=True,
    key="ai_files",
)
text = st.text_area("Or paste WhatsApp order", height=160, placeholder="Customer Name\n2 ctn classic shredd\n3 ctn 50/50")
run_text = st.button("🚀 Parse Order", type="primary")

inputs = []
if paste_result is not None and getattr(paste_result, "image_data", None) is not None:
    buf = io.BytesIO()
    paste_result.image_data.save(buf, format="PNG")
    inputs.append(("clipboard.png", "image", buf.getvalue()))
if run_text and text.strip():
    inputs.append(("pasted_text", "text", text.strip()))
if run_text:
    for f in files or []:
        inputs.append((f.name, "file", f))

for name, kind, payload in inputs:
    st.markdown("---")
    st.subheader(f"📥 {name}")
    try:
        if kind == "image":
            if use_ai:
                ai_result = ai_parse_order_image(payload)
                parser_text = ai_to_parser_text(ai_result)
                customer = ai_result.get("customer_name", "")
                st.json(ai_result)
            else:
                parser_text = _core["ocr_image"](payload)
                ai_result = {"customer_name": "", "items": []}
                customer = ""
        elif kind == "text":
            if use_ai:
                ai_result = ai_parse_order_text(payload)
                parser_text = ai_to_parser_text(ai_result)
                customer = ai_result.get("customer_name", "")
                st.json(ai_result)
            else:
                parser_text = payload
                ai_result = {"customer_name": "", "items": []}
                customer = ""
        else:
            ext = Path(payload.name).suffix.lower()
            if ext in {".xlsx", ".xls", ".csv"}:
                raw = payload.getvalue()
                import pandas as pd
                df = pd.read_csv(io.BytesIO(raw)) if ext == ".csv" else _core["extract_excel"](io.BytesIO(raw))
                result = process_tabular(df)
                if result.empty:
                    st.warning("No valid mapped rows found in this spreadsheet.")
                else:
                    st.dataframe(result, use_container_width=True)
                continue
            file_kind, extracted = read_uploaded_file(payload)
            if use_ai:
                ai_result = ai_parse_order_text(str(extracted))
                parser_text = ai_to_parser_text(ai_result)
                customer = ai_result.get("customer_name", "")
                st.json(ai_result)
            else:
                parser_text = str(extracted)
                ai_result = {"customer_name": "", "items": []}
                customer = ""

        if parser_text.strip():
            mapped_customer, rows = parse_order(parser_text)
            final_customer = customer or mapped_customer
            show_order_result(final_customer, rows, name)
        else:
            st.warning("No readable order was detected.")
    except Exception as exc:
        st.error(f"Could not parse {name}: {exc}")

st.caption("AI does not invent FG codes. Final mapping is performed by the existing local product master and rules.json.")
