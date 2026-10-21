"""Tests for answer_verifier. Run with: python test_answer_verifier.py (or pytest)."""

from answer_verifier import missing_from_evidence, verify_answer

YEAR_RESULT = '{"scope": {"covers_all_stores": true}, "totals": {"units": 90308, "units_compare": 95034, ' \
    '"units_change_pct": -5.0, "revenue": 6157517.72, "revenue_change_pct": -5.7}}'
EXCESS_RESULT = '{"scope": {"covers_all_stores": true}, "total_excess_value_in_scope": "190854419.94"}'
KIRKLAND_RESULT = '{"scope": {"covers_all_stores": false}, "units": 1171}'


def test_grounded_figures_pass():
    answer = "Scope: all stores\nUnits 90,308 vs 95,034 (-5.0%), revenue $6.16M (down 5.7%)."
    assert verify_answer(answer, [YEAR_RESULT]).problems == []


def test_fabricated_figure_is_flagged():
    result = verify_answer("Scope: all stores\nRevenue was 7,000,000.", [YEAR_RESULT])
    assert result.unverified == ["7,000,000"]


def test_wrong_rounding_is_flagged():
    assert verify_answer("Scope: x\nRevenue fell 5.8%.", [YEAR_RESULT]).unverified == ["5.8%"]
    assert verify_answer("Scope: x\nRevenue fell 5.7%.", [YEAR_RESULT]).unverified == []


def test_millions_match_within_displayed_precision():
    assert verify_answer("Scope: x\nExcess is $190.9M.", [EXCESS_RESULT]).unverified == []
    assert verify_answer("Scope: x\nExcess is $195M.", [EXCESS_RESULT]).unverified == ["$195M"]


def test_names_dates_and_small_numbers_are_ignored_and_codes_must_come_from_a_tool():
    answer = (
        "Scope: x\nSliding Miter Saw 12-inch, 50lb bag, 2x4x8 lumber, SKU ELJB000015, "
        "as of 2026-10-13, in 2023, top 3 of 8 stores, month 7."
    )
    assert verify_answer(answer, [YEAR_RESULT, '{"sku": "ELJB000015"}']).problems == []  # the code came from a tool
    assert any("ELJB000015" in p for p in verify_answer(answer, [YEAR_RESULT]).problems)  # an unreturned code is now a finding


def test_calculation_result_is_not_checked_but_its_inputs_are():
    ok = "Scope: x\nMy calculation: 95,034 - 90,308 = 4,726 fewer units."
    assert verify_answer(ok, [YEAR_RESULT]).problems == []
    bad = "Scope: x\nMy calculation: 1,000,000 + 2,000,000 = 3,000,000."
    assert verify_answer(bad, [YEAR_RESULT]).unverified == ["1,000,000", "2,000,000"]


def test_calculation_line_without_a_result_is_fully_checked():
    answer = "Scope: x\nMy calculation: 4,726 fewer units."
    assert verify_answer(answer, [YEAR_RESULT]).unverified == ["4,726"]


def test_figures_from_the_users_question_count_as_evidence():
    answer = "Scope: x\nAt a 40% discount the loss is shown below."
    assert verify_answer(answer, [YEAR_RESULT, "what if we sold at 40 percent below cost"]).problems == []


def test_figures_without_scope_line_are_flagged():
    result = verify_answer("Units were 90,308.", [YEAR_RESULT])
    assert result.issues == ['The answer has figures but no "Scope:" line.']


def test_answer_without_figures_needs_no_scope():
    assert verify_answer("I could not find anything for that.", [YEAR_RESULT]).problems == []


def test_network_claim_is_flagged_only_when_not_all_stores():
    claim = "Scope: Zava Retail Kirkland\nThe network total is 1,171 units."
    assert len(verify_answer(claim, [KIRKLAND_RESULT]).issues) == 1
    assert verify_answer(claim, [YEAR_RESULT.replace("90308", "1171")]).issues == []


