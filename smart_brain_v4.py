import base64, io, json, os, re
from typing import Any, Dict, List
from openai import OpenAI
from PIL import Image, ImageOps, ImageFilter
import pytesseract

XAI_MODEL=os.getenv('XAI_MODEL','grok-4.6')
OPENAI_MODEL=os.getenv('OPENAI_MODEL','gpt-5.6-luna')

SCHEMA={'type':'object','properties':{'lines':{'type':'array','items':{'type':'object','properties':{'kind':{'type':'string','enum':['CUSTOMER','PRODUCT','IGNORE']},'text':{'type':'string'},'customer':{'type':'string'},'product':{'type':'string'},'quantity':{'type':'number'},'unit':{'type':'string','enum':['CTN','PKT','KG','PCS','']}},'required':['kind','text','customer','product','quantity','unit'],'additionalProperties':False}}},'required':['lines'],'additionalProperties':False}

IGNORE_WORDS=re.compile(r'^(forwarded|self pick|today|tomorrow|yesterday|later|thanks|thank you|ok|okay|salam|hello|hi)$',re.I)
TIME_RE=re.compile(r'\b\d{1,2}:\d{2}\s*(?:am|pm)?\b',re.I)
PRODUCT_RE=re.compile(r'cheese|cheddar|mozz|mozzarella|shred|shredded|dice|block|slice|butter|ghee|nivora|latina|verona|danish|top cow|achha|allana|50/50|70/30|pizza|silver|imported|local|classic',re.I)
UNIT_RE=re.compile(r'\b\d+(?:\.\d+)?\s*(ctn|carton|cartons|box|boxes|pkt|packet|packets|pcs|pc|units?)\b',re.I)

SYSTEM='''You are the visual order classifier for a WhatsApp cheese-order screenshot. Read top-to-bottom.
Classify every relevant visible line as CUSTOMER, PRODUCT, or IGNORE.
CUSTOMER = standalone order-owner heading.
PRODUCT = actual ordered product line with an explicit quantity.
IGNORE = timestamps, Forwarded, Self pick, Add in V4, greetings, comments, dates, UI, addresses, phone numbers, prices, random OCR garbage, and product-like text without an explicit quantity.
A line like "Top cow dice 2 packet 10:31 PM" is PRODUCT: 2 PKT; ignore the time.
A line like "70/30 shredded local 10 ctn" is PRODUCT: 10 CTN; 70/30 is not quantity.
A standalone name such as "Chudary trader" or "Red paper Nishter" is CUSTOMER when it introduces a following product line.
Never merge customer blocks.'''

def _secret(name):
    try:
        import streamlit as st
        v=st.secrets.get(name)
        if v:return str(v)
    except Exception: pass
    return os.getenv(name)

def _xai():
    key=_secret('XAI_API_KEY') or _secret('GROK_API_KEY')
    if not key: raise RuntimeError('XAI_API_KEY/GROK_API_KEY is not configured')
    return OpenAI(api_key=key,base_url='https://api.x.ai/v1')

def _openai():
    key=_secret('OPENAI_API_KEY')
    if not key: raise RuntimeError('OPENAI_API_KEY is not configured')
    return OpenAI(api_key=key)

def _json(text):
    text=(text or '').strip()
    if text.startswith('```'):
        text=re.sub(r'^```(?:json)?\s*','',text,flags=re.I); text=re.sub(r'\s*```$','',text)
    return json.loads(text)

def _clean_product(p):
    s=re.sub(r'\s+',' ',str(p or '')).strip(); n=s.lower()
    if 'top cow' in n and 'yellow' in n and ('dice' in n or 'shred' in n): return 'Top Cow Yellow Dice'
    if 'top cow' in n and ('dice' in n or 'shred' in n or 'white' in n): return 'Top Cow White Dice'
    if 'classic' in n and 'shred' in n: return 'Classic Mozzarella Shredded'
    if re.search(r'50\s*/\s*50.*shred',n): return '50/50 Shredded'
    if 'achha' in n and 'white' in n and 'dice' in n: return 'Achha White Dice'
    return s

