import base64
import io
import json
import os
import re
from typing import Any, Dict, List

from PIL import Image, ImageFilter, ImageOps
import pytesseract
from openai import OpenAI, RateLimitError, APIError, APITimeoutError, APIConnectionError

GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

SCHEMA = {
    "type": "object",
    "properties": {
        "orders": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "customer_name": {"type": "string"},
                    "items": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "raw_text": {"type": "string"},
                            "product": {"type": "string"},
                            "quantity": {"type": "number"},
                            "unit": {"type": "string", "enum": ["CTN", "PKT", "KG", "PCS"]}
                        },
                        "required": ["raw_text", "product", "quantity", "unit"],
                        "additionalProperties": False
                    }}
                },
                "required": ["customer_name", "items"],
                "additionalProperties": False
            }
        }
    },
    "required": ["orders"],
    "additionalProperties": False
}

INSTRUCTIONS = """
You are the reasoning brain for a cheese order parser.

MULTI-CUSTOMER WHATSAPP RULE — THIS IS CRITICAL:
- One screenshot can contain 5, 10, or more customers.
- FIRST find customer/order blocks. ONLY THEN read products inside each block.
- A customer heading/sender name followed by product lines starts an order block.
- A blank line or a new customer heading normally ends the previous block.
- NEVER combine lines from different customers into one order.
- Return ONE object in orders[] for EACH distinct visible customer/order block.
- Read the ENTIRE screenshot top-to-bottom. Do not stop at the first order.
- Preserve customer names exactly as visible where possible.
- If a customer name is hard to read, make a best-effort name from the visible sender text; NEVER silently merge that block into another customer.

PRODUCT RULES:
- Classic shredd/shredded -> FG-02-0036.
- 50/50 shredd/shredded -> Imported 50/50 2kg -> FG-03-0024.
- Top Cow only: white shredded = white dice; yellow shredded = yellow dice.
- Dice, shredded and block remain DISTINCT for all other products.
- Achha White Dice -> FG-01-0124.
- Box/carton/CTN = CTN.
- 70/30 and 50/50 are ratios, not quantities.
- 2kg, 2.5kg, 1kg, 800gm are product attributes, not quantities, unless explicitly ordered.
- Example: '70/30 shredded local 10 ctn' => quantity 10 CTN.
- Ignore phone numbers, dates, prices, invoice numbers, greetings, addresses and customer codes for product mapping.
- Never invent FG codes; local master mapping is authoritative.
""".strip()


def _secret(name: str) -> str | None:
    try:
        import streamlit as st
        value = st.secrets.get(name)
        if value:
            return str(value)
    except Exception:
        pass
    return os.getenv(name)


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("AI response was not an object")
    return data


def _normalize(data: Dict[str, Any]) -> Dict[str, Any]:
    out = []
    for order in data.get("orders", []):
        customer = str(order.get("customer_name", "")).strip()
        items = []
        for item in order.get("items", []):
            product = str(item.get("product", "")).strip()
            if not product:
                continue
            items.append({
                "raw_text": str(item.get("raw_text", "")).strip(),
                "product": product,
                "quantity": item.get("quantity"),
                "unit": str(item.get("unit", "PKT")).upper(),
            })
        if customer or items:
            out.append({"customer_name": customer, "items": items})
    return {"orders": out}


def _prepare_image(image_bytes: bytes) -> tuple[bytes, str]:
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = image.size
    m = max(w, h)
    if m < 3200:
        s = 3200 / m
        image = image.resize((int(w*s), int(h*s)), Image.Resampling.LANCZOS)
    elif m > 6000:
        s = 6000 / m
        image = image.resize((int(w*s), int(h*s)), Image.Resampling.LANCZOS)
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.SHARPEN)
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=94, optimize=True)
    return out.getvalue(), "image/jpeg"