def test_negated_network_claim_is_allowed():
    answer = "Scope: Zava Retail Kirkland\nI cannot give a network total. Kirkland sold 1,171 units."
    assert verify_answer(answer, [KIRKLAND_RESULT]).problems == []


def test_problems_lists_everything_found():
    result = verify_answer("Revenue was 7,000,000.", [YEAR_RESULT])
    assert len(result.problems) == 2


def test_wrong_arithmetic_is_flagged():
    answer = "Scope: x\nMy calculation: 95,034 - 90,308 = 5,000."
    problems = verify_answer(answer, [YEAR_RESULT]).problems
    assert len(problems) == 1 and "does not check out" in problems[0] and "4,726.00" in problems[0]


def test_later_calculation_may_use_an_earlier_confirmed_result():
    evidence = ['{"scope": 1, "a": 4430800.00, "b": 3644850.00, "c": 3513000.00}', "sell at 40 percent below cost"]
    answer = (
        "Scope: x\n"
        "My calculation: 4430800.00 + 3644850.00 + 3513000.00 = 11588650.00\n"
        "My calculation: 40% x 11588650.00 = 4635460.00"
    )
    assert verify_answer(answer, evidence).problems == []


def test_later_calculation_cannot_use_an_unconfirmed_result():
    answer = "Scope: x\nMy calculation: 1.00 + 1.00 = 3.00\nMy calculation: 3.00 x 90308 = 270924.00"
    assert verify_answer(answer, [YEAR_RESULT]).problems != []


def test_calculation_that_is_not_arithmetic_is_flagged():
    answer = "Scope: x\nMy calculation: units sold divided by orders = 3.40"
    assert verify_answer(answer, [YEAR_RESULT]).issues[0].startswith("Calculation is not plain arithmetic")


def test_decimal_input_matches_a_percentage_in_the_evidence():
    evidence = ['{"scope": 1, "excess": 3513000.00}', "sell at 40 percent below cost"]
    answer = "Scope: x\nMy calculation: 3513000.00 * 0.4 = 1405200.00"
    assert verify_answer(answer, evidence).problems == []
    assert verify_answer("Scope: x\nMy calculation: 3513000.00 * 0.7 = 2459100.00", evidence).unverified == ["0.7"]


def test_calculation_may_start_with_a_negative_number():
    evidence = ['{"scope": 1, "gap": -25973, "surplus": 6027}']
    answer = "Scope: x\n- My calculation: -25973 + 6027 = -19946 (still below)"
    assert verify_answer(answer, evidence).problems == []


def test_numbers_are_matched_to_the_evidence_at_their_own_precision():
    evidence = ['{"excess_value": 4430800.00, "pct": 12.3, "units": 9469}']
    assert missing_from_evidence([4430800, 12.3, 9469, 9469.0, -9469], evidence) == []
    assert missing_from_evidence([4430801, 12.4, 5555], evidence) == [4430801, 12.4, 5555]


def test_a_calculation_line_with_a_label_is_checked_on_its_arithmetic():
    evidence = ["max 1.561 min 0.608"]
    assert verify_answer("Scope: all\nMy calculation: GARDEN swing = 1.561 - 0.608 = 0.953", evidence).problems == []
    assert verify_answer("Scope: all\nMy calculation: GARDEN swing = 1.561 - 0.608 = 0.900", evidence).problems


def test_words_around_the_numbers_of_a_calculation_do_not_break_the_check():
    ev = ["units_over_equal_cover: -26649, units_over_equal_cover: 6035"]
    line = "Scope: all\nMy calculation: Seattle units_over_equal_cover (-26,649) + Kirkland units_over_equal_cover (6,035) = -20,614"
    assert verify_answer(line, ev).problems == []
    assert verify_answer(line.replace("-20,614", "-20,000"), ev).problems


