"""Regression tests for the deterministic parser core.

Every expectation here comes from MASTER_TRAINING_CHEESE_ORDER_STOCK_SAP_V2.txt
or from a bug that was found in the previous version of the parser.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import (  # noqa: E402
    PRODUCTS,
    load_rules,
    match_product,
    normalize,
    parse_line,
    parse_order,
    parse_quantity,
    sap_line,
    teach_rule,
)
from item_master import WP_VARIANTS, is_wp_code  # noqa: E402

RULES = load_rules()


def code_of(text):
    return match_product(text, RULES).code


def units_of(text):
    return parse_line(text, RULES).sap_units


# ---------------------------------------------------------------- item master


def test_every_wp_pair_exists():
    for regular, wp in WP_VARIANTS.items():
        assert regular in PRODUCTS and wp in PRODUCTS
        assert is_wp_code(wp) and not is_wp_code(regular)


def test_parser_never_returns_an_unknown_code():
    samples = [
        "allana pizza 70/30 shred yellow wp 2 ctn", "allana gold mozz dice yellow wp 1 ctn",
        "top cow premium white wp 2 ctn", "nivora pt yellow shred wp 3 ctn",
        "silver cheddar block 1 ctn", "achha mozz block wp 2 ctn", "desi ghee 16kg 2 pkt",
    ]
    for text in samples:
        match = match_product(text, RULES)
        assert match.code is None or match.code in PRODUCTS, text
        assert match.suggestion is None or match.suggestion in PRODUCTS, text


# ---------------------------------------------------------------- normalising


@pytest.mark.parametrize(
    "raw,expected_fragment",
    [
        ("Achha Mozz Blk", "achha mozzarella block"),
        ("ACCHA SHARED", "achha shred"),
        ("Classic Chadder Block", "classic cheddar block"),
        ("70.30 lockl shredd", "70/30 local shred"),
        ("Top-Cow White Dice", "top cow white dice"),
        ("2 Cartons", "2 ctn"),
        ("5 Packets", "5 pkt"),
        ("W.Poly", "wp"),
        ("w/p", "wp"),
        ("W Poly", "wp"),
    ],
)
def test_normalisation(raw, expected_fragment):
    assert expected_fragment in normalize(raw)


# ---------------------------------------------------------------- quantities


@pytest.mark.parametrize(
    "text,expected",
    [
        ("3 CTN 70/30 Local", [(3, "CTN")]),                     # ratio is not a quantity
        ("50/50 shredded 10 ctn", [(10, "CTN")]),
        ("Butter salted 82 fat 5 ctn", [(5, "CTN")]),            # fat % is not a quantity
        ("Yellow slice 800 gm 3 ctn", [(3, "CTN")]),             # gram size is not a quantity
        ("Top cow dice 2 packet 10:31 PM", [(2, "PKT")]),        # timestamp is not a quantity
        ("Achha mozz block 2kg 4 ctn", [(4, "CTN")]),            # pack size is not a quantity
        ("Nivora max white dice 2.5kg 2 ctn", [(2, "CTN")]),
        ("90 kg 70/30 local", [(90, "KG")]),
        ("2 kg burger slice", [(2, "KG")]),
        ("1 ctn 2 pkt achha shred", [(1, "CTN"), (2, "PKT")]),
    ],
)
def test_quantity_extraction(text, expected):
    quantity = parse_quantity(text)
    assert quantity.parts == [(float(v), u) for v, u in expected], quantity


def test_quantity_without_unit_is_flagged_not_guessed():
    quantity = parse_quantity("achha shared 20")
    assert quantity.review
    assert parse_line("achha shared 20", RULES).status == "CHECK"


def test_pack_size_alone_is_not_a_quantity():
    line = parse_line("Achha mozz block 2kg", RULES)
    assert line.status == "CHECK"
    assert line.sap_units is None


# ---------------------------------------------------------------- conversions


@pytest.mark.parametrize(
    "text,expected_code,expected_units",
    [
        ("3 CTN 70/30 Local", "FG-03-0018", 15),        # 5 pcs/ctn
        ("2 CTN Blue Shredd", "FG-01-0042", 10),
        ("1 CTN Danish Mozz Block", "FG-01-0018", 10),  # 10 pcs/ctn
        ("2 kg Burger Slice", "FG-02-0028", 2),         # 2 PCS, never 2 CTN
        ("2 ctn burger slice", "FG-02-0028", 36),       # 18 pcs/ctn
        ("4 CTN Top Cow Yellow Shred", "FG-02-0049", 20),
        ("90 kg 70/30 local", "FG-03-0018", 45),        # 90kg = 9 ctn = 45 pcs
        ("Nivora MF white dice 3 ctn", "FG-02-0102", 12),   # 4 pcs/ctn
        ("achha mozz block 25 pkt", "FG-01-0006", 25),      # PKT is never multiplied
        ("desi ghee 1kg 6 pkt", "FG-05-0011", 6),
    ],
)
def test_conversion(text, expected_code, expected_units):
    line = parse_line(text, RULES)
    assert line.code == expected_code, line
    assert line.sap_units == expected_units, line
    assert line.status == "OK", line.note


# ---------------------------------------------------------------- mapping


@pytest.mark.parametrize(
    "text,expected",
    [
        # special mappings
        ("Red mozz blk 2 ctn", "FG-01-0006"),
        ("Blue shredd 2 ctn", "FG-01-0042"),
        ("Danish mozz block 1 ctn", "FG-01-0018"),
        ("Danish shredd 1 ctn", "FG-01-0030"),
        ("Mozzarella block 3 ctn", "FG-01-0006"),          # generic default = Achha
        # Top Cow: shred == dice
        ("Top cow white shred 2 ctn", "FG-02-0048"),
        ("Top cow white dice 2 ctn", "FG-02-0048"),
        ("Top cow yellow shredded 2 ctn", "FG-02-0049"),
        ("Top cow cheddar block 1 ctn", "FG-02-0068"),
        ("Top cow block 1 ctn", "FG-02-0060"),
        # Nivora: shred != dice
        ("Nivora MF white shredded 2 ctn", "FG-02-0101"),
        ("MF white dice 2 ctn", "FG-02-0102"),
        ("Pro yellow shred 1 ctn", "FG-02-0107"),
        ("PT yellow shredd 1 ctn", "FG-02-0119"),
        ("VF white dice 1 ctn", "FG-02-0114"),
        # silver
        ("Silver cheddar block 1 ctn", "FG-02-0040"),
        ("New silver chadder blk 1 ctn", "FG-02-0080"),
        ("Silver cheddar shred 1 ctn", "FG-02-0067"),
        ("Silver mozzarella shred 1 ctn", "FG-01-0110"),
        ("Silver mozz block 1 ctn", "FG-01-0111"),
        # ratios
        ("Classic 70/30 shredded 5 ctn", "FG-02-0072"),
        ("Imp 70/30 5 ctn", "FG-03-0006"),
        ("Imported 70/30 dice 5 ctn", "FG-03-0026"),
        ("M3 70/30 2 ctn", "FG-02-0051"),
        ("50/50 shredded 10 ctn", "FG-03-0024"),
        # classic / achha
        ("Classic shredd 4 ctn", "FG-02-0036"),
        ("Classic cheddar block 4 ctn", "FG-02-0012"),
        ("Classic mozz block 4 ctn", "FG-01-0012"),
        ("Achha white dice 2 ctn", "FG-01-0124"),
        ("Achha yellow dice 2 ctn", "FG-01-0125"),
        ("Achha shared yellow 2 ctn", "FG-01-0054"),
        ("Achha shredded 2 ctn", "FG-01-0042"),
        # slices
        ("White slice 2 ctn", "FG-02-0023"),
        ("White slice 800gm 2 ctn", "FG-02-0037"),
        ("Burger slice 2 ctn", "FG-02-0028"),
        ("Orange slice 800 gm 2 ctn", "FG-02-0038"),
        ("Jalapeno slice 1 ctn", "FG-02-0039"),
        # pizza topping vs Nivora PT
        ("Pizza topping block 1 ctn", "FG-02-0065"),
        ("Pizza topping shredd 1 ctn", "FG-02-0064"),
        ("Pizza topping white dice 1 ctn", "FG-02-0118"),
        # butter
        ("Salted butter 2 pkt", "FG-06-0011"),
        ("Unsalted butter 2 pkt", "FG-06-0004"),
        ("Butter yellow 87 fat 2 pkt", "FG-06-0018"),
        ("Butter white 500gm 2 pkt", "FG-06-0003"),
        # ghee
        ("Desi ghee 500gm 3 pkt", "FG-05-0002"),
        ("Desi ghee 16kg 1 pkt", "FG-05-0005"),
        # explicit FG code wins
        ("FG-01-0042 25 pkt", "FG-01-0042"),
    ],
)
def test_product_mapping(text, expected):
    assert code_of(text) == expected, match_product(text, RULES)


# ---------------------------------------------------------------- W.Poly rule


@pytest.mark.parametrize(
    "regular_text,wp_text,regular_code,wp_code",
    [
        ("Top cow white dice 3 ctn", "Top cow white dice WP 3 ctn", "FG-02-0048", "FG-02-0076"),
        ("Top cow yellow shred 3 ctn", "Top cow yellow shred W.Poly 3 ctn", "FG-02-0049", "FG-02-0077"),
        ("Achha mozz block 2 ctn", "Achha mozz block WP 2 ctn", "FG-01-0006", "FG-01-0123"),
        ("Achha shredd 2 ctn", "Achha shredd W.P 2 ctn", "FG-01-0042", "FG-01-0119"),
        ("Latina shred 2 ctn", "Latina shred wp 2 ctn", "FG-01-0066", "FG-01-0120"),
        ("Local 70/30 shred 2 ctn", "Local 70/30 shred wp 2 ctn", "FG-03-0018", "FG-01-0121"),
        ("Verona shred 2 ctn", "Verona shred w-poly 2 ctn", "FG-01-0072", "FG-01-0122"),
        ("Nivora MF white dice 2 ctn", "Nivora MF white dice wp 2 ctn", "FG-02-0102", "FG-02-0093"),
        ("Nivora pro yellow shred 2 ctn", "Nivora pro yellow shred wp 2 ctn", "FG-02-0107", "FG-02-0123"),
        ("Allana mozzarella shred white 2 ctn", "Allana mozzarella shred white wp 2 ctn", "FG-02-0097", "FG-02-0164"),
    ],
)
def test_wp_is_conditional(regular_text, wp_text, regular_code, wp_code):
    assert code_of(regular_text) == regular_code
    assert code_of(wp_text) == wp_code


def test_wp_without_a_wp_sku_is_flagged():
    match = match_product("Silver cheddar block wp 1 ctn", RULES)
    assert match.code is None
    assert "W.Poly" in match.review
    assert match.suggestion == "FG-02-0040"


def test_wp_is_never_inferred_from_a_saved_alias():
    # rules.json contains the alias "top cow white dice" -> FG-02-0048.
    assert code_of("Top cow white dice wp 3 ctn") == "FG-02-0076"


def test_allana_specific_beats_generic_5050_alias():
    assert code_of("Allana pizza 50/50 yellow wp 3 ctn") == "FG-02-0184"
    assert code_of("50/50 shredded 3 ctn") == "FG-03-0024"


def test_allana_missing_sku_goes_to_review():
    match = match_product("Allana pizza 70/30 shredded yellow wp 2 ctn", RULES)
    assert match.code is None
    assert "not in the item master" in match.review


# ---------------------------------------------------------------- ambiguity


@pytest.mark.parametrize(
    "text",
    [
        "70/30 shredded 3 ctn",          # brand missing
        "Nivora MF white 2 ctn",         # dice or shredded?
        "Slice 2 ctn",                   # colour missing
        "Butter 3 pkt",                  # salted/unsalted missing
        "Shredded 4 ctn",                # nothing to map
        "Classic block 2 ctn",           # cheddar or mozzarella?
    ],
)
def test_ambiguous_lines_are_flagged(text):
    line = parse_line(text, RULES)
    assert line.status == "CHECK", line
    assert line.note


def test_butter_colour_conflict_is_flagged():
    line = parse_line("Salted butter white 2 pkt", RULES)
    assert line.status == "CHECK"
    assert "salted" in line.note.lower()


# ---------------------------------------------------------------- orders


def test_customers_are_never_merged():
    text = """Babar Ali
