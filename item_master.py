"""Authoritative SAP item master for the cheese order parser.

Every FG code the parser can ever emit must exist in PRODUCTS. Nothing else is
allowed to invent a code (see MASTER_TRAINING_CHEESE_ORDER_STOCK_SAP_V2.txt:
"Never invent an FG code").

Fields
------
name     : human readable product name shown in the check tables
pack     : packing family (block / regular / slice / slice800 / nivora / unit)
pcs_ctn  : packets (SAP units) per carton -- used for CTN -> PKT conversion
kg       : kilograms per packet          -- used for KG  -> PKT conversion
keywords : low priority free text hints used only by the fallback matcher
"""

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

# ============================================================
# AUGUST-18 ITEM MASTER EXTENSIONS
# These are explicit W.Poly/WP and newly locked mappings.
# WP items are used ONLY when the order explicitly contains WP/W.P/W.Poly.
# ============================================================
PRODUCTS.update({
    "FG-02-0040": {"name":"Silver Cheddar Block", "pack":"block", "pcs_ctn":10, "kg":2, "keywords":["silver cheddar block","silver chadder block"]},
    "FG-02-0067": {"name":"Silver Cheddar Shred", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["silver cheddar shred","silver cheddar shredded","silver chadder shred"]},
    "FG-02-0080": {"name":"New Silver Cheddar Block", "pack":"block", "pcs_ctn":10, "kg":2, "keywords":["new silver cheddar block","new silver chadder block","new silver chadder blk"]},

    # Achha W.Poly
    "FG-01-0123": {"name":"Achha Mozzarella Block W.Poly 2kg", "pack":"block", "pcs_ctn":10, "kg":2, "keywords":["achha mozz block wp","achha mozzarella block wp"]},
    "FG-01-0119": {"name":"Achha Mozzarella Shredded White W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["achha mozz shred wp","achha mozzarella shredded wp"]},
    "FG-01-0120": {"name":"Latina Mozzarella Shredded WP 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["latina shred wp","latina mozzarella shred wp"]},
    "FG-01-0121": {"name":"Local 70/30 Mozzarella/Cheddar Shredded WP 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["local 70/30 wp","local 70/30 mozzarella cheddar wp"]},
    "FG-01-0122": {"name":"Verona Mozzarella Shredded WP 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["verona shred wp","verona mozzarella shred wp"]},
    "FG-01-0126": {"name":"Imported/UK Mozzarella Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["uk shred wp","imported uk shred wp"]},

    # Top Cow W.Poly — Shred and Dice are the same SKU
    "FG-02-0076": {"name":"Top Cow White Mozzarella Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["top cow white dice wp","top cow white shred wp","top cow white shredded wp"]},
    "FG-02-0077": {"name":"Top Cow Yellow Mozzarella Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["top cow yellow dice wp","top cow yellow shred wp","top cow yellow shredded wp"]},
    "FG-02-0079": {"name":"Top Cow Premium White Mozzarella Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["top cow premium white dice wp","top cow premium white shred wp"]},

    # Nivora W.Poly 2kg variants
    "FG-02-0126": {"name":"Nivora Max White Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0125": {"name":"Nivora Max White Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0128": {"name":"Nivora Max Yellow Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0127": {"name":"Nivora Max Yellow Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0093": {"name":"Nivora MF White Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0092": {"name":"Nivora MF White Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0091": {"name":"Nivora MF Yellow Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0090": {"name":"Nivora MF Yellow Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0122": {"name":"Nivora Pro White Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0121": {"name":"Nivora Pro White Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0124": {"name":"Nivora Pro Yellow Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0123": {"name":"Nivora Pro Yellow Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0134": {"name":"Nivora PT White Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0133": {"name":"Nivora PT White Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0136": {"name":"Nivora PT Yellow Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0135": {"name":"Nivora PT Yellow Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0130": {"name":"Nivora VF White Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0129": {"name":"Nivora VF White Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0132": {"name":"Nivora VF Yellow Dice W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},
    "FG-02-0131": {"name":"Nivora VF Yellow Shredded W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":[]},

    # Allana W.Poly
    "FG-02-0160": {"name":"Allana Cheddar Cheese Block W.Poly 2kg", "pack":"block", "pcs_ctn":10, "kg":2, "keywords":["allana cheddar block wp"]},
    "FG-02-0214": {"name":"Allana Cheddar Cheese Slice White W.Poly 800gm", "pack":"slice800", "pcs_ctn":18, "kg":0.8, "keywords":["allana white slice wp 800"]},
    "FG-02-0215": {"name":"Allana Cheddar Cheese Slice Yellow W.Poly 800gm", "pack":"slice800", "pcs_ctn":18, "kg":0.8, "keywords":["allana yellow slice wp 800"]},
    "FG-02-0159": {"name":"Allana Gold Cheddar Cheese Block W.Poly 2kg", "pack":"block", "pcs_ctn":10, "kg":2, "keywords":["allana gold cheddar block wp"]},
    "FG-02-0161": {"name":"Allana Gold Mozzarella Cheese Block W.Poly 2kg", "pack":"block", "pcs_ctn":10, "kg":2, "keywords":["allana gold mozzarella block wp"]},
    "FG-02-0167": {"name":"Allana Gold Mozzarella Cheese Dice White W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold mozz white dice wp"]},
    "FG-02-0169": {"name":"Allana Gold Mozzarella Cheese Dice Yellow W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold mozz yellow dice wp"]},
    "FG-02-0163": {"name":"Allana Gold Mozzarella Cheese Shredded White W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold mozz white shred wp"]},
    "FG-02-0165": {"name":"Allana Gold Mozzarella Cheese Shredded Yellow W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold mozz yellow shred wp"]},
    "FG-02-0177": {"name":"Allana Gold Pizza Cheese Dice 70/30 White W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold pizza dice 70/30 white wp"]},
    "FG-02-0179": {"name":"Allana Gold Pizza Cheese Dice 70/30 Yellow W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold pizza dice 70/30 yellow wp"]},
    "FG-02-0181": {"name":"Allana Gold Pizza Cheese Shredded 50/50 White W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold pizza shred 50/50 white wp"]},
    "FG-02-0183": {"name":"Allana Gold Pizza Cheese Shredded 50/50 Yellow W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold pizza shred 50/50 yellow wp"]},
    "FG-02-0173": {"name":"Allana Gold Pizza Cheese Shredded 70/30 White W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold pizza shred 70/30 white wp"]},
    "FG-02-0175": {"name":"Allana Gold Pizza Cheese Shredded 70/30 Yellow W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana gold pizza shred 70/30 yellow wp"]},
    "FG-02-0171": {"name":"Allana Gold Pizza Topping Block W.Poly 2kg", "pack":"block", "pcs_ctn":10, "kg":2, "keywords":["allana gold pizza topping block wp"]},
    "FG-02-0168": {"name":"Allana Mozzarella Cheese Dice White W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana mozz white dice wp"]},
    "FG-02-0170": {"name":"Allana Mozzarella Cheese Dice Yellow W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana mozz yellow dice wp"]},
    "FG-02-0178": {"name":"Allana Pizza Cheese Dice 70/30 White W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana pizza dice 70/30 white wp"]},
    "FG-02-0180": {"name":"Allana Pizza Cheese Dice 70/30 Yellow W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana pizza dice 70/30 yellow wp"]},
    "FG-02-0184": {"name":"Allana Pizza Cheese Shredded 50/50 Yellow W.Poly 2kg", "pack":"regular", "pcs_ctn":5, "kg":2, "keywords":["allana pizza shred 50/50 yellow wp"]},
    "FG-02-0172": {"name":"Allana Pizza Topping Block W.Poly 2kg", "pack":"block", "pcs_ctn":10, "kg":2, "keywords":["allana pizza topping block wp"]},
})


# ============================================================
# REGULAR  ->  W.POLY (WP) PAIRS
# A WP code may only be used when the order text explicitly says
# WP / W.P / W.Poly / W-Poly / W/P. If the customer writes WP for an item that
# has no WP counterpart here, the line is flagged for review instead of
# silently falling back to the regular SKU.
# ============================================================
WP_VARIANTS = {
    # Achha
    "FG-01-0006": "FG-01-0123",   # Achha Mozzarella Block
    "FG-01-0042": "FG-01-0119",   # Achha Mozzarella Shredded White
    # Other 2kg regulars
    "FG-01-0066": "FG-01-0120",   # Latina Mozzarella Shredded
    "FG-03-0018": "FG-01-0121",   # Local 70/30 Shredded
    "FG-01-0072": "FG-01-0122",   # Verona Mozzarella Shredded
    "FG-01-0036": "FG-01-0126",   # Imported / UK Mozzarella Shredded
    # Top Cow (shred and dice are the same SKU)
    "FG-02-0048": "FG-02-0076",   # Top Cow White Dice/Shred
    "FG-02-0049": "FG-02-0077",   # Top Cow Yellow Dice/Shred
    # Nivora 2.5kg regular -> Nivora 2kg W.Poly
    "FG-02-0102": "FG-02-0093",   # MF White Dice
    "FG-02-0101": "FG-02-0092",   # MF White Shredded
    "FG-02-0104": "FG-02-0091",   # MF Yellow Dice
    "FG-02-0103": "FG-02-0090",   # MF Yellow Shredded
    "FG-02-0106": "FG-02-0122",   # Pro White Dice
    "FG-02-0105": "FG-02-0121",   # Pro White Shredded
    "FG-02-0108": "FG-02-0124",   # Pro Yellow Dice
    "FG-02-0107": "FG-02-0123",   # Pro Yellow Shredded
    "FG-02-0110": "FG-02-0126",   # Max White Dice
    "FG-02-0109": "FG-02-0125",   # Max White Shredded
    "FG-02-0112": "FG-02-0128",   # Max Yellow Dice
    "FG-02-0111": "FG-02-0127",   # Max Yellow Shredded
    "FG-02-0118": "FG-02-0134",   # PT White Dice
    "FG-02-0117": "FG-02-0133",   # PT White Shredded
    "FG-02-0120": "FG-02-0136",   # PT Yellow Dice
    "FG-02-0119": "FG-02-0135",   # PT Yellow Shredded
    "FG-02-0114": "FG-02-0130",   # VF White Dice
    "FG-02-0113": "FG-02-0129",   # VF White Shredded
    "FG-02-0116": "FG-02-0132",   # VF Yellow Dice
    "FG-02-0115": "FG-02-0131",   # VF Yellow Shredded
    # Allana
    "FG-02-0094": "FG-02-0160",   # Allana Cheddar Block
    "FG-02-0096": "FG-02-0162",   # Allana Mozzarella Block
    "FG-02-0097": "FG-02-0164",   # Allana Mozzarella Shredded White
    "FG-02-0100": "FG-02-0174",   # Allana Pizza Cheese 70/30 Shredded White
}


def is_wp_code(code: str) -> bool:
    """True when the SAP code belongs to a W.Poly (WP) packed item."""
    name = PRODUCTS.get(code, {}).get("name", "").lower()
    return "w.poly" in name or "wpoly" in name or "w poly" in name or name.endswith(" wp") or " wp " in name


#: Codes that only ever exist as W.Poly (no regular counterpart in the master).
WP_ONLY = {code for code in PRODUCTS if is_wp_code(code) and code not in set(WP_VARIANTS.values())}

#: Reverse lookup, WP code -> regular code.
REGULAR_OF_WP = {wp: regular for regular, wp in WP_VARIANTS.items()}
