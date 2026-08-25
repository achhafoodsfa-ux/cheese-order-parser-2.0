import base64
import io
import json
import os
import re
from typing import Any, Dict, List

from openai import OpenAI, RateLimitError, APIError, APITimeoutError, APIConnectionError
from PIL import Image, ImageFilter, ImageOps
import pytesseract

GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

SCHEMA = {"type":"object","properties":{"orders":{"type":"array","items":{"type":"object","properties":{"customer_name":{"type":"string"},"items":{"type":"array","items":{"type":"object","properties":{"raw_text":{"type":"string"},"product":{"type":"string"},"quantity":{"type":"number"},"unit":{"type":"string","enum":["CTN","PKT","KG","PCS"]}},"required":["raw_text","product","quantity","unit"],"additionalProperties":False}}},"required":["customer_name","items"],"additionalProperties":False}}},"required":["orders"],"additionalProperties":False}

SYSTEM = r'''You are the order-understanding brain for a cheese order parser.
ONLY identify CUSTOMER/ORDER OWNER and PRODUCT + EXPLICIT ORDER QUANTITY.
Ignore everything else.

MULTI-CUSTOMER SCREENSHOT RULES:
- One screenshot may contain 1, 5, 10, 20+ customers.
- Read the entire screenshot top-to-bottom.
- Each distinct customer/order block MUST be its own orders[] object.
- Never merge customers, even when products are identical.
- Never move a product between customer blocks.

IGNORE: WhatsApp timestamps, Forwarded, Self pick, today/tomorrow, greetings, chat commentary, phone numbers, addresses, prices, invoices/payments, WhatsApp UI, dates, OCR garbage, duplicate OCR text and customer/BP/CFS codes for product mapping.

PRODUCT RULES:
- Classic shredd/shredded => FG-02-0036.
- 50/50 shredd/shredded => Imported 50/50 2kg => FG-03-0024.
- TOP COW ONLY: white shredded = white dice; yellow shredded = yellow dice.
- For all other products Dice/Shredded/Block are different.
- Achha White Dice => FG-01-0124.
- Box/carton/CTN = CTN.
- 70/30 and 50/50 are ratios, not quantities.
- 2kg, 2.5kg, 1kg, 800gm are product attributes, not quantities.
- '70/30 shredded local 10 ctn' means 10 CTN, never 70 or 30.
- Never invent FG codes; the local product master is authoritative.
'''.strip()

NOISE = [r"^[-–—]?\s*forwarded\s*$",r"^self\s*pick\s*$",r"^(today|tomorrow|yesterday|later|thanks|thank you|ok|okay|salam|hello|hi)\s*$",r"^\d{1,2}:\d{2}(?:\s*[ap]m)?(?:\s*[a-z])?$",r"^\d{1,2}[-/]\d{1,2}[-/]\d{2,4}$",r"^[-= ]*ocr(?:\s+pass)?[-= ]*$"]
PRODUCT_HINTS = re.compile(r"cheese|cheddar|mozz|mozzarella|shred|shredded|dice|block|slice|butter|ghee|nivora|latina|verona|danish|top cow|achha|allana|50/50|70/30|pizza|silver|imported|local|classic", re.I)

def _secret(name:str)->str|None:
    try:
        import streamlit as st
        v=st.secrets.get(name)
        if v:return str(v)
    except Exception: pass
    v=os.getenv(name)
    return str(v) if v else None

def _clean_text(text:str)->str:
    out=[];seen=set()
    for raw in str(text or "").splitlines():
        line=re.sub(r"\s+"," ",raw).strip()
        if not line: continue
        if any(re.fullmatch(p,line,re.I) for p in NOISE): continue
        if re.fullmatch(r"\d{1,2}:\d{2}.*",line,re.I): continue
        k=line.casefold()
        if k in seen: continue
        seen.add(k);out.append(line)
    return "\n".join(out)

