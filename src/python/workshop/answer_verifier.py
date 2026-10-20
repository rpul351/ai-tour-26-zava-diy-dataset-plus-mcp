"""Checks that figures and scope claims in an agent answer trace back to tool results."""

import ast
import re
from bisect import bisect_left, insort
from dataclasses import dataclass, field

_DATE = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")
_NUMBER = re.compile(r"(?<![\w.])-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?")
_SUFFIX = re.compile(r"^\s?(%|[KMB]\b|million\b|billion\b|thousand\b)", re.IGNORECASE)
_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "b": 1e9, "billion": 1e9}
_EVIDENCE_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")
_SELF_CALCULATED = "my calculation"
_NEGATION = re.compile(r"\b(not|cannot|can't|can not|only|no)\b", re.IGNORECASE)
_NETWORK_CLAIM = re.compile(r"network total|network-wide|company-wide|whole network|all-store total", re.IGNORECASE)


@dataclass
class Verification:
    unverified: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def problems(self) -> list[str]:
        found = []
        if self.unverified:
            found.append("Figures not found in any tool result: " + ", ".join(self.unverified))
        return found + self.issues


def _checkable_figures(answer: str) -> list[tuple[str, float, float]]:
    """Return (text, absolute value, tolerance) for every figure worth checking."""
    text = _DATE.sub(" ", answer)
    figures = []
    for match in _NUMBER.finditer(text):
        raw = match.group()
        tail = text[match.end() : match.end() + 12]
        suffix = _SUFFIX.match(tail)
        if not suffix and re.match(r"-?[A-Za-z]", tail):
            continue  # part of a name or code, such as 12-inch, 50lb or 2x4x8
        digits = raw.replace("$", "").replace(",", "").lstrip("-")
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        scale = _SCALE.get(suffix.group(1).lower().strip(), 1.0) if suffix else 1.0
        is_plain_integer = not suffix and "$" not in raw and "," not in raw and "." not in raw
        value = float(digits)
        if is_plain_integer and (value < 100 or 1900 <= value <= 2100):
            continue  # counts, ranks, months and years
        figures.append((raw + (suffix.group(0) if suffix else ""), value * scale, 0.5 * 10 ** (-decimals) * scale))
    return figures


def _evidence_values(evidence: list[str]) -> list[float]:
    return sorted({abs(float(n)) for text in evidence for n in _EVIDENCE_NUMBER.findall(text)})


def _present(values: list[float], target: float, tolerance: float) -> bool:
    index = bisect_left(values, target - tolerance - 1e-9)
    return index < len(values) and values[index] <= target + tolerance + 1e-9


def missing_from_evidence(numbers: list[float], evidence: list[str]) -> list[float]:
    """Numbers that do not appear in the evidence, allowing for the precision they were written with."""
    from decimal import Decimal

    values = _evidence_values(evidence)
    missing = []
    for number in numbers:
        decimals = max(0, -Decimal(str(number)).as_tuple().exponent)
        if not _present(values, abs(float(number)), 0.5 * 10 ** (-decimals)):
            missing.append(number)
    return missing


def _evaluate(expression: str) -> float:
    """Evaluate plain arithmetic (numbers, + - * / and brackets) without using eval."""

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            return -walk(node.operand) if isinstance(node.op, ast.USub) else walk(node.operand)
        if isinstance(node, ast.BinOp):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        raise ValueError("not plain arithmetic")

    return walk(ast.parse(expression, mode="eval"))


def evaluate_arithmetic(expression: str) -> tuple[float, list[float]]:
    """Evaluate plain arithmetic and return the result with every number it used. Raises ValueError if it is not plain arithmetic."""
    text = _arithmetic(expression)
    if not text or not re.fullmatch(r"[\d\s.+\-*/()]+", text):
        raise ValueError("not plain arithmetic")
    operands = [abs(float(m)) for m in re.findall(r"\d+(?:\.\d+)?", text)]
    return _evaluate(text), operands


def _arithmetic(text: str) -> str:
    text = text.replace("$", "").replace(",", "").replace("\u00d7", "*").replace("\u00f7", "/").replace("\u2212", "-")
    text = re.sub(r"(\d+(?:\.\d+)?)\s*%", r"(\1/100)", text)
    return re.sub(r"(?<=[\d)])\s+x\s+(?=[\d(])", " * ", text).strip()