def _ocr_image(image_bytes: bytes) -> str:
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        gray = ImageOps.grayscale(image)
        gray = ImageOps.autocontrast(gray)
        if max(gray.size) < 3200:
            s = 3200 / max(gray.size)
            gray = gray.resize((int(gray.size[0]*s), int(gray.size[1]*s)), Image.Resampling.LANCZOS)
        gray = gray.filter(ImageFilter.SHARPEN)
        texts = []
        for psm in (6, 11):
            t = pytesseract.image_to_string(gray, config=f"--psm {psm}").strip()
            if t:
                texts.append(t)
        return "\n\n--- OCR PASS ---\n\n".join(texts)
    except Exception:
        return ""


def _looks_like_product(line: str) -> bool:
    t = line.lower()
    if re.search(r"\b(?:ctn|carton|cartons|box|boxes|pkt|packet|packets|pcs|pc|blk|block|kg)\b", t):
        return True
    return bool(re.search(r"cheese|cheddar|mozz|mozzarella|shred|shredded|dice|block|slice|butter|ghee|nivora|latina|verona|danish|top cow|achha|allana|50/50|70/30|pizza|silver|imported|local|classic", t))


def _is_probable_customer_heading(line: str) -> bool:
    t = line.strip()
    if not t or _looks_like_product(t):
        return False
    if re.search(r"\b(?:ctn|carton|cartons|box|boxes|pkt|packet|packets|pcs|pc|kg|blk|block)\b", t, re.I):
        return False
    if re.search(r"\d", t):
        return False
    if len(t.split()) > 10:
        return False
    return True


def _segment_customer_blocks(ocr: str) -> str:
    """Turn OCR text into explicit CUSTOMER BLOCK markers before sending to vision."""
    if not ocr.strip():
        return ""
    lines = [re.sub(r"\s+", " ", x).strip() for x in ocr.splitlines()]
    blocks = []
    current_name = None
    current = []
    for line in lines:
        if not line:
            continue
        if _is_probable_customer_heading(line):
            if current_name and current:
                blocks.append((current_name, current))
            current_name = line
            current = []
        elif current_name:
            current.append(line)
    if current_name and current:
        blocks.append((current_name, current))
    if not blocks:
        return ocr
    parts = []
    for i, (name, lines_) in enumerate(blocks, 1):
        parts.append(f"=== CUSTOMER BLOCK {i} ===\nCUSTOMER: {name}\n" + "\n".join(lines_))
    return "\n\n".join(parts)


def _call_groq_text(text: str) -> Dict[str, Any]:
    key = _secret("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "system", "content": INSTRUCTIONS}, {"role": "user", "content": text}],
        response_format={"type": "json_object"}, temperature=0, max_tokens=12000,
    )
    return _normalize(_parse_json(r.choices[0].message.content))


def _call_groq_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    key = _secret("GROQ_API_KEY")
    client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured")
    prepared, pmime = _prepare_image(image_bytes)
    ocr_raw = _ocr_image(prepared)
    segmented = _segment_customer_blocks(ocr_raw)
    data_url = f"data:{pmime};base64," + base64.b64encode(prepared).decode("ascii")
    prompt = f"""Read the ENTIRE WhatsApp screenshot top-to-bottom.

The OCR channel has already detected these possible customer blocks. Use them as anchors, then verify against the image:

{segmented or '[OCR did not find clear blocks]'}

Rules:
- Return EVERY customer block as a separate orders[] object.
- Never merge two blocks.
- Keep every product line with the block where it appears.
- Read all visible blocks, not only the first one.
- OCR can be wrong; the image is authoritative.

Return all orders in JSON."""
    r = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}
        ],
        response_format={"type": "json_object"}, temperature=0, max_tokens=12000,
    )
    return _normalize(_parse_json(r.choices[0].message.content))


def _call_openai_text(text: str) -> Dict[str, Any]:
    key = _secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    r = OpenAI(api_key=key).responses.create(
        model=OPENAI_MODEL, store=False, instructions=INSTRUCTIONS, input=text,
        text={"format": {"type": "json_schema", "name": "cheese_orders", "schema": SCHEMA, "strict": True}},
    )
    return _normalize(_parse_json(r.output_text))