def _looks_customer_candidate(text):
    t=re.sub(r'\s+',' ',str(text or '')).strip()
    if not t or IGNORE_WORDS.fullmatch(t) or TIME_RE.search(t): return False
    if re.search(r'\d',t) or UNIT_RE.search(t) or PRODUCT_RE.search(t): return False
    if len(t.split())>8: return False
    return True

def _looks_product_row(text,row):
    t=str(text or '').strip()
    unit=row.get('unit','') if isinstance(row,dict) else ''
    qty=row.get('quantity',0) if isinstance(row,dict) else 0
    has_qty=bool(UNIT_RE.search(t)) or (str(unit).upper() in {'CTN','PKT','KG','PCS'} and float(qty or 0)>0)
    product=str(row.get('product','')).strip() if isinstance(row,dict) else ''
    return has_qty and bool(product or PRODUCT_RE.search(t))

def _repair_lines(lines):
    raw=[]
    for r in lines or []:
        if not isinstance(r,dict): continue
        text=re.sub(r'\s+',' ',str(r.get('text',''))).strip()
        if not text: continue
        if IGNORE_WORDS.fullmatch(text) or TIME_RE.fullmatch(text):
            r['kind']='IGNORE'; continue
        # Remove WhatsApp time suffix from source text, never from quantity.
        clean_time=TIME_RE.sub(' ',text); clean_time=re.sub(r'\s+',' ',clean_time).strip()
        r['text']=clean_time
        if _looks_product_row(clean_time,r): r['kind']='PRODUCT'
        elif r.get('kind')!='PRODUCT' and _looks_customer_candidate(clean_time): r['kind']='CANDIDATE_CUSTOMER'
        else: r['kind']='IGNORE'
        raw.append(r)
    # Deterministic customer repair: any candidate followed by a PRODUCT is a customer heading.
    fixed=[]
    for i,r in enumerate(raw):
        if r['kind']=='CANDIDATE_CUSTOMER':
            nxt=next((x for x in raw[i+1:] if x['kind']!='IGNORE'),None)
            if nxt and nxt['kind']=='PRODUCT':
                r['kind']='CUSTOMER'; r['customer']=r.get('customer') or r['text']
            else:
                r['kind']='IGNORE'
        fixed.append(r)
    # First useful line can be a customer heading even if model called it IGNORE.
    for i,r in enumerate(fixed):
        if r['kind'] in ('CUSTOMER','PRODUCT'): break
        if _looks_customer_candidate(r.get('text','')):
            nxt=next((x for x in fixed[i+1:] if x['kind']!='IGNORE'),None)
            if nxt and nxt['kind']=='PRODUCT':
                r['kind']='CUSTOMER'; r['customer']=r['text']; break
    return fixed

def _lines_to_orders(lines):
    lines=_repair_lines(lines)
    orders=[]; current=None
    seen_items=set()
    for row in lines:
        kind=row.get('kind'); text=str(row.get('text','')).strip()
        if kind=='CUSTOMER':
            name=str(row.get('customer') or text).strip()
            if not name or IGNORE_WORDS.fullmatch(name): continue
            if current and current['items']: orders.append(current)
            current={'customer_name':name,'items':[]}; seen_items=set(); continue
        if kind!='PRODUCT' or current is None: continue
        product=_clean_product(row.get('product',''))
        try:q=float(row.get('quantity'))
        except Exception:q=0
        unit=str(row.get('unit','') or '').upper()
        # Never accept a quantity unless an explicit unit exists. Ratios/timestamps therefore cannot become quantities.
        if not product or q<=0 or unit not in {'CTN','PKT','KG','PCS'}: continue
        key=(product.casefold(),q,unit)
        if key in seen_items: continue
        seen_items.add(key)
        current['items'].append({'raw_text':text,'product':product,'quantity':q,'unit':unit})
    if current and current['items']: orders.append(current)
    return {'orders':orders}

