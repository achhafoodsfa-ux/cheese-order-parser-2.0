import base64
import io
import json
import os
import re
from typing import Any, Dict, List

from openai import OpenAI, RateLimitError, APIError, APITimeoutError, APIConnectionError
from PIL import Image, ImageFilter, ImageOps
import pytesseract

GROQ_MODEL=os.getenv("GROQ_MODEL","qwen/qwen3.6-27b")
OPENAI_MODEL=os.getenv("OPENAI_MODEL","gpt-5.6-luna")

SCHEMA={"type":"object","properties":{"orders":{"type":"array","items":{"type":"object","properties":{"customer_name":{"type":"string"},"items":{"type":"array","items":{"type":"object","properties":{"raw_text":{"type":"string"},"product":{"type":"string"},"quantity":{"type":"number"},"unit":{"type":"string","enum":["CTN","PKT","KG","PCS"]}},"required":["raw_text","product","quantity","unit"],"additionalProperties":False}}},"required":["customer_name","items"],"additionalProperties":False}}},"required":["orders"],"additionalProperties":False}

PRODUCT_HINTS=re.compile(r"cheese|cheddar|mozz|mozzarella|shred|shredded|dice|block|slice|butter|ghee|nivora|latina|verona|danish|top cow|achha|allana|50/50|70/30|pizza|silver|imported|local|classic|nishter|red paper",re.I)
NOISE=[r"^[-–—]?\s*forwarded\s*$",r"^self\s*pick\s*$",r"^(today|tomorrow|yesterday|later|thanks|thank you|ok|okay|salam|hello|hi)\s*$",r"^\d{1,2}:\d{2}(?:\s*[ap]m)?(?:\s*[a-z])?$",r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$",r"^[-= ]*ocr(?:\s+pass)?[-= ]*$"]

SYSTEM="""You are a cheese order extraction engine. Your ONLY job is to identify CUSTOMER/ORDER OWNER and PRODUCT + EXPLICIT ORDER QUANTITY.

Hard rules:
- Every distinct customer/order block is a separate order.
- Never merge customers, even if they order the same product.
- Never move a product line from one customer to another.
- Ignore timestamps, Forwarded, Self pick, greetings, chat commentary, addresses, phone numbers, prices, invoices, dates, WhatsApp UI and OCR garbage.
- Clock times are NEVER quantities.
- 70/30, 50/50 and weights such as 2kg are product attributes, not quantities.
- Classic shredd/shredded => FG-02-0036.
- 50/50 shredd/shredded => FG-03-0024.
- Top Cow white shredded/dice and plain Top Cow dice => FG-02-0048.
- Top Cow yellow shredded/dice => FG-02-0049.
- Achha White Dice => FG-01-0124.
- Box/carton/CTN = CTN.
- Example: 70/30 shredded local 10 ctn = 10 CTN.
- Never invent product codes.
Return ALL orders."""

def secret(n):
    try:
        import streamlit as st
        v=st.secrets.get(n)
        if v:return str(v)
    except Exception: pass
    v=os.getenv(n)
    return str(v) if v else None

def parse_json(t):
    t=(t or "").strip()
    if t.startswith("```"):
        t=re.sub(r"^```(?:json)?\s*","",t,flags=re.I);t=re.sub(r"\s*```$","",t)
    return json.loads(t)

def clean_lines(text):
    out=[];seen=set()
    for raw in str(text or "").splitlines():
        line=re.sub(r"\s+"," ",raw).strip()
        if not line:continue
        if any(re.fullmatch(p,line,re.I) for p in NOISE):continue
        k=line.casefold()
        if k in seen:continue
        seen.add(k);out.append(line)
    return out

def looks_product(line):
    t=line.lower()
    return bool(PRODUCT_HINTS.search(t) or re.search(r"\b(?:ctn|carton|box|pkt|packet|pcs|pc|blk|block|kg)\b",t))

def looks_heading(line):
    t=line.strip()
    if not t or looks_product(t):return False
    if re.search(r"\d",t):return False
    if len(t.split())>9:return False
    return True

def segment_blocks(text):
    lines=clean_lines(text)
    candidates=[]
    for i,line in enumerate(lines):
        if not looks_heading(line):continue
        # Heading is valid only if a product line follows before the next probable heading.
        for j in range(i+1,min(i+8,len(lines))):
            if looks_product(lines[j]):
                candidates.append((i,line));break
            if looks_heading(lines[j]):break
    if not candidates:return text
    parts=[]
    for n,(pos,name) in enumerate(candidates):
        stop=candidates[n+1][0] if n+1<len(candidates) else len(lines)
        prod=[x for x in lines[pos+1:stop] if looks_product(x)]
        if prod:parts.append(f"=== CUSTOMER BLOCK {n+1} ===\nCUSTOMER: {name}\n"+"\n".join(prod))
    return "\n\n".join(parts) or text

def canonical_product(p):
    s=re.sub(r"\s+"," ",str(p or "")).strip().lower()
    if re.search(r"top\s*cow.*dice",s) and "yellow" not in s:return "Top Cow White Dice"
    if re.search(r"top\s*cow.*(white\s*)?(shred|shredded)",s) and "yellow" not in s:return "Top Cow White Dice"
    if re.search(r"top\s*cow.*(yellow.*dice|yellow.*shred|yellow.*shredded)",s):return "Top Cow Yellow Dice"
    if re.search(r"classic.*(shred|shredded)",s):return "Classic Mozzarella Shredded"
    if re.search(r"50\s*/\s*50.*(shred|shredded)",s):return "50/50 Shredded"
    if re.search(r"achha.*white.*dice",s):return "Achha White Dice"
    return str(p or "").strip()

def normalize(data):
    orders=[]
    for o in data.get("orders",[]) if isinstance(data,dict) else []:
        name=str(o.get("customer_name","")).strip()
        if not name:continue
        items=[]
        for it in o.get("items",[]):
            p=canonical_product(it.get("product","")); raw=str(it.get("raw_text","")).strip()
            try:q=float(it.get("quantity"))
            except:q=None
            if not p or q is None or q<=0:continue
            u=str(it.get("unit","PKT")).upper()
            if u not in {"CTN","PKT","KG","PCS"}:u="PKT"
            items.append({"raw_text":raw,"product":p,"quantity":q,"unit":u})
        if items:orders.append({"customer_name":name,"items":items})
    return {"orders":orders}

def groq():
    k=secret("GROQ_API_KEY")
    if not k:raise RuntimeError("GROQ_API_KEY is not configured")
    return OpenAI(api_key=k,base_url="https://api.groq.com/openai/v1")

def openai():
    k=secret("OPENAI_API_KEY")
    if not k:raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=k)