def _parse_json(value:str)->Dict[str,Any]:
    text=(value or "").strip()
    if text.startswith("```"):
        text=re.sub(r"^```(?:json)?\s*","",text,flags=re.I);text=re.sub(r"\s*```$","",text)
    data=json.loads(text)
    if not isinstance(data,dict): raise ValueError("AI did not return an object")
    return data

def _normalize(data:Dict[str,Any])->Dict[str,Any]:
    result=[]
    for order in data.get("orders",[]):
        customer=str(order.get("customer_name","")).strip()
        if not customer: continue
        items=[]
        for item in order.get("items",[]):
            product=str(item.get("product","")).strip(); raw=str(item.get("raw_text","")).strip()
            if not product or any(re.fullmatch(p,product,re.I) for p in NOISE): continue
            try: q=float(item.get("quantity"))
            except (TypeError,ValueError): q=None
            if q is None or q<=0: continue
            unit=str(item.get("unit","PKT")).upper().strip()
            if unit not in {"CTN","PKT","KG","PCS"}: unit="PKT"
            items.append({"raw_text":raw,"product":product,"quantity":q,"unit":unit})
        if items: result.append({"customer_name":customer,"items":items})
    return {"orders":result}

def _groq_client():
    key=_secret("GROQ_API_KEY")
    if not key: raise RuntimeError("GROQ_API_KEY is not configured")
    return OpenAI(api_key=key,base_url="https://api.groq.com/openai/v1")

def _openai_client():
    key=_secret("OPENAI_API_KEY")
    if not key: raise RuntimeError("OPENAI_API_KEY is not configured")
    return OpenAI(api_key=key)

def _groq_text(text:str)->Dict[str,Any]:
    clean=_clean_text(text)
    r=_groq_client().chat.completions.create(model=GROQ_MODEL,messages=[{"role":"system","content":SYSTEM},{"role":"user","content":"Parse this WhatsApp order text. Separate EVERY customer/order block and return ONLY customer + product + quantity:\n\n"+clean}],response_format={"type":"json_object"},temperature=0,max_tokens=12000)
    return _normalize(_parse_json(r.choices[0].message.content))

def _groq_image(image_bytes:bytes,mime:str)->Dict[str,Any]:
    data_url=f"data:{mime};base64,"+base64.b64encode(image_bytes).decode("ascii")
    prompt="Read the ENTIRE WhatsApp screenshot. Separate EVERY customer/order block. Extract ONLY customer name + product + explicit quantity. Ignore timestamps, Forwarded, Self pick, chat text, UI, addresses, phone numbers, prices and dates. Never merge customers."
    r=_groq_client().chat.completions.create(model=GROQ_MODEL,messages=[{"role":"system","content":SYSTEM},{"role":"user","content":[{"type":"text","text":prompt},{"type":"image_url","image_url":{"url":data_url}}]}],response_format={"type":"json_object"},temperature=0,max_tokens=12000)
    return _normalize(_parse_json(r.choices[0].message.content))

def _openai_text(text:str)->Dict[str,Any]:
    r=_openai_client().responses.create(model=OPENAI_MODEL,store=False,instructions=SYSTEM,input=_clean_text(text),text={"format":{"type":"json_schema","name":"cheese_orders","schema":SCHEMA,"strict":True}})
    return _normalize(_parse_json(r.output_text))

def _openai_image(image_bytes:bytes,mime:str)->Dict[str,Any]:
    data_url=f"data:{mime};base64,"+base64.b64encode(image_bytes).decode("ascii")
    r=_openai_client().responses.create(model=OPENAI_MODEL,store=False,instructions=SYSTEM,input=[{"role":"user","content":[{"type":"input_text","text":"Read the entire WhatsApp screenshot and return ALL customers separately. Extract only customer + product + quantity."},{"type":"input_image","image_url":data_url,"detail":"high"}]}],text={"format":{"type":"json_schema","name":"cheese_orders","schema":SCHEMA,"strict":True}})
    return _normalize(_parse_json(r.output_text))