3 CTN 70/30 Local
2 CTN Blue Shredd
1 CTN Danish Mozz Block
2 kg Burger Slice
Cheese Wala Traders
4 CTN Top Cow Yellow Shred"""
    orders = parse_order(text, RULES)
    assert [order.customer for order in orders] == ["Babar Ali", "Cheese Wala Traders"]
    assert orders[0].merged() == {
        "FG-03-0018": 15,
        "FG-01-0042": 10,
        "FG-01-0018": 10,
        "FG-02-0028": 2,
    }
    assert orders[1].merged() == {"FG-02-0049": 20}


def test_same_product_is_merged_inside_one_customer_only():
    text = """Shop A
2 ctn achha shredd
3 ctn achha shredd
Shop B
1 ctn achha shredd"""
    orders = parse_order(text, RULES)
    assert orders[0].merged() == {"FG-01-0042": 25}
    assert orders[1].merged() == {"FG-01-0042": 5}


def test_customer_code_is_captured_and_never_mapped_to_a_product():
    text = """Metro Foods
CFS-12345
2 ctn white slice"""
    orders = parse_order(text, RULES)
    assert len(orders) == 1
    assert orders[0].customer == "Metro Foods"
    assert orders[0].customer_code == "CFS12345"
    assert orders[0].merged() == {"FG-02-0023": 36}


def test_noise_lines_are_ignored():
    text = """Al Karam