def _check_calculation(line: str, values: list[float], result: Verification) -> None:
    """Check a 'My calculation: <inputs> = <result>' line: inputs traced, arithmetic correct."""
    body = re.sub(r"^\W*my calculation[\s:]*", "", line.strip(), flags=re.IGNORECASE)
    inputs, stated = body.rsplit("=", 1)
    stated = re.split(r"->|\u2192|\u2248|~", stated)[-1]  # "= 71.19556 -> 71.20": the rounded value is what the user reads
    if "=" in inputs:  # "label = 1.5 - 0.5 = 1.0": check the arithmetic after the label
        inputs = inputs.rsplit("=", 1)[1]
    for text, value, tolerance in _checkable_figures(inputs):
        label = text.strip()
        as_percentage = value < 1 and _present(values, value * 100, tolerance * 100)  # 0.4 for "40 percent"
        if label not in result.unverified and not as_percentage and not _present(values, value, tolerance):
            result.unverified.append(label)

    expression = _arithmetic(inputs)
    if expression and not re.fullmatch(r"[\d\s.+\-*/()]+", expression):
        unlabelled = re.sub(r"\([^()\d]*\)", " ", expression)  # "(revenue for Seattle)"
        unlabelled = re.sub(r"[A-Za-z_][A-Za-z_0-9&']*", " ", unlabelled).strip()  # "Seattle units (5) + Kirkland units (6)"
        if re.fullmatch(r"[\d\s.+\-*/()]+", unlabelled) and re.search(r"[+\-*/]", unlabelled):
            expression = unlabelled
    if not expression or not re.fullmatch(r"[\d\s.+\-*/()]+", expression):
        result.issues.append(f"Calculation is not plain arithmetic on numbers: {line.strip()}")
        return
    try:
        computed = _evaluate(expression)
    except (ValueError, SyntaxError, ZeroDivisionError):
        result.issues.append(f"Calculation could not be evaluated: {line.strip()}")
        return
    match = _NUMBER.search(stated)
    if not match:
        result.issues.append(f"Calculation states no result: {line.strip()}")
        return
    suffix = _SUFFIX.match(stated[match.end() :])
    scale = _SCALE.get(suffix.group(1).lower().strip(), 1.0) if suffix else 1.0
    digits = match.group().replace("$", "").replace(",", "").lstrip("-")
    decimals = len(digits.split(".")[1]) if "." in digits else 0
    claimed, tolerance = float(digits) * scale, 0.5 * 10 ** (-decimals) * scale
    if abs(abs(computed) - claimed) > tolerance + 1e-9:
        result.issues.append(
            f"Calculation does not check out (it works out to {abs(computed):,.2f}; "
            f"state that result rounded to the same decimals you gave, or fewer): {line.strip()}"
        )
        return
    insort(values, claimed)  # a confirmed result may be used by later lines


_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")


def _row_numbers(line: str) -> list[float]:
    """Every number in a table row, so a cell can be checked against the other cells in its row."""
    return [abs(float(m.group().replace("$", "").replace(",", ""))) for m in _NUMBER.finditer(_DATE.sub(" ", line))]


def _any_in(values: list[float], low: float, high: float) -> bool:
    index = bisect_left(values, min(low, high) - 1e-9)
    return index < len(values) and values[index] <= max(low, high) + 1e-9


def _derivable(value: float, tolerance: float, row: list[float], evidence: list[float]) -> bool:
    """True if value equals a sum, difference, product, ratio, percentage or percentage change of two numbers.

    One number must come from the same table row. The other comes from the row too, or from a tool result when the
    figure is shown to 2 or more decimals, so a made-up whole number cannot match one by coincidence.
    """
    low, high = value - tolerance, value + tolerance
    use_evidence = tolerance <= 0.005 + 1e-12
    for x in row:
        if x <= 0:
            continue
        intervals = [
            (low - x, high - x),  # x + y
            (x - high, x - low),  # x - y
            (low + x, high + x),  # y - x
            (low / x, high / x),  # x * y
            (low * x, high * x),  # y / x
            (low * x / 100, high * x / 100),  # y as a percentage of x
        ]
        if low > 0:
            intervals += [(x / high, x / low), (100 * x / high, 100 * x / low)]  # x / y and x as a percentage of y
        for sign in (1, -1):  # the checker drops the sign, so a change of -2.78 arrives as 2.78
            v_low, v_high = sorted((sign * low, sign * high))
            if 1 + v_low / 100 > 0:
                intervals.append((x * (1 + v_low / 100), x * (1 + v_high / 100)))  # y is x after a percentage change
                intervals.append((x / (1 + v_high / 100), x / (1 + v_low / 100)))  # percentage change from y to x
        for lo, hi in intervals:
            if lo > hi:
                lo, hi = hi, lo
            if any(lo - 1e-9 <= y <= hi + 1e-9 for y in row if y != x or row.count(x) > 1):
                return True
            if use_evidence and _any_in(evidence, lo, hi):
                return True
    return False


def verify_answer(answer: str, evidence: list[str]) -> Verification:
    """Compare an answer with the tool results it should be based on.

    Every figure must match a number in a tool result or in the user's question, within the
    rounding the answer shows. The agent may show its own arithmetic on a line of the form
    "My calculation: <inputs> = <result>". The inputs are traced like any other figure, the
    arithmetic is recomputed, and a confirmed result may be used by later lines.
    """
    result = Verification()
    values = _evidence_values(evidence)
    lines = answer.splitlines()
    calculations = [ln for ln in lines if _SELF_CALCULATED in ln.lower() and "=" in ln]
    prose = "\n".join(ln for ln in lines if ln not in calculations)

    for line in calculations:
        _check_calculation(line, values, result)

    figures = []
    for line in prose.splitlines():
        row = _row_numbers(line) if _TABLE_ROW.match(line) else None
        for text, value, tolerance in _checkable_figures(line):
            figures.append((text, value, tolerance))
            label = text.strip()
            if label in result.unverified or _present(values, value, tolerance):
                continue
            if row is not None and _derivable(value, tolerance, row, values):
                continue
            result.unverified.append(label)

    joined = "\n".join(evidence)
    if figures and '"scope"' in joined and not re.search(r"^\W*scope:", answer, re.IGNORECASE | re.MULTILINE):
        result.issues.append('The answer has figures but no "Scope:" line.')
    if '"covers_all_stores": false' in joined:
        for sentence in re.split(r"(?<=[.!?])\s+|\n", answer):
            if _NETWORK_CLAIM.search(sentence) and not _NEGATION.search(sentence):
                result.issues.append(
                    "The answer calls a figure a network total, but the tool result says covers_all_stores is false."
                )
                break
    return result
