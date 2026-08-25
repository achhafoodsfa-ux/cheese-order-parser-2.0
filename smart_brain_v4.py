import base64, io, json, os, re
from typing import Any, Dict, List
from openai import OpenAI
from PIL import Image, ImageOps, ImageFilter
import pytesseract

XAI_MODEL=os.getenv('XAI_MODEL','grok-4.6')
OPENAI_MODEL=os.getenv('OPENAI_MODEL','gpt-5.6-luna')

SCHEMA={
 'type':'object','properties':{'lines':{'type':'array','items':{
  'type':'object','properties':{
   'kind':{'type':'string','enum':['CUSTOMER','PRODUCT','IGNORE']},
   'text':{'type':'string'},
   'customer':{'type':'string'},
   'product':{'type':'string'},
   'quantity':{'type':'number'},
   'unit':{'type':'string','enum':['CTN','PKT','KG','PCS','']}
  },'required':['kind','text','customer','product','quantity','unit'],'additionalProperties':False
 }}},'required':['lines'],'additionalProperties':False}

IGNORE_WORDS=re.compile(r'^(forwarded|self pick|today|tomorrow|yesterday|later|thanks|thank you|ok|okay|salam|hello|hi)$',re.I)
TIME_RE=re.compile(r'\b\d{1,2}:\d{2}\s*(?:am|pm)?\b',re.I)
PRODUCT_RE=re.compile(r'cheese|cheddar|mozz|mozzarella|shred|shredded|dice|block|slice|butter|ghee|nivora|latina|verona|danish|top cow|achha|allana|50/50|70/30|pizza|silver|imported|local|classic',re.I)

SYSTEM='''You are the visual order classifier for a WhatsApp cheese-order screenshot. Read the screenshot visually, top to bottom, preserving the visible line order.
Classify EVERY visible text line as exactly one of CUSTOMER, PRODUCT, or IGNORE.
CUSTOMER = a standalone customer/order-owner heading that introduces a block of order lines.
PRODUCT = a line that contains an explicitly ordered cheese/product and quantity.
IGNORE = timestamps, Forwarded, Self pick, greetings, comments, addresses, phone numbers, prices, dates, chat UI, random OCR garbage, repeated lines, delivery notes, and anything that is not the customer heading or an actual product order.
A line like 'Top cow dice 2 packet 10:31 PM' is PRODUCT: quantity is 2 PKT and the time is ignored.
A line like '70/30 shredded local 10 ctn' is PRODUCT: quantity is 10 CTN, never 70 or 30.
A standalone name such as 'Chudary trader' is CUSTOMER only when it is visually/structurally a new order heading; never treat a chatter line as customer.
Never merge two CUSTOMER blocks.
Never use customer names or BP/CFS codes for product mapping.
Do not invent products or quantities.'''

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
        text=re.sub(r'^```(?:json)?\s*','',text,flags=re.I);text=re.sub(r'\s*```$','',text)
    return json.loads(text)

def _clean_product(p):
    s=re.sub(r'\s+',' ',str(p or '')).strip()
    n=s.lower()
    if re.search(r'top\s*cow',n) and ('yellow' in n and ('dice' in n or 'shred' in n)): return 'Top Cow Yellow Dice'
    if re.search(r'top\s*cow',n) and ('dice' in n or 'shred' in n or 'white' in n): return 'Top Cow White Dice'
    if re.search(r'classic.*shred',n): return 'Classic Mozzarella Shredded'
    if re.search(r'50\s*/\s*50.*shred',n): return '50/50 Shredded'
    if re.search(r'achha.*white.*dice',n): return 'Achha White Dice'
    return s

def _lines_to_orders(lines):
    orders=[];current=None
    for row in lines:
        kind=str(row.get('kind','')).upper().strip(); text=re.sub(r'\s+',' ',str(row.get('text',''))).strip()
        if kind=='CUSTOMER':
            name=str(row.get('customer','') or text).strip()
            if not name or IGNORE_WORDS.fullmatch(name): continue
            if current and current['items']: orders.append(current)
            current={'customer_name':name,'items':[]}
        elif kind=='PRODUCT':
            if current is None: continue
            product=_clean_product(row.get('product',''))
            try:q=float(row.get('quantity'))
            except Exception:q=0
            unit=str(row.get('unit','') or '').upper()
            if product and q>0 and unit in {'CTN','PKT','KG','PCS'}:
                current['items'].append({'raw_text':text,'product':product,'quantity':q,'unit':unit})
    if current and current['items']: orders.append(current)
    return {'orders':orders}

def _xai_image(image_bytes):
    data='data:image/png;base64,'+base64.b64encode(image_bytes).decode('ascii')
    r=_xai().chat.completions.create(
        model=XAI_MODEL,
        messages=[{'role':'system','content':SYSTEM},{'role':'user','content':[{'type':'text','text':'Classify every visible text line in this WhatsApp screenshot. Return only JSON.'},{'type':'image_url','image_url':{'url':data}}]}],
        response_format={'type':'json_object'},temperature=0,max_tokens=12000)
    return _lines_to_orders(_json(r.choices[0].message.content).get('lines',[]))

def _ocr(image_bytes):
    try:
        im=Image.open(io.BytesIO(image_bytes)).convert('RGB'); w,h=im.size
        if max(w,h)<4200:
            s=4200/max(w,h); im=im.resize((int(w*s),int(h*s)),Image.Resampling.LANCZOS)
        g=ImageOps.autocontrast(ImageOps.grayscale(im)).filter(ImageFilter.SHARPEN)
        return '\n'.join([pytesseract.image_to_string(g,config='--psm 6'),pytesseract.image_to_string(g,config='--psm 11')])
    except Exception:return ''

def _xai_text(text):
    clean='\n'.join(x.strip() for x in str(text).splitlines() if x.strip())
    r=_xai().chat.completions.create(model=XAI_MODEL,messages=[{'role':'system','content':SYSTEM},{'role':'user','content':'Classify these extracted WhatsApp lines exactly as they appear. Return only JSON.\n\n'+clean}],response_format={'type':'json_object'},temperature=0,max_tokens=12000)
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
    r=parse_orders_text(text); first=(r.get('orders') or [{}])[0]
    return {'customer_name':first.get('customer_name',''),'items':first.get('items',[]),**r}

def ai_parse_order_image(image_bytes):
    r=parse_orders_image(image_bytes); first=(r.get('orders') or [{}])[0]
    return {'customer_name':first.get('customer_name',''),'items':first.get('items',[]),**r}

def ai_to_parser_text(result):
    if result.get('_fallback') and result.get('_fallback_text'): return str(result['_fallback_text'])
    return '\n\n'.join(g['parser_text'] for g in orders_to_parser_groups(result))