Forwarded
Salam
10:31 PM
2 ctn classic shredd
Self Pick
Thanks"""
    orders = parse_order(text, RULES)
    assert orders[0].merged() == {"FG-02-0036": 10}
    assert orders[0].ignored


def test_whatsapp_style_block_markers():
    text = """=== CUSTOMER BLOCK 1 ===
CUSTOMER: Pizza Point
3 ctn top cow white shred
=== CUSTOMER BLOCK 2 ===
CUSTOMER: Burger Lab
2 ctn burger slice"""
    orders = parse_order(text, RULES)
    assert [order.customer for order in orders] == ["Pizza Point", "Burger Lab"]
    assert orders[0].merged() == {"FG-02-0048": 15}
    assert orders[1].merged() == {"FG-02-0028": 36}


def test_review_lines_stay_out_of_the_sap_block():
    text = """Shop X
2 ctn classic shredd
20 achha shredd"""
    orders = parse_order(text, RULES)
    order = orders[0]
    assert order.merged() == {"FG-02-0036": 10}
    assert len(order.review_lines) == 1
    assert "unit" in order.review_lines[0].note.lower()


# ---------------------------------------------------------------- SAP output


def test_sap_line_format():
    assert sap_line("FG-01-0042", 25) == "FG-01-0042\t\t25\t\t\t\t\tHO-WH\t\tCHEESE"
    assert sap_line("FG-01-0042", 25).count("\t") == 9


def test_sap_block_contains_only_sap_lines():
    text = "Shop Y\n2 ctn classic shredd\nplease deliver today\n20 achha shredd"
    order = parse_order(text, RULES)[0]
    for line in order.sap_text().splitlines():
        assert line.startswith("FG-") and line.endswith("CHEESE")


# ---------------------------------------------------------------- teaching


def test_teaching_an_alias(tmp_path):
    rules_file = tmp_path / "rules.json"
    ok, message = teach_rule("Customer ABC calls it 'MF White' = FG-02-0102", path=rules_file)
    assert ok and "FG-02-0102" in message
    taught = load_rules(rules_file)
    assert taught["product_aliases"][0]["code"] == "FG-02-0102"
    assert code_of("mf white 2 ctn") is None  # still ambiguous with default rules
    assert match_product("mf white 2 ctn", taught).code == "FG-02-0102"


def test_teaching_rejects_an_invented_code(tmp_path):
    ok, message = teach_rule("Something = FG-99-9999", path=tmp_path / "rules.json")
    assert not ok and "item master" in message


# ---------------------------------------------------------------- tabular


def test_process_tabular_units_and_cartons():
    pd = pytest.importorskip("pandas")
    from core import process_tabular, tabular_to_orders

    frame = pd.DataFrame([
        {"Customer": "Alpha", "SAP Code": "FG-01-0042", "Product": "Achha Shredded", "Cartons": 2, "Units": 10},
        {"Customer": "Alpha", "SAP Code": "", "Product": "Danish Mozz Block", "Cartons": 1, "Units": 0},
        {"Customer": "Beta", "SAP Code": "FG-01-0042", "Product": "Achha Shredded", "Cartons": 2, "Units": 7},
    ])
    result = process_tabular(frame, RULES)
    assert list(result["SAP Qty (PKT)"]) == [10, 10, 7]
    assert result.iloc[2]["Status"] == "CHECK"          # 2 x 5 != 7
    orders = tabular_to_orders(result)
    assert [order.customer for order in orders] == ["Alpha", "Beta"]
    assert orders[0].merged() == {"FG-01-0042": 10, "FG-01-0018": 10}


def test_heading_with_inline_customer_code():
    text = """Al Madina Traders CFS-10234
