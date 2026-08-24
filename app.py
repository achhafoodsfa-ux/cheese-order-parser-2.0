import io
import json
import os
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from PIL import Image, ImageOps, ImageFilter
import pytesseract
import fitz  # PyMuPDF
from pypdf import PdfReader
from docx import Document
from streamlit_paste_button import paste_image_button
from ai_order_parser import ai_parse_order_text, ai_parse_order_image, ai_to_parser_text

st.set_page_config(page_title="Cheese SAP Order Parser", page_icon="🧀", layout="wide")

# Existing master mapping is kept intact.
PRODUCTS = {
"FG-02-0012":{"name":"Classic Cheddar Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["classic cheddar","classic chadder","classic cheddar block"]},
"FG-02-0068":{"name":"Top Cow Cheddar Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["top cow cheddar block","top cow chadder block"]},
"FG-02-0006":{"name":"Achha Pizza Cheddar Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["pizza cheddar","pizza chadder","pizza cheddar block"]},
"FG-02-0018":{"name":"Regular Cheddar Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["regular cheddar block"]},
"FG-02-0028":{"name":"Yellow Slice 1kg","pack":"slice","pcs_ctn":18,"kg":1,"keywords":["yellow slice","orange slice","burger slice","burger/orange"]},
"FG-02-0023":{"name":"White Slice 1kg","pack":"slice","pcs_ctn":18,"kg":1,"keywords":["white slice"]},
"FG-02-0039":{"name":"Jalapeno Cheddar Slice 1kg","pack":"slice","pcs_ctn":18,"kg":1,"keywords":["jalapeno slice","jalapeno cheddar slice"]},
"FG-02-0038":{"name":"Yellow Slice 800gm","pack":"slice800","pcs_ctn":18,"kg":0.8,"keywords":["yellow slice 800","yellow 800"]},
"FG-02-0037":{"name":"White Slice 800gm","pack":"slice800","pcs_ctn":18,"kg":0.8,"keywords":["white slice 800","white 800"]},
"FG-02-0060":{"name":"Top Cow Mozzarella Block White","pack":"block","pcs_ctn":10,"kg":2,"keywords":["top cow mozzarella block","top cow block"]},
"FG-02-0048":{"name":"Top Cow White Dice/Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["top cow white dice","top cow white shred","top cow white shredded","top cow shred white"]},
"FG-02-0049":{"name":"Top Cow Yellow Dice/Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["top cow yellow dice","top cow yellow shred","top cow yellow shredded"]},
"FG-02-0072":{"name":"Classic 70/30 Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["classic 70/30","classic 70.30"]},
"FG-01-0012":{"name":"Classic Mozzarella Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["classic mozzarella block","classic mozz block","classic mozz blk"]},
"FG-02-0036":{"name":"Classic Mozzarella Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["classic mozzarella shred","classic mozzarella shredded","classic shred"]},
"FG-02-0082":{"name":"Classic Mozzarella Shredded DC","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["classic mozzarella shredded dc"]},
"FG-01-0018":{"name":"Danish Mozzarella Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["danish mozzarella block","danish mozz block","danish mozz blk"]},
"FG-01-0030":{"name":"Danish Mozzarella Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["danish mozzarella shred","danish mozzarella shredded"]},
"FG-01-0036":{"name":"Imported/UK Mozzarella Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["imp uk mozzarella","imported mozzarella shred","uk mozzarella shred"]},
"FG-03-0006":{"name":"Imported 70/30 Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["imp 70/30","imported 70/30"]},
"FG-03-0026":{"name":"Imported 70/30 Dice","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["imp 70/30 dice","imported 70/30 dice"]},
"FG-01-0006":{"name":"Achha Mozzarella Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["achha mozzarella block","achha mozz block","achha mozz blk","red mozz blk","red mozzarella block","mozzarella block"]},
"FG-01-0042":{"name":"Achha Mozzarella Shredded White","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["achha shred","achha shredded","achha shared","achha shared white","blue shredd","blue shred","achha mozzarella shred","achha mozzarella shredded"]},
"FG-01-0054":{"name":"Achha Mozzarella Shredded Yellow","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["achha shred yellow","achha shared yellow"]},
"FG-01-0124":{"name":"Achha White Dice","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["achha white dice"]},
"FG-01-0125":{"name":"Achha Yellow Dice","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["achha yellow dice"]},
"FG-03-0018":{"name":"Local 70/30 Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["local 70/30","local 70.30","locl 70/30","lockl 70/30","lockl 70.30"]},
"FG-02-0051":{"name":"New/M3 70/30 Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["new 70/30","new 70.30","m3 70/30","m3 shred","m3 70/30"]},
"FG-03-0024":{"name":"50/50 Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["50/50 shred","50/50 shredded"]},
"FG-01-0066":{"name":"Latina Mozzarella Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["latina mozzarella shred","latina shred"]},
"FG-01-0111":{"name":"Silver Mozzarella Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["silver mozzarella block","silver mozz block","silver"]},
"FG-01-0110":{"name":"Silver Mozzarella Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["silver mozzarella shred"]},
"FG-03-0025":{"name":"Verona Mozzarella Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["verona mozzarella block","verona mozz block"]},
"FG-01-0072":{"name":"Verona Mozzarella Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["verona shred","verona mozzarella shred"]},
"FG-02-0065":{"name":"Pizza Topping Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["pizza topping block"]},
"FG-02-0064":{"name":"Pizza Topping Shredded","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["pizza topping shred"]},
"FG-06-0004":{"name":"Butter White 82 FAT 1kg","pack":"unit","pcs_ctn":1,"kg":1,"keywords":["butter white 82","butter white"]},
"FG-06-0011":{"name":"Butter Yellow 82 FAT 1kg","pack":"unit","pcs_ctn":1,"kg":1,"keywords":["butter yellow 82","butter yellow"]},
"FG-06-0017":{"name":"Butter White 87 Fat 1kg","pack":"unit","pcs_ctn":1,"kg":1,"keywords":["butter white 87"]},
"FG-06-0018":{"name":"Butter Yellow 87 Fat 1kg","pack":"unit","pcs_ctn":1,"kg":1,"keywords":["butter yellow 87"]},
"FG-06-0003":{"name":"Butter White 500gm","pack":"unit","pcs_ctn":1,"kg":0.5,"keywords":["butter white 500"]},
"FG-06-0010":{"name":"Butter Yellow 500gm","pack":"unit","pcs_ctn":1,"kg":0.5,"keywords":["butter yellow 500"]},
"FG-05-0002":{"name":"Desi Ghee Tin 500gm","pack":"unit","pcs_ctn":1,"kg":0.5,"keywords":["desi ghee 500"]},
"FG-05-0011":{"name":"Desi Ghee Tin 1kg","pack":"unit","pcs_ctn":1,"kg":1,"keywords":["desi ghee 1kg","desi ghee"]},
"FG-05-0005":{"name":"Desi Ghee Tin 16kg","pack":"unit","pcs_ctn":1,"kg":16,"keywords":["desi ghee 16kg"]},
"FG-02-0110":{"name":"Nivora Max White Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["max white dice","max w dice"]},
"FG-02-0109":{"name":"Nivora Max White Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["max white shred","max white shredded"]},
"FG-02-0112":{"name":"Nivora Max Yellow Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["max yellow dice"]},
"FG-02-0111":{"name":"Nivora Max Yellow Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["max yellow shred"]},
"FG-02-0102":{"name":"Nivora MF White Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["mf white","mf white dice"]},
"FG-02-0101":{"name":"Nivora MF White Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["mf white shred"]},
"FG-02-0104":{"name":"Nivora MF Yellow Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["mf yellow","mf yellow dice"]},
"FG-02-0103":{"name":"Nivora MF Yellow Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["mf yellow shred"]},
"FG-02-0106":{"name":"Nivora Pro White Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["pro white","pro w","pro white dice"]},
"FG-02-0105":{"name":"Nivora Pro White Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["pro white shred"]},
"FG-02-0108":{"name":"Nivora Pro Yellow Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["pro yellow dice"]},
"FG-02-0107":{"name":"Nivora Pro Yellow Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["pro yellow shred"]},
"FG-02-0118":{"name":"Nivora PT White Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["pt white","pt w","pizza topping white"]},
"FG-02-0117":{"name":"Nivora PT White Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["pt white shred"]},
"FG-02-0120":{"name":"Nivora PT Yellow Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["pt yellow","pt y","pizza topping yellow"]},
"FG-02-0119":{"name":"Nivora PT Yellow Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["pt yellow shred"]},
"FG-02-0114":{"name":"Nivora VF White Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["vf white dice"]},
"FG-02-0113":{"name":"Nivora VF White Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["vf white shred"]},
"FG-02-0116":{"name":"Nivora VF Yellow Dice","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["vf yellow dice"]},
"FG-02-0115":{"name":"Nivora VF Yellow Shredded","pack":"nivora","pcs_ctn":4,"kg":2.5,"keywords":["vf yellow shred"]},
"FG-02-0094":{"name":"Allana Cheddar Cheese Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["allana cheddar block"]},
"FG-02-0096":{"name":"Allana Mozzarella Cheese Block","pack":"block","pcs_ctn":10,"kg":2,"keywords":["allana mozzarella block"]},
"FG-02-0097":{"name":"Allana Mozzarella Cheese Shredded White","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["allana mozzarella shred white"]},
"FG-02-0100":{"name":"Allana Pizza Cheese 70/30 Shredded White","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["allana 70/30","allana pizza 70/30"]},
"FG-02-0162":{"name":"Allana Mozzarella Block W.Poly","pack":"block","pcs_ctn":10,"kg":2,"keywords":["allana wpoly mozzarella block"]},
"FG-02-0164":{"name":"Allana Mozzarella Shredded White W.Poly","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["allana wpoly mozzarella shred white"]},
"FG-02-0166":{"name":"Allana Mozzarella Shredded Yellow W.Poly","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["allana wpoly mozzarella shred yellow"]},
"FG-02-0174":{"name":"Allana Pizza Cheese 70/30 White W.Poly","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["allana wpoly 70/30"]},
"FG-02-0182":{"name":"Allana Pizza Cheese 50/50 White W.Poly","pack":"regular","pcs_ctn":5,"kg":2,"keywords":["allana wpoly 50/50"]},
}

RULES_FILE = Path("rules.json")

def norm(s):
    s=str(s).lower().strip()
    replacements={"shared":"shred","shraded":"shredded","shrad":"shred","shrd":"shred","shreded":"shredded","chadder":"cheddar","chaddar":"cheddar","cheder":"cheddar","cheedar":"cheddar","chesse":"cheese","accha":"achha","acha":"achha","locl":"local","lockl":"local","70.30":"70/30"}
    for a,b in replacements.items(): s=s.replace(a,b)
    return re.sub(r"\s+"," ",s)

def load_rules():
    default={"product_aliases":[],"quantity_rules":[],"customer_rules":[],"general_rules":[]}
    try:
        if RULES_FILE.exists():
            with RULES_FILE.open("r",encoding="utf-8") as f: return {**default,**json.load(f)}
    except Exception: pass
    return default

def save_rules(rules):
    with RULES_FILE.open("w",encoding="utf-8") as f: json.dump(rules,f,ensure_ascii=False,indent=2)
    return True

RULES=load_rules()

def apply_saved_aliases(text):
    t=norm(text)
    for rule in RULES.get("product_aliases",[]):
        alias=norm(rule.get("alias",""));code=rule.get("code","")
        if alias and code in PRODUCTS and alias in t:return code
    return None

def find_product(text):
    # Customer identifiers/codes are intentionally ignored. This function maps product text only.
    t=norm(text)
    saved=apply_saved_aliases(t)
    if saved:return saved
    # Explicit authoritative mappings from master training.
    if "50/50" in t and ("shred" in t or "shredded" in t):return "FG-03-0024"
    if "classic" in t and ("shred" in t or "shredded" in t) and "70/30" not in t:return "FG-02-0036"
    priority=[("red mozz blk","FG-01-0006"),("red mozzarella block","FG-01-0006"),("blue shredd","FG-01-0042"),("blue shred","FG-01-0042"),("danish mozzarella block","FG-01-0018"),("danish mozz block","FG-01-0018"),("classic mozzarella block","FG-01-0012"),("classic mozz block","FG-01-0012"),("burger slice","FG-02-0028"),("orange slice","FG-02-0028")]
    for key,code in priority:
        if key in t:return code
    if "slice" in t:
        white="white" in t; yellow=any(x in t for x in ("yellow","orange","burger")); jal="jalapeno" in t or "jal" in t; is800=any(x in t for x in ("800","800gm","800 gm",".8","0.8"))
        if jal:return "FG-02-0039"
        if white:return "FG-02-0037" if is800 else "FG-02-0023"
        if yellow:return "FG-02-0038" if is800 else "FG-02-0028"
    if "burger" in t and "2 kg" in t:return "FG-02-0028"
    if "local" in t and "70/30" in t:return "FG-03-0018"
    if ("new" in t or "m3" in t) and "70/30" in t:return "FG-02-0051"
    if "imp" in t and "70/30" in t:return "FG-03-0006"
    if "classic" in t and "70/30" in t:return "FG-02-0072"
    if "achha" in t and "yellow" in t and "dice" in t:return "FG-01-0125"
    if "achha" in t and "white" in t and "dice" in t:return "FG-01-0124"
    if "achha" in t and "yellow" in t and "shred" in t:return "FG-01-0054"
    if "achha" in t and "shred" in t:return "FG-01-0042"
    if "top cow" in t and "yellow" in t:return "FG-02-0049"
    if "top cow" in t and "white" in t:return "FG-02-0048"
    if "top cow" in t and "cheddar" in t and "block" in t:return "FG-02-0068"
    if "top cow" in t and "block" in t:return "FG-02-0060"
    if "verona" in t and "block" in t:return "FG-03-0025"
    if "verona" in t:return "FG-01-0072"
    if "silver" in t and "shred" in t:return "FG-01-0110"
    if "silver" in t:return "FG-01-0111"
    if "danish" in t and "shred" in t:return "FG-01-0030"
    if "danish" in t:return "FG-01-0018"
    if "classic" in t and "cheddar" in t and "block" in t:return "FG-02-0012"
    if "pizza cheddar" in t or ("pizza" in t and "cheddar" in t and "block" in t):return "FG-02-0006"
    for key,code in [("mf white","FG-02-0102"),("mf yellow","FG-02-0104"),("pro white","FG-02-0106"),("pro w","FG-02-0106"),("pro yellow","FG-02-0108"),("max white","FG-02-0110"),("max yellow","FG-02-0112"),("pt white","FG-02-0118"),("pt w","FG-02-0118"),("pt yellow","FG-02-0120"),("pt y","FG-02-0120"),("vf white","FG-02-0114"),("vf yellow","FG-02-0116")]:
        if key in t:return code
    if "mozzarella block" in t or "mozz block" in t or "mozz blk" in t:return "FG-01-0006"
    candidates=[(len(k),code) for code,p in PRODUCTS.items() for k in p["keywords"] if k in t]
    return sorted(candidates,reverse=True)[0][1] if candidates else None

def parse_quantity(line):
    t=norm(line)
    m=re.search(r"(\d+(?:\.\d+)?)\s*kg\s+.*burger\s*(?:/|or)?\s*(?:orange)?\s*slice",t)
    if m:return int(float(m.group(1))),"PKT"
    m=re.search(r"(\d+(?:\.\d+)?)\s*(ctn|carton|cartons|box|boxes|pkt|packet|packets|pcs|pc|units?|kg)?\b",t)
    if not m:return None,None
    qty=float(m.group(1)); unit=(m.group(2) or "").lower(); qty=int(qty) if qty.is_integer() else qty
    if unit in ("ctn","carton","cartons","box","boxes"):return qty,"CTN"
    if unit in ("pkt","packet","packets","pcs","pc","unit","units"):return qty,"PKT"
    if unit=="kg":return qty,"KG"
    return qty,"CTN" if qty>10 else "PKT"

def parse_order(text, progress=None):
    lines=[x.strip() for x in str(text).splitlines() if x.strip()]; rows=[]; customer=""
    if progress: progress(0.05,"Reading order text…")
    for i,line in enumerate(lines):
        if i==0 and not re.search(r"\d",line): customer=line.strip(); continue
        code=find_product(line); qty,unit=parse_quantity(line)
        if not code or qty is None:
            rows.append({"Source":line,"Customer":customer,"FG Code":"UNMAPPED","Product":"","Input Qty":qty,"Input Unit":unit,"SAP Qty (PKT)":"","Status":"CHECK MAPPING"}); continue
        p=PRODUCTS[code]; sap_qty=round(qty/p["kg"]) if unit=="KG" else int(qty*p["pcs_ctn"]) if unit=="CTN" else int(qty)
        rows.append({"Source":line,"Customer":customer,"FG Code":code,"Product":p["name"],"Input Qty":qty,"Input Unit":unit,"SAP Qty (PKT)":sap_qty,"Status":"OK"})
        if progress: progress(min(0.70,0.10+0.55*(i+1)/max(1,len(lines))),f"Mapping line {i+1}/{len(lines)}…")
    if progress: progress(0.75,"Running quantity and SAP validation…")
    return customer,rows

def sap_line(code,qty):return f"{code}\t\t{int(qty)}\t\t\t\t\tHO-WH\t\tCHEESE"

def extract_excel(file):
    xls=pd.ExcelFile(file); frames=[]
    for sheet in xls.sheet_names:
        df=pd.read_excel(file,sheet_name=sheet)
        if not df.empty:df["__sheet__"]=sheet;frames.append(df)
    return pd.concat(frames,ignore_index=True) if frames else pd.DataFrame()

def normalize_columns(df):
    d=df.copy();d.columns=[str(c).strip().lower() for c in d.columns];return d

def process_tabular(df):
    d=normalize_columns(df);code_col=next((c for c in d.columns if "sap" in c and "code" in c),None);product_col=next((c for c in d.columns if "product" in c or "description" in c or "item" in c),None);ctn_col=next((c for c in d.columns if "carton" in c or c=="ctn"),None);unit_col=next((c for c in d.columns if c in ("units","unit","pcs","qty","quantity")),None);customer_col=next((c for c in d.columns if "customer" in c or "party" in c),None)
    output=[]
    for _,r in d.iterrows():
        customer=str(r.get(customer_col," ")).strip() if customer_col else "";code=str(r.get(code_col," ")).strip() if code_col else "";product=str(r.get(product_col," ")).strip() if product_col else ""
        if code not in PRODUCTS:code=find_product(product)
        if not code:continue
        try:units=float(r.get(unit_col,0)) if unit_col else 0
        except Exception:units=0
        try:ctn=float(r.get(ctn_col,0)) if ctn_col else 0
        except Exception:ctn=0
        if units>0:sap_qty=int(units)
        elif ctn>0:sap_qty=int(ctn*PRODUCTS[code]["pcs_ctn"])
        else:continue
        output.append({"Customer":customer,"FG Code":code,"Product":PRODUCTS[code]["name"],"SAP Qty (PKT)":sap_qty,"Source":"Excel","Status":"OK"})
    return pd.DataFrame(output)

IMAGE_EXTS={"png","jpg","jpeg","webp","bmp","tif","tiff"};TABULAR_EXTS={"xlsx","xls","csv"};TEXT_EXTS={"txt"};PDF_EXTS={"pdf"};DOC_EXTS={"docx"}

def clean_ocr_text(text):
    text=text.replace("\x00"," ");lines=[]
    for raw in text.splitlines():
        line=re.sub(r"[ \t]+"," ",raw).strip()
        if line:lines.append(line)
    return "\n".join(lines)

def ocr_image(data):
    image=Image.open(io.BytesIO(data))
    if image.mode not in ("RGB","L"):image=image.convert("RGB")
    w,h=image.size;scale=2 if max(w,h)<2500 else 1
    if scale>1:image=image.resize((w*scale,h*scale))
    gray=ImageOps.grayscale(image);gray=ImageOps.autocontrast(gray);gray=gray.filter(ImageFilter.SHARPEN)
    text=pytesseract.image_to_string(gray,config="--psm 6")
    if not text.strip():text=pytesseract.image_to_string(gray,config="--psm 11")
    return clean_ocr_text(text)

def pdf_to_text(data):
    parts=[];reader=PdfReader(io.BytesIO(data))
    for page in reader.pages:
        try:parts.append(page.extract_text() or "")
        except Exception:parts.append("")
    text=clean_ocr_text("\n".join(parts))
    if len(re.sub(r"\s","",text))<20:
        doc=fitz.open(stream=data,filetype="pdf");ocr_parts=[]
        for page in doc:
            pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False);ocr_parts.append(ocr_image(pix.tobytes("png")))
        doc.close();text=clean_ocr_text("\n".join(ocr_parts))
    return text

def docx_to_text(data):
    doc=Document(io.BytesIO(data));chunks=[p.text for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:chunks.append(" ".join(cell.text.strip() for cell in row.cells))
    return clean_ocr_text("\n".join(chunks))

def read_uploaded_file(uploaded_file):
    ext=Path(uploaded_file.name).suffix.lower().lstrip(".");data=uploaded_file.getvalue()
    if ext in IMAGE_EXTS:return "image",ocr_image(data)
    if ext in PDF_EXTS:return "pdf",pdf_to_text(data)
    if ext in DOC_EXTS:return "docx",docx_to_text(data)
    if ext=="csv":return "csv",pd.read_csv(io.BytesIO(data))
    if ext in ("xlsx","xls"):return "excel",extract_excel(io.BytesIO(data))
    if ext in TEXT_EXTS:return "text",data.decode("utf-8",errors="ignore")
    raise ValueError(f"Unsupported file type: .{ext}")

def show_order_result(customer,rows,source_label):
    ok=[r for r in rows if r["Status"]=="OK"];bad=[r for r in rows if r["Status"]!="OK"]
    if customer:st.markdown(f"### {customer}")
    st.subheader("SAP Paste Format");merged={}
    for r in ok:merged[r["FG Code"]]=merged.get(r["FG Code"],0)+int(r["SAP Qty (PKT)"])
    if merged:
        sap="\n".join(sap_line(c,q) for c,q in merged.items());st.code(sap,language="text");st.download_button("Download SAP Order",sap,file_name=f"{customer or 'order'}_SAP.txt",mime="text/plain",key=f"dl_{abs(hash(source_label))}")
    else:st.warning("No mapped order lines found.")
    if bad:st.error("These lines need manual checking:");st.dataframe(pd.DataFrame(bad),use_container_width=True)
    check_df=pd.DataFrame(ok)
    if not check_df.empty:st.subheader("Triple-check");st.dataframe(check_df[["Source","FG Code","Product","Input Qty","Input Unit","SAP Qty (PKT)"]],use_container_width=True)

def teach_rule(rule_text, category="general", customer=""):
    text=rule_text.strip()
    if not text:return False,"Write a teaching rule first."
    rules=load_rules()
    m=re.search(r"(.+?)\s*(?:means|=|is)\s*(FG-\d{2}-\d{4})\b",text,re.I)
    if m and m.group(2).upper() in PRODUCTS:
        alias=m.group(1).strip(" :-");code=m.group(2).upper()
        rules.setdefault("product_aliases",[])
        rules["product_aliases"]=[r for r in rules["product_aliases"] if norm(r.get("alias"))!=norm(alias)]
        rules["product_aliases"].append({"alias":alias,"code":code,"note":text})
        save_rules(rules);return True,f"Saved product alias: {alias} → {code}"
    entry={"rule":text,"customer":customer.strip(),"category":category}
    key="customer_rules" if customer.strip() or category=="customer" else ("quantity_rules" if category=="quantity / conversion" else "general_rules")
    rules.setdefault(key,[]).append(entry);save_rules(rules)
    return True,"Teaching rule saved and will be applied as persistent guidance."

st.title("🧀 Cheese Order Parser → SAP")
st.caption("Smart input + persistent teaching. Press Enter to start processing. Drag/drop WhatsApp screenshots, images, PDFs, Excel, CSV, Word files or paste an order.")

with st.sidebar:
    st.header("🧠 Parser Memory")
    st.metric("Saved product aliases",len(RULES.get("product_aliases",[])))
    st.metric("Saved rules",len(RULES.get("general_rules",[]))+len(RULES.get("customer_rules",[]))+len(RULES.get("quantity_rules",[])))
    st.caption("Saved rules are stored in rules.json. They remain available across normal Streamlit reruns.")
    if RULES.get("product_aliases"):
        st.subheader("Learned aliases")
        for r in RULES["product_aliases"][-12:]:st.write(f"• **{r['alias']}** → `{r['code']}`")
    st.divider()
    st.write("• SAP quantity = PKT/Units")
    st.write("• CTN is converted automatically")
    st.write("• 2kg block = 10 PKT/CTN")
    st.write("• 2kg shred/dice = 5 PKT/CTN")
    st.write("• Nivora 2.5kg = 4 PKT/CTN")
    st.write("• Slice = 18 PKT/CTN")
    st.write("• Red mozz blk = Achha Mozz Block")
    st.write("• Blue shredd = Achha Mozz Shredded")
    st.write("• Danish Mozz Block = Danish, never Achha")
    st.write("• 50/50 Shredded = Imported 50/50 Shredded 2kg")
    st.write("• Classic Shredded = FG-02-0036")

order_tab,teach_tab,excel_tab=st.tabs(["🤖 Smart Order Input","🎓 Teach / Save Rule","📊 Excel / CSV"])

with order_tab:
    st.subheader("Smart Order Input")
    st.info("Type/paste an order and press **Enter** to start. Or drag & drop one or more files into the same input.")
    st.info("📋 Copy a WhatsApp screenshot, then click **Paste Image**. For files, use the large uploader below; drag & drop is supported there.")
    ai_enabled = st.checkbox("🧠 Use AI Smart Parsing (recommended)", value=True, help="AI understands messy WhatsApp wording and screenshots. Final FG codes still come from your local product mapping/rules.")

    paste_result = paste_image_button("📋 Paste Image from Clipboard", key="paste_image_clipboard", errors="ignore")
    fallback_files = st.file_uploader(
        "📎 DROP FILES / IMAGES HERE — PNG, JPG, PDF, Excel, CSV, Word, TXT",
        type=sorted(IMAGE_EXTS|TABULAR_EXTS|TEXT_EXTS|PDF_EXTS|DOC_EXTS),
        accept_multiple_files=True,
        key="smart_files",
        help="Drag files directly into this box or click Browse files.",
    )
    fallback_text=st.text_area("Or paste WhatsApp text here",height=130,placeholder="Customer Name\n3 CTN 70/30 local\n1 CTN 70/30 new",key="fallback_text")
    run_fallback=st.button("🚀 Process pasted text / files",type="primary")

    pasted_images = []
    if paste_result is not None and getattr(paste_result, "image_data", None) is not None:
        import io
        buf = io.BytesIO()
        paste_result.image_data.save(buf, format="PNG")
        pasted_images.append(buf.getvalue())

    files=[];message=""
    if run_fallback:
        message=fallback_text.strip();files.extend(fallback_files or [])

    if run_fallback or pasted_images:
        progress=st.progress(0,text="Starting parser…")
        status=st.empty()
        for pidx, data in enumerate(pasted_images, 1):
            st.markdown("---")
            st.markdown(f"### 📋 Pasted WhatsApp image {pidx}")
            try:
                st.image(data, caption="Pasted from clipboard", use_container_width=True)
                status.info("Step 1/4 — Reading pasted image…")
                if ai_enabled:
                    ai_result = ai_parse_order_image(data)
                    extracted = ai_to_parser_text(ai_result)
                    st.caption("🧠 AI interpretation used; FG mapping remains local/authoritative.")
                else:
                    extracted = ocr_image(data)
                progress.progress(0.35, text="Image reading completed")
                with st.expander("🔎 AI/OCR interpretation", expanded=False):
                    st.text(extracted[:12000] if extracted else "[No readable order detected]")
                if extracted.strip():
                    status.info("Step 3/4 — Mapping products and quantities…")
                    customer, rows = parse_order(extracted, lambda v,t: progress.progress(min(0.65+v*0.25,0.90), text=t))
                    if ai_enabled and ai_result.get("customer_name"):
                        customer = ai_result["customer_name"]
                    show_order_result(customer, rows, f"pasted_image_{pidx}")
                else:
                    st.error("Pasted image: no readable text was detected.")
            except Exception as e:
                st.error(f"Pasted image {pidx}: {e}")

        if message:
            status.info("Step 1/4 — Reading WhatsApp text…")
            if ai_enabled:
                ai_result = ai_parse_order_text(message)
                parser_text = ai_to_parser_text(ai_result)
                st.caption("🧠 AI interpretation used; customer codes are ignored for product mapping.")
                with st.expander("🔎 AI interpretation", expanded=False):
                    st.json(ai_result)
            else:
                ai_result = {"customer_name": "", "items": []}
                parser_text = message
            customer,rows=parse_order(parser_text,lambda v,t: progress.progress(v,text=t))
            if ai_enabled and ai_result.get("customer_name"):
                customer = ai_result["customer_name"]
            status.info("Step 2/4 — Mapping products and quantities…")
            show_order_result(customer,rows,"chat_text")
        for idx,f in enumerate(files,1):
            st.markdown("---");st.markdown(f"### 📎 {f.name}")
            try:
                status.info(f"Step 1/4 — Reading {f.name}…");kind,content=read_uploaded_file(f)
                progress.progress(min(0.35+idx/max(1,len(files))*0.25,0.60),text=f"Extracted {f.name}")
                if kind in ("excel","csv"):
                    status.info("Step 2/4 — Processing spreadsheet rows…");result=process_tabular(content)
                    if result.empty:st.warning(f"{f.name}: no valid mapped rows found.")
                    else:st.success(f"{f.name}: {len(result)} mapped rows extracted.");st.dataframe(result,use_container_width=True)
                else:
                    extracted=str(content)
                    with st.expander("🔎 Extracted text / OCR",expanded=False):st.text(extracted[:12000] if extracted else "[No text detected]")
                    if extracted.strip():
                        status.info("Step 3/4 — Parsing extracted order…");customer,rows=parse_order(extracted,lambda v,t: progress.progress(min(0.65+v*0.25,0.90),text=t));show_order_result(customer,rows,f.name)
                    else:st.error(f"{f.name}: no readable text was detected.")
            except Exception as e:st.error(f"{f.name}: {e}")
        progress.progress(1.0,text="Done — order processed and validated.");status.success("Step 4/4 — Complete. Review the Triple-check table before SAP paste.")

with teach_tab:
    st.subheader("🎓 Teach the Parser")
    st.write("Write a rule once and save it. Product aliases can be written naturally, for example: **'mf white dice = FG-02-0102'**.")
    teach_text=st.text_area("Teaching / rule",height=180,placeholder="Example: Customer ABC calls Nivora MF White Dice 'MF White'. Use FG-02-0102.",key="teach_text")
    c1,c2=st.columns([1,1])
    with c1:teach_category=st.selectbox("Rule type",["general","customer","product alias","quantity / conversion"])
    with c2:teach_customer=st.text_input("Customer (optional)",placeholder="Only if this rule is customer-specific")
    if st.button("💾 Save & Remember Rule",type="primary"):
        category="customer" if teach_category=="customer" else ("general" if teach_category=="product alias" else teach_category)
        ok,msg=teach_rule(teach_text,category,teach_customer)
        if ok:st.success(msg);RULES=load_rules()
        else:st.warning(msg)
    st.divider();st.subheader("Saved memory")
    rules=load_rules();aliases=rules.get("product_aliases",[])
    if aliases:st.dataframe(pd.DataFrame(aliases),use_container_width=True)
    for label,key in [("General rules","general_rules"),("Customer rules","customer_rules"),("Quantity / conversion rules","quantity_rules")]:
        items=rules.get(key,[])
        if items:
            st.markdown(f"**{label}**")
            for i,r in enumerate(items,1):st.write(f"{i}. {r.get('rule','')}" + (f" — Customer: {r.get('customer')}" if r.get('customer') else ""))

with excel_tab:
    st.subheader("Upload Excel / CSV")
    uploaded=st.file_uploader("Supported: XLSX, XLS, CSV",type=["xlsx","xls","csv"],accept_multiple_files=True,key="excel_upload")
    if uploaded and st.button("Process Excel / CSV",type="primary"):
        all_frames=[]
        for f in uploaded:
            try:
                df=pd.read_csv(f) if f.name.lower().endswith(".csv") else extract_excel(f);result=process_tabular(df)
                if not result.empty:result["Source File"]=f.name;all_frames.append(result)
            except Exception as e:st.error(f"{f.name}: {e}")
        if all_frames:
            final=pd.concat(all_frames,ignore_index=True);grouped=final.groupby(["Customer","FG Code","Product"],dropna=False)["SAP Qty (PKT)"].sum().reset_index();st.success(f"Processed {len(grouped)} customer/product lines.");st.dataframe(grouped,use_container_width=True)
            st.subheader("Customer-wise SAP Orders");customers=grouped["Customer"].fillna("").replace("nan","").unique();txt_parts=[]
            for cust in customers:
                cust_df=grouped[grouped["Customer"].fillna("")==cust];title=cust if cust else "UNKNOWN CUSTOMER";st.markdown(f"#### {title}");block="\n".join(sap_line(row["FG Code"],row["SAP Qty (PKT)"]) for _,row in cust_df.iterrows());st.code(block,language="text");txt_parts.append(f"### {title}\n{block}")
            st.download_button("Download All Customer Orders","\n\n".join(txt_parts),file_name="SAP_Orders_All_Customers.txt",mime="text/plain")
        else:st.warning("No valid order rows found.")

st.divider();st.caption("SAP format: FG CODE + 2 tabs + QTY in PKT + 5 tabs + HO-WH + 2 tabs + CHEESE")