def _ocr_image(image_bytes:bytes)->str:
    try:
        image=Image.open(io.BytesIO(image_bytes)).convert("RGB");w,h=image.size
        if max(w,h)<4000:
            scale=4000/max(w,h);image=image.resize((int(w*scale),int(h*scale)),Image.Resampling.LANCZOS)
        gray=ImageOps.grayscale(image);gray=ImageOps.autocontrast(gray);gray=gray.filter(ImageFilter.SHARPEN)
        return pytesseract.image_to_string(gray,config="--psm 6").strip()
    except Exception: return ""

def _ocr_candidates(ocr:str)->str:
    cleaned=_clean_text(ocr);kept=[]
    for line in cleaned.splitlines():
        t=line.strip()
        if not t: continue
        if re.search(r"(forwarded|self pick)",t,re.I) and not PRODUCT_HINTS.search(t): continue
        if re.fullmatch(r"\d{1,2}:\d{2}.*",t,re.I): continue
        if PRODUCT_HINTS.search(t) or re.search(r"\b(?:ctn|carton|cartons|box|boxes|pkt|packet|pcs|pc|blk|block|kg)\b",t,re.I): kept.append(t)
        elif not re.search(r"\d",t) and len(t.split())<=8: kept.append(t)
    out=[];seen=set()
    for x in kept:
        k=x.casefold()
        if k not in seen:seen.add(k);out.append(x)
    return "\n".join(out)

def parse_orders_text(text:str):
    try:return _groq_text(text)
    except (RateLimitError,APIError,APITimeoutError,APIConnectionError,RuntimeError,ValueError,json.JSONDecodeError):
        try:return _openai_text(text)
        except Exception as exc:return {"orders":[],"_fallback":True,"_fallback_text":text,"_fallback_reason":type(exc).__name__}

def parse_orders_image(image_bytes:bytes,mime:str="image/png"):
    try:
        r=_groq_image(image_bytes,mime)
        if r.get("orders"):return r
    except Exception:pass
    ocr=_ocr_image(image_bytes);candidates=_ocr_candidates(ocr)
    if candidates:
        try:
            r=_groq_text(candidates)
            if r.get("orders"):return r
        except Exception:pass
        try:
            r=_openai_text(candidates)
            if r.get("orders"):return r
        except Exception:pass
    try:
        r=_openai_image(image_bytes,mime)
        if r.get("orders"):return r
    except Exception:pass
    return {"orders":[],"_fallback":True,"_fallback_text":candidates or ocr,"_fallback_reason":"no_readable_order_detected"}

def orders_to_parser_groups(result:Dict[str,Any])->List[Dict[str,str]]:
    if result.get("_fallback") and result.get("_fallback_text"):
        return [{"customer_name":"","parser_text":str(result.get("_fallback_text"))}]
    groups=[]
    for order in result.get("orders",[]):
        name=str(order.get("customer_name","")).strip();lines=[name]
        for item in order.get("items",[]):
            q=float(item.get("quantity"));qtxt=str(int(q)) if q.is_integer() else str(q);product=item.get("product","");unit=item.get("unit","PKT")
            if product: lines.append(f"{qtxt} {unit} {product}")
        if len(lines)>1:groups.append({"customer_name":name,"parser_text":"\n".join(lines)})
    return groups

def ai_parse_order_text(text:str):
    r=parse_orders_text(text);first=r.get("orders",[{}])[0] if r.get("orders") else {}
    return {"customer_name":first.get("customer_name",""),"items":first.get("items",[]),**r}

def ai_parse_order_image(image_bytes:bytes):
    r=parse_orders_image(image_bytes);first=r.get("orders",[{}])[0] if r.get("orders") else {}
    return {"customer_name":first.get("customer_name",""),"items":first.get("items",[]),**r}

def ai_to_parser_text(result:Dict[str,Any])->str:
    if result.get("_fallback") and result.get("_fallback_text"):
        return str(result.get("_fallback_text"))
    return "\n\n".join(g["parser_text"] for g in orders_to_parser_groups(result))