def parse_text(text):
    clean=segment_blocks(text)
    r=groq().chat.completions.create(model=GROQ_MODEL,messages=[{"role":"system","content":SYSTEM},{"role":"user","content":"Parse ONLY this order text. Each CUSTOMER BLOCK must remain a separate order:\n\n"+clean}],response_format={"type":"json_object"},temperature=0,max_tokens=12000)
    return normalize(parse_json(r.choices[0].message.content))

def ocr_image(b):
    try:
        im=Image.open(io.BytesIO(b)).convert("RGB");w,h=im.size
        if max(w,h)<4200:
            s=4200/max(w,h);im=im.resize((int(w*s),int(h*s)),Image.Resampling.LANCZOS)
        g=ImageOps.autocontrast(ImageOps.grayscale(im)).filter(ImageFilter.SHARPEN)
        return pytesseract.image_to_string(g,config="--psm 6").strip()
    except Exception:return ""

def vision_image(b,mime):
    data=f"data:{mime};base64,"+base64.b64encode(b).decode("ascii")
    r=groq().chat.completions.create(model=GROQ_MODEL,messages=[{"role":"system","content":SYSTEM},{"role":"user","content":[{"type":"text","text":"Read the entire screenshot. Return every customer separately. Do not merge customer blocks."},{"type":"image_url","image_url":{"url":data}}]}],response_format={"type":"json_object"},temperature=0,max_tokens=12000)
    return normalize(parse_json(r.choices[0].message.content))

def parse_orders_text(text):
    try:return parse_text(text)
    except (RateLimitError,APIError,APITimeoutError,APIConnectionError,RuntimeError,ValueError,json.JSONDecodeError):
        try:return normalize(parse_json(openai().responses.create(model=OPENAI_MODEL,store=False,instructions=SYSTEM,input=segment_blocks(text),text={"format":{"type":"json_schema","name":"cheese_orders","schema":SCHEMA,"strict":True}}).output_text))
        except Exception as e:return {"orders":[],"_fallback":True,"_fallback_text":text,"_fallback_reason":type(e).__name__}

def parse_orders_image(b,mime="image/png"):
    # First use OCR blocks because customer boundaries are more important than visual guessing.
    ocr=ocr_image(b)
    segmented=segment_blocks(ocr) if ocr else ""
    if segmented and segmented!=ocr:
        r=parse_orders_text(segmented)
        if r.get("orders"):return r
    try:
        r=vision_image(b,mime)
        if r.get("orders"):return r
    except Exception:pass
    if ocr:
        r=parse_orders_text(ocr)
        if r.get("orders"):return r
    try:
        data=f"data:{mime};base64,"+base64.b64encode(b).decode("ascii")
        r=openai().responses.create(model=OPENAI_MODEL,store=False,instructions=SYSTEM,input=[{"role":"user","content":[{"type":"input_text","text":"Return every customer separately; only product lines and quantities."},{"type":"input_image","image_url":data,"detail":"high"}]}],text={"format":{"type":"json_schema","name":"cheese_orders","schema":SCHEMA,"strict":True}})
        return normalize(parse_json(r.output_text))
    except Exception:pass
    return {"orders":[],"_fallback":True,"_fallback_text":ocr,"_fallback_reason":"no_readable_order_detected"}

def orders_to_parser_groups(result):
    if result.get("_fallback") and result.get("_fallback_text"):return [{"customer_name":"","parser_text":result["_fallback_text"]}]
    groups=[]
    for o in result.get("orders",[]):
        lines=[o.get("customer_name","")]
        for it in o.get("items",[]):
            q=float(it["quantity"]);qt=str(int(q)) if q.is_integer() else str(q);lines.append(f"{qt} {it.get('unit','PKT')} {it.get('product','')}")
        if len(lines)>1:groups.append({"customer_name":o.get("customer_name",""),"parser_text":"\n".join(lines)})
    return groups

def ai_parse_order_text(t):
    r=parse_orders_text(t);f=r.get("orders",[{}])[0] if r.get("orders") else {};return {"customer_name":f.get("customer_name",""),"items":f.get("items",[]),**r}

def ai_parse_order_image(b):
    r=parse_orders_image(b);f=r.get("orders",[{}])[0] if r.get("orders") else {};return {"customer_name":f.get("customer_name",""),"items":f.get("items",[]),**r}

def ai_to_parser_text(r):
    if r.get("_fallback") and r.get("_fallback_text"):return r["_fallback_text"]
    return "\n\n".join(g["parser_text"] for g in orders_to_parser_groups(r))