def _xai_image(image_bytes):
    data='data:image/png;base64,'+base64.b64encode(image_bytes).decode('ascii')
    r=_xai().chat.completions.create(model=XAI_MODEL,messages=[{'role':'system','content':SYSTEM},{'role':'user','content':[{'type':'text','text':'Visually inspect every WhatsApp message bubble. Return one JSON line record for each relevant visible line. Preserve top-to-bottom order.'},{'type':'image_url','image_url':{'url':data}}]}],response_format={'type':'json_object'},temperature=0,max_tokens=12000)
    return _lines_to_orders(_json(r.choices[0].message.content).get('lines',[]))

def _ocr(image_bytes):
    try:
        im=Image.open(io.BytesIO(image_bytes)).convert('RGB'); w,h=im.size
        if max(w,h)<4200:
            s=4200/max(w,h); im=im.resize((int(w*s),int(h*s)),Image.Resampling.LANCZOS)
        g=ImageOps.autocontrast(ImageOps.grayscale(im)).filter(ImageFilter.SHARPEN)
        return pytesseract.image_to_string(g,config='--psm 6')
    except Exception:return ''

def _xai_text(text):
    r=_xai().chat.completions.create(model=XAI_MODEL,messages=[{'role':'system','content':SYSTEM},{'role':'user','content':'Classify these extracted WhatsApp lines. Return one record per line. Preserve order.\n\n'+str(text)}],response_format={'type':'json_object'},temperature=0,max_tokens=12000)
    return _lines_to_orders(_json(r.choices[0].message.content).get('lines',[]))

def parse_orders_image(image_bytes,mime='image/png'):
    try:
        r=_xai_image(image_bytes)
        if r.get('orders'): return r
    except Exception: pass
    ocr=_ocr(image_bytes)
    if ocr:
        try:
            r=_xai_text(ocr)
            if r.get('orders'): return r
        except Exception: pass
    return {'orders':[],'_fallback':True,'_fallback_text':ocr,'_fallback_reason':'no_readable_order_detected'}

def parse_orders_text(text):
    try:return _xai_text(text)
    except Exception:
        try:
            r=_openai().responses.create(model=OPENAI_MODEL,store=False,instructions=SYSTEM,input=str(text),text={'format':{'type':'json_schema','name':'order_lines','schema':SCHEMA,'strict':True}})
            return _lines_to_orders(_json(r.output_text).get('lines',[]))
        except Exception as e:return {'orders':[],'_fallback':True,'_fallback_text':text,'_fallback_reason':type(e).__name__}

def orders_to_parser_groups(result):
    if result.get('_fallback') and result.get('_fallback_text'): return [{'customer_name':'','parser_text':str(result['_fallback_text'])}]
    groups=[]
    for o in result.get('orders',[]):
        lines=[o['customer_name']]
        for it in o.get('items',[]):
            q=float(it['quantity']); qt=str(int(q)) if q.is_integer() else str(q); lines.append(f"{qt} {it['unit']} {it['product']}")
        if len(lines)>1: groups.append({'customer_name':o['customer_name'],'parser_text':'\n'.join(lines)})
    return groups

def ai_parse_order_text(text):
    r=parse_orders_text(text); first=(r.get('orders') or [{}])[0]; return {'customer_name':first.get('customer_name',''),'items':first.get('items',[]),**r}

def ai_parse_order_image(image_bytes):
    r=parse_orders_image(image_bytes); first=(r.get('orders') or [{}])[0]; return {'customer_name':first.get('customer_name',''),'items':first.get('items',[]),**r}

def ai_to_parser_text(result):
    if result.get('_fallback') and result.get('_fallback_text'): return str(result['_fallback_text'])
    return '\n\n'.join(g['parser_text'] for g in orders_to_parser_groups(result))
