"""SQL parsing, transpilation, and local optimization with a Mojo tokenizer."""

from __future__ import annotations

from typing import Any

from . import expressions as exp
from .errors import ParseError, SqlglotError, UnsupportedError
from .expressions import Expression
from .optimizer import optimize
from .parser import Parser, parse, parse_one
from .tokens import Token, TokenType, Tokenizer

__version__ = "0.1.0"


def transpile(
    sql: str,
    read: Any = None,
    write: Any = None,
    identity: bool = True,
    error_level: Any = None,
    **opts: Any,
) -> list[str]:
    generator_opts = {
        key: opts.pop(key)
        for key in list(opts)
        if key in {"pretty", "identify", "normalize", "comments"}
    }
    return [
        expression.sql(dialect=write or (read if identity else None), **generator_opts)
        for expression in parse(sql, read=read, **opts)
        if expression is not None
    ]


def condition(expression: str, dialect: Any = None, **opts: Any) -> Expression:
    return parse_one(expression, dialect=dialect, into=exp.Condition, **opts)


def maybe_parse(
    sql_or_expression: str | Expression,
    *,
    into: type[Expression] | None = None,
    dialect: Any = None,
    **opts: Any,
) -> Expression:
    if isinstance(sql_or_expression, Expression):
        return sql_or_expression
    return parse_one(sql_or_expression, dialect=dialect, into=into, **opts)


__all__ = [
    "Expression",
    "ParseError",
    "Parser",
    "SqlglotError",
    "Token",
    "TokenType",
    "Tokenizer",
    "UnsupportedError",
    "condition",
    "exp",
    "maybe_parse",
    "optimize",
    "parse",
    "parse_one",
    "transpile",
]
