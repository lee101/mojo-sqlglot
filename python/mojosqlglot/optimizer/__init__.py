"""Deterministic local optimizer for constant and Boolean expressions."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Sequence

from .. import expressions as exp
from ..parser import parse_one


def _number(value: exp.Expression) -> Decimal | None:
    if not isinstance(value, exp.Literal) or value.is_string:
        return None
    try:
        return Decimal(value.this)
    except InvalidOperation:
        return None


def _literal(value: Decimal) -> exp.Literal:
    if value == value.to_integral():
        return exp.Literal.number(str(value.quantize(Decimal(1))))
    return exp.Literal.number(format(value.normalize(), "f"))


def _simplify_node(node: exp.Expression) -> exp.Expression:
    if isinstance(node, exp.Paren):
        return node.this
    if isinstance(node, exp.Unary):
        value = node.this
        op = node.args["op"]
        if op == "NOT" and isinstance(value, exp.Boolean):
            return exp.Boolean(not value.this)
        number = _number(value)
        if number is not None and op in {"+", "-"}:
            return _literal(number if op == "+" else -number)
        return node
    if isinstance(node, exp.Binary):
        left, right, op = node.this, node.expression, node.args["op"]
        if op == "AND":
            if isinstance(left, exp.Boolean):
                return right if left.this else exp.Boolean(False)
            if isinstance(right, exp.Boolean):
                return left if right.this else exp.Boolean(False)
            if left == right:
                return left
        if op == "OR":
            if isinstance(left, exp.Boolean):
                return exp.Boolean(True) if left.this else right
            if isinstance(right, exp.Boolean):
                return exp.Boolean(True) if right.this else left
            if left == right:
                return left
        a, b = _number(left), _number(right)
        if a is not None and b is not None:
            if op == "+":
                return _literal(a + b)
            if op == "-":
                return _literal(a - b)
            if op == "*":
                return _literal(a * b)
            if op in {"=", "<>", "<", "<=", ">", ">="}:
                result = {
                    "=": a == b,
                    "<>": a != b,
                    "<": a < b,
                    "<=": a <= b,
                    ">": a > b,
                    ">=": a >= b,
                }[op]
                return exp.Boolean(result)
        if (
            isinstance(left, exp.Literal)
            and isinstance(right, exp.Literal)
            and left.is_string
            and right.is_string
            and op in {"=", "<>"}
        ):
            return exp.Boolean((left.this == right.this) if op == "=" else (left.this != right.this))
    if isinstance(node, exp.Between):
        value = _number(node.this)
        low = _number(node.args["low"])
        high = _number(node.args["high"])
        if value is not None and low is not None and high is not None:
            result = low <= value <= high
            return exp.Boolean(not result if node.args.get("negated") else result)
    if isinstance(node, exp.Case):
        remaining = []
        for when in node.args["ifs"]:
            condition = when.this
            if isinstance(condition, exp.Boolean):
                if condition.this:
                    return when.expression
                continue
            remaining.append(when)
        if not remaining:
            return node.args.get("default") or exp.Null()
        node.set("ifs", remaining)
    return node


def simplify(expression: exp.Expression) -> exp.Expression:
    return expression.transform(_simplify_node, copy=True)


def optimize(
    expression: str | exp.Expression,
    schema: dict | None = None,
    db: str | exp.Identifier | None = None,
    catalog: str | exp.Identifier | None = None,
    dialect: Any = None,
    rules: Sequence[Callable] | None = None,
    sql: str | None = None,
    **kwargs: Any,
) -> exp.Expression:
    tree = parse_one(expression, read=dialect) if isinstance(expression, str) else expression
    if rules:
        result = tree.copy()
        for rule in rules:
            result = rule(result, schema=schema, dialect=dialect, **kwargs)
        return result
    return simplify(tree)


__all__ = ["optimize", "simplify"]
