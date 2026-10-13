"""Tests for answer_verifier. Run with: python test_answer_verifier.py (or pytest)."""

from answer_verifier import verify_answer

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


def test_names_codes_dates_and_small_numbers_are_ignored():
    answer = (
        "Scope: x\nSliding Miter Saw 12-inch, 50lb bag, 2x4x8 lumber, SKU ELJB000015, "
        "as of 2026-10-13, in 2023, top 3 of 8 stores, month 7."
    )
    assert verify_answer(answer, [YEAR_RESULT]).problems == []


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


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_")]
    for fn in tests:
        fn()
        print("ok  ", fn.__name__)
    print(f"{len(tests)} passed")