def test_a_table_cell_that_can_be_recomputed_from_its_row_is_accepted():
    ev = ["Seattle units 25349 revenue 1726491.36 units_2022 26075"]
    table = ("Scope: all\n\n| Store | Units | Revenue ($) | Revenue per unit ($) | Change vs 2022 (%) |\n|:---|---:|---:|---:|---:|\n"
             "| Seattle | 25349 | 1726491.36 | 68.11 | -2.78 |\n")
    assert verify_answer(table, ev).problems == []


def test_a_table_cell_that_does_not_follow_from_its_row_is_still_flagged():
    ev = ["Seattle units 25349 revenue 1726491.36 units_2022 26075"]
    table = ("Scope: all\n\n| Store | Units | Revenue ($) | Revenue per unit ($) |\n|:---|---:|---:|---:|\n"
             "| Seattle | 25349 | 1726491.36 | 99.11 |\n")
    assert any("99.11" in p for p in verify_answer(table, ev).problems)


def test_a_made_up_whole_number_cannot_pass_by_matching_a_tool_figure():
    ev = ["units 25349 revenue 1726491.36 stock 13280 value 2456800.00 other 40 55 300 1000"]
    table = "Scope: all\n\n| Store | Units |\n|:---|---:|\n| Seattle | 25349 |\n| Online | 13281 |\n"
    assert any("13281" in p for p in verify_answer(table, ev).problems)


def test_a_calculation_line_with_bracketed_labels_is_checked_on_its_arithmetic():
    ev = ["revenue 1726491.36 units 25349"]
    ok = "Scope: all\nMy calculation: 1726491.36 (revenue for Seattle) / 25349 (units for Seattle) = 68.11"
    assert verify_answer(ok, ev).problems == []
    assert verify_answer(ok.replace("68.11", "70.00"), ev).problems


def test_the_rounded_value_after_an_arrow_is_what_is_checked():
    ev = ["revenue 83369.67 units 1171"]
    assert verify_answer("Scope: all\nMy calculation: 83369.67 / 1171 = 71.1955600352 -> 71.20", ev).problems == []
    assert verify_answer("Scope: all\nMy calculation: 83369.67 / 1171 = 71.1955600352 -> 72.00", ev).problems


def test_a_small_whole_number_in_a_table_is_data_and_must_trace_to_a_tool_result():
    ev = ['{"results": [{"sku": "A", "units": 13, "previous_units": 15}]}']
    ok = "Scope: all\n\n| Product | Units | Previous |\n|:---|---:|---:|\n| A | 13 | 15 |\n"
    assert verify_answer(ok, ev).problems == []
    wrong = ok.replace("| 13 |", "| 47 |")
    assert any("47" in p for p in verify_answer(wrong, ev).problems)
    assert verify_answer("Scope: all\n\n| Rank | Product |\n|---:|:---|\n| 3 | A |\n", ev).problems == []  # ranks under 10 are not data


def test_a_sku_no_tool_returned_is_flagged_and_a_returned_one_is_not():
    ev = ['{"results": [{"product_name": "Digital Caliper 6-inch", "sku": "HTMT000017", "units": 2292}]}', "question: top sellers"]
    ok = "Scope: all\n\n| Product | SKU | Units |\n|:---|:---|---:|\n| Digital Caliper 6-inch | HTMT000017 | 2292 |\n"
    assert verify_answer(ok, ev).problems == []
    bad = ok.replace("HTMT000017", "HTMT000099")
    assert any("HTMT000099" in p for p in verify_answer(bad, ev).problems)


def test_a_sku_the_user_typed_is_allowed_and_ordinary_words_are_not_mistaken_for_skus():
    ev = ['{"results": []}', "how is LBMLD005 doing?"]
    assert verify_answer("Scope: all\n\nNo sales for LBMLD005 this month, using HTTP2 and GPT4 style names is not a SKU.", ev).problems == []


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