2 ctn top cow white shred
Metro Foods BP4471
1 ctn danish mozz blk"""
    orders = parse_order(text, RULES)
    assert [(order.customer, order.customer_code) for order in orders] == [
        ("Al Madina Traders", "CFS10234"),
        ("Metro Foods", "BP4471"),
    ]
    assert orders[0].merged() == {"FG-02-0048": 10}
    assert orders[1].merged() == {"FG-01-0018": 10}


def test_ratio_beats_brand_when_both_are_written():
    assert code_of("achha 70/30 shred local 5 ctn") == "FG-03-0018"


def test_product_without_quantity_is_reviewed_not_treated_as_customer():
    orders = parse_order("Shop Z\nachha shredded\n2 ctn white slice", RULES)
    assert len(orders) == 1
    assert orders[0].merged() == {"FG-02-0023": 36}
    assert len(orders[0].review_lines) == 1


def test_assume_unit_opt_in():
    orders = parse_order("Shop Q\n20 achha shredd", RULES, assume_unit="CTN")
    assert orders[0].merged() == {"FG-01-0042": 100}
    orders = parse_order("Shop Q\n20 achha shredd", RULES, assume_unit="PKT")
    assert orders[0].merged() == {"FG-01-0042": 20}


def test_every_item_master_name_maps_back_to_its_own_code():
    """The strongest invariant: writing the official product name must return it."""
    for code, product in PRODUCTS.items():
        assert match_product(f"{product['name']} 2 ctn", RULES).code == code, product["name"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("white slice 800 2 ctn", "FG-02-0037"),      # size without "gm"
        ("yellow slice 800 2 ctn", "FG-02-0038"),
        ("butter yellow 500 2 pkt", "FG-06-0010"),
        ("desi ghee 16 1 pkt", "FG-05-0005"),
        ("desi ghee 16 ctn", "FG-05-0011"),           # 16 CTN of the 1kg tin, not 16kg
        ("m3 shred 2 ctn", "FG-02-0051"),
        ("uk shred wp 2 ctn", "FG-01-0126"),
        ("max w dice 2 ctn", "FG-02-0110"),           # w = white
        ("pt y shred 1 ctn", "FG-02-0119"),           # y = yellow
    ],
)
def test_shorthand_sizes_and_abbreviations(text, expected):
    assert code_of(text) == expected, match_product(text, RULES)


def test_nivora_default_form_is_opt_in():
    assert match_product("mf white 2 ctn", RULES).code is None
    assert match_product("mf white 2 ctn", RULES, default_form="dice").code == "FG-02-0102"