def _call_openai_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    key = _secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    prepared, pmime = _prepare_image(image_bytes)
    segmented = _segment_customer_blocks(_ocr_image(prepared))
    data_url = f"data:{pmime};base64," + base64.b64encode(prepared).decode("ascii")
    prompt = f"Read the whole WhatsApp screenshot. Return one separate orders[] object for EVERY customer block. Never merge blocks. Verify the OCR anchors below against the image:\n\n{segmented or '[No OCR anchors]'}"
    r = OpenAI(api_key=key).responses.create(
        model=OPENAI_MODEL, store=False, instructions=INSTRUCTIONS,
        input=[{"role":"user","content":[
            {"type":"input_text","text":prompt},
            {"type":"input_image","image_url":data_url,"detail":"high"}
        ]}],
        text={"format": {"type": "json_schema", "name": "cheese_orders", "schema": SCHEMA, "strict": True}},
    )
    return _normalize(_parse_json(r.output_text))


def _run(primary, secondary, fallback_text=""):
    try:
        return primary()
    except (RateLimitError, APIError, APITimeoutError, APIConnectionError, RuntimeError, ValueError, json.JSONDecodeError):
        try:
            return secondary()
        except Exception as exc:
            return {"orders": [], "_fallback": True, "_fallback_text": fallback_text, "_fallback_reason": type(exc).__name__}


def parse_orders_text(text: str) -> Dict[str, Any]:
    return _run(lambda: _call_groq_text(text), lambda: _call_openai_text(text), text)


def parse_orders_image(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    return _run(lambda: _call_groq_image(image_bytes, mime), lambda: _call_openai_image(image_bytes, mime), "")


def orders_to_parser_groups(result: Dict[str, Any]) -> List[Dict[str, str]]:
    if result.get("_fallback"):
        return [{"customer_name": "", "parser_text": str(result.get("_fallback_text", ""))}]
    groups = []
    for order in result.get("orders", []):
        name = str(order.get("customer_name", "")).strip()
        lines = [name] if name else []
        for item in order.get("items", []):
            q = item.get("quantity")
            unit = item.get("unit", "PKT")
            product = item.get("product", "")
            if product and q not in (None, ""):
                lines.append(f"{q} {unit} {product}")
        if len(lines) > 1:
            groups.append({"customer_name": name, "parser_text": "\n".join(lines)})
    return groups


def ai_parse_order_text(text: str) -> Dict[str, Any]:
    result = parse_orders_text(text)
    if result.get("orders"):
        first = result["orders"][0]
        return {"customer_name": first.get("customer_name", ""), "items": first.get("items", []), "orders": result.get("orders", []), **{k: result[k] for k in result if k.startswith("_")}}
    return result


def ai_parse_order_image(image_bytes: bytes) -> Dict[str, Any]:
    result = parse_orders_image(image_bytes)
    if result.get("orders"):
        first = result["orders"][0]
        return {"customer_name": first.get("customer_name", ""), "items": first.get("items", []), "orders": result.get("orders", []), **{k: result[k] for k in result if k.startswith("_")}}
    return result


def ai_to_parser_text(result: Dict[str, Any]) -> str:
    if result.get("_fallback"):
        return str(result.get("_fallback_text", ""))
    orders = result.get("orders") or [{"customer_name": result.get("customer_name", ""), "items": result.get("items", [])}]
    lines = []
    for order in orders:
        if order.get("customer_name"):
            lines.append(str(order["customer_name"]))
        for item in order.get("items", []):
            q = item.get("quantity"); unit = item.get("unit", "PKT"); product = item.get("product", "")
            if product and q not in (None, ""):
                lines.append(f"{q} {unit} {product}")
        lines.append("")
    return "\n".join(lines).strip()
