"""Recursive-descent SQL parser for SELECT queries and scalar expressions."""

from __future__ import annotations

from typing import Any

from . import expressions as exp
from .errors import ParseError
from .tokens import Token, TokenType, Tokenizer


_SET_OPS = {
    TokenType.UNION: exp.Union,
    TokenType.INTERSECT: exp.Intersect,
    TokenType.EXCEPT: exp.Except,
}
_JOIN_START = {
    TokenType.JOIN,
    TokenType.LEFT,
    TokenType.RIGHT,
    TokenType.FULL,
    TokenType.INNER,
    TokenType.CROSS,
    TokenType.NATURAL,
}
_CLAUSES = {
    TokenType.FROM,
    TokenType.WHERE,
    TokenType.GROUP_BY,
    TokenType.HAVING,
    TokenType.QUALIFY,
    TokenType.ORDER_BY,
    TokenType.LIMIT,
    TokenType.OFFSET,
    TokenType.UNION,
    TokenType.INTERSECT,
    TokenType.EXCEPT,
    TokenType.SEMICOLON,
    TokenType.R_PAREN,
}
_PRECEDENCE = {
    TokenType.OR: 1,
    TokenType.AND: 2,
    TokenType.EQ: 4,
    TokenType.NEQ: 4,
    TokenType.LT: 4,
    TokenType.LTE: 4,
    TokenType.GT: 4,
    TokenType.GTE: 4,
    TokenType.BETWEEN: 4,
    TokenType.IN: 4,
    TokenType.IS: 4,
    TokenType.LIKE: 4,
    TokenType.ILIKE: 4,
    TokenType.DPIPE: 5,
    TokenType.PIPE: 5,
    TokenType.CARET: 5,
    TokenType.AMP: 5,
    TokenType.PLUS: 6,
    TokenType.DASH: 6,
    TokenType.STAR: 7,
    TokenType.SLASH: 7,
    TokenType.MOD: 7,
    TokenType.ARROW: 8,
    TokenType.DARROW: 8,
}
_OP_TEXT = {
    TokenType.EQ: "=",
    TokenType.NEQ: "<>",
    TokenType.LT: "<",
    TokenType.LTE: "<=",
    TokenType.GT: ">",
    TokenType.GTE: ">=",
    TokenType.AND: "AND",
    TokenType.OR: "OR",
    TokenType.DPIPE: "||",
    TokenType.PIPE: "|",
    TokenType.CARET: "^",
    TokenType.AMP: "&",
    TokenType.PLUS: "+",
    TokenType.DASH: "-",
    TokenType.STAR: "*",
    TokenType.SLASH: "/",
    TokenType.MOD: "%",
    TokenType.ARROW: "->",
    TokenType.DARROW: "->>",
}


class Parser:
    def __init__(self, dialect: Any = None, **opts: Any) -> None:
        self.dialect = dialect
        self.opts = opts
        self.tokens: list[Token] = []
        self.i = 0

    @property
    def current(self) -> Token | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def _is(
        self,
        kind: TokenType,
        kind2: TokenType | None = None,
        kind3: TokenType | None = None,
        kind4: TokenType | None = None,
    ) -> bool:
        i = self.i
        if i >= len(self.tokens):
            return False
        token_type = self.tokens[i].token_type
        return (
            token_type is kind
            or token_type is kind2
            or token_type is kind3
            or token_type is kind4
        )

    def _advance(self) -> Token:
        i = self.i
        if i >= len(self.tokens):
            self._error("unexpected end of input")
        self.i = i + 1
        return self.tokens[i]

    def _match(self, kind: TokenType) -> Token | None:
        i = self.i
        if i < len(self.tokens):
            token = self.tokens[i]
            if token.token_type is kind:
                self.i = i + 1
                return token
        return None

    def _expect(self, kind: TokenType, message: str | None = None) -> Token:
        token = self._match(kind)
        if token is None:
            self._error(message or f"expected {kind.name}")
        return token  # type: ignore[return-value]

    def _error(self, message: str) -> None:
        if self.current:
            raise ParseError(
                f"{message} at line {self.current.line}, column {self.current.col}: "
                f"{self.current.raw or self.current.text!r}"
            )
        line = self.tokens[-1].line if self.tokens else 1
        column = self.tokens[-1].col + 1 if self.tokens else 1
        raise ParseError(f"{message} at end of input, line {line}, column {column}")

    def parse(self, sql: str) -> list[exp.Expression | None]:
        self.tokens = Tokenizer(self.dialect).tokenize(sql)
        self.i = 0
        statements: list[exp.Expression | None] = []
        while self.current:
            if self._match(TokenType.SEMICOLON):
                statements.append(None)
                continue
            statements.append(self._parse_query())
            if self.current and not self._match(TokenType.SEMICOLON):
                self._error("unexpected token")
        return statements

    def parse_one(
        self, sql: str, into: type[exp.Expression] | None = None
    ) -> exp.Expression:
        self.tokens = Tokenizer(self.dialect).tokenize(sql)
        self.i = 0
        if into and into is not exp.Select and (
            issubclass(into, exp.Condition) or into is exp.Expression
        ):
            result = self._parse_expression()
        else:
            result = self._parse_query()
        self._match(TokenType.SEMICOLON)
        if self.current:
            self._error("unexpected token")
        if into and into not in (exp.Expression, exp.Condition) and not isinstance(result, into):
            self._error(f"expected {into.__name__}")
        return result

    def _parse_query(self) -> exp.Expression:
        ctes: list[exp.CTE] = []
        recursive = False
        if self._match(TokenType.WITH):
            recursive = bool(self._match(TokenType.RECURSIVE))
            while True:
                alias = self._parse_identifier()
                columns: list[exp.Identifier] = []
                if self._match(TokenType.L_PAREN):
                    columns = self._parse_identifier_list()
                    self._expect(TokenType.R_PAREN)
                self._expect(TokenType.AS)
                self._expect(TokenType.L_PAREN)
                query = self._parse_query()
                self._expect(TokenType.R_PAREN)
                ctes.append(exp.CTE(this=query, alias=alias, columns=columns))
                if not self._match(TokenType.COMMA):
                    break

        query = self._parse_select()
        if ctes:
            query.set("ctes", ctes).set("recursive", recursive)

        while self.current and self.current.token_type in _SET_OPS:
            op_token = self._advance()
            distinct = not bool(self._match(TokenType.ALL))
            self._match(TokenType.DISTINCT)
            right = self._parse_select()
            query = _SET_OPS[op_token.token_type](
                this=query, expression=right, distinct=distinct
            )
        return query

    def _parse_select(self) -> exp.Select:
        self._expect(TokenType.SELECT, "only SELECT queries are supported")
        distinct = bool(self._match(TokenType.DISTINCT))
        top = None
        if self._match(TokenType.TOP):
            top = self._parse_expression(8)

        expressions = [self._parse_select_item()]
        while self._match(TokenType.COMMA):
            expressions.append(self._parse_select_item())
        query = exp.Select(expressions, distinct=distinct)

        if self._match(TokenType.FROM):
            query.set("from_", self._parse_relation())
            joins: list[exp.Join] = []
            while self.current and (
                self.current.token_type in _JOIN_START
                or self.current.token_type is TokenType.COMMA
            ):
                if self._match(TokenType.COMMA):
                    joins.append(exp.Join(this=self._parse_relation(), kind="CROSS", side=""))
                    continue
                joins.append(self._parse_join())
            query.set("joins", joins)
        if self._match(TokenType.WHERE):
            query.set("where", self._parse_expression())
        if self._match(TokenType.GROUP_BY):
            query.set("group", self._parse_csv_expressions())
        if self._match(TokenType.HAVING):
            query.set("having", self._parse_expression())
        if self._match(TokenType.QUALIFY):
            query.set("qualify", self._parse_expression())
        if self._match(TokenType.ORDER_BY):
            orders = [self._parse_order()]
            while self._match(TokenType.COMMA):
                orders.append(self._parse_order())
            query.set("order", orders)
        while self._is(TokenType.LIMIT, TokenType.OFFSET):
            if self._match(TokenType.LIMIT):
                query.set("limit", self._parse_expression(3))
            elif self._match(TokenType.OFFSET):
                query.set("offset", self._parse_expression(3))
        if top is not None and query.args.get("limit") is None:
            query.set("limit", top)
        return query

    def _parse_select_item(self) -> exp.Expression:
        value = self._parse_expression()
        if self._match(TokenType.AS):
            return exp.Alias(value, self._parse_identifier())
        if self._is(TokenType.VAR, TokenType.IDENTIFIER) and not self._is_clause():
            return exp.Alias(value, self._parse_identifier())
        return value

    def _is_clause(self) -> bool:
        i = self.i
        return i >= len(self.tokens) or self.tokens[i].token_type in _CLAUSES

    def _parse_identifier(self) -> exp.Identifier:
        if not self._is(TokenType.VAR, TokenType.IDENTIFIER):
            self._error("expected identifier")
        token = self._advance()
        return exp.Identifier(token.text, quoted=token.quoted)

    def _parse_identifier_list(self) -> list[exp.Identifier]:
        result = [self._parse_identifier()]
        while self._match(TokenType.COMMA):
            result.append(self._parse_identifier())
        return result

    def _parse_relation(self) -> exp.Expression:
        if self._match(TokenType.L_PAREN):
            relation: exp.Expression = exp.Subquery(this=self._parse_query())
            self._expect(TokenType.R_PAREN)
        else:
            parts = [self._parse_identifier()]
            while self._match(TokenType.DOT):
                parts.append(self._parse_identifier())
            relation = exp.Table(parts[-1], parts=parts)
        alias = None
        if self._match(TokenType.AS):
            alias = self._parse_identifier()
        elif self._is(TokenType.VAR, TokenType.IDENTIFIER):
            alias = self._parse_identifier()
        if alias:
            relation.set("alias", alias)
        return relation

    def _parse_join(self) -> exp.Join:
        natural = bool(self._match(TokenType.NATURAL))
        side = ""
        kind = ""
        if self._is(TokenType.LEFT, TokenType.RIGHT, TokenType.FULL):
            side = self._advance().text.upper()
            self._match(TokenType.OUTER)
        elif self._is(TokenType.INNER, TokenType.CROSS):
            kind = self._advance().text.upper()
        self._expect(TokenType.JOIN)
        relation = self._parse_relation()
        on = None
        using: list[exp.Identifier] = []
        if self._match(TokenType.ON):
            on = self._parse_expression()
        elif self._match(TokenType.USING):
            self._expect(TokenType.L_PAREN)
            using = self._parse_identifier_list()
            self._expect(TokenType.R_PAREN)
        return exp.Join(
            this=relation,
            side=side,
            kind=kind,
            natural=natural,
            on=on,
            using=using,
        )

    def _parse_order(self) -> exp.Order:
        value = self._parse_expression()
        desc = bool(self._match(TokenType.DESC))
        if not desc:
            self._match(TokenType.ASC)
        nulls = None
        if self._match(TokenType.NULLS):
            if self._match(TokenType.FIRST):
                nulls = "FIRST"
            elif self._match(TokenType.LAST):
                nulls = "LAST"
            else:
                self._error("expected FIRST or LAST")
        return exp.Order(this=value, desc=desc, nulls=nulls)

    def _parse_csv_expressions(self) -> list[exp.Expression]:
        result = [self._parse_expression()]
        while self._match(TokenType.COMMA):
            result.append(self._parse_expression())
        return result

    def _parse_expression(self, min_precedence: int = 0) -> exp.Expression:
        left = self._parse_unary()
        while self.current:
            token_type = self.current.token_type
            negated = False
            if (
                token_type is TokenType.NOT
                and self.i + 1 < len(self.tokens)
                and self.tokens[self.i + 1].token_type
                in {TokenType.BETWEEN, TokenType.IN, TokenType.LIKE, TokenType.ILIKE}
            ):
                token_type = self.tokens[self.i + 1].token_type
                negated = True
            precedence = _PRECEDENCE.get(token_type, -1)
            if precedence < min_precedence:
                break
            self._advance()
            if negated:
                self._advance()
            if token_type is TokenType.BETWEEN:
                low = self._parse_expression(precedence + 1)
                self._expect(TokenType.AND)
                high = self._parse_expression(precedence + 1)
                left = exp.Between(this=left, low=low, high=high, negated=negated)
                continue
            if token_type is TokenType.IN:
                self._expect(TokenType.L_PAREN)
                if self._is(TokenType.SELECT, TokenType.WITH):
                    values: exp.Expression | list[exp.Expression] = self._parse_query()
                elif self._match(TokenType.R_PAREN):
                    values = []
                    left = exp.In(this=left, expressions=values, negated=negated)
                    continue
                else:
                    values = self._parse_csv_expressions()
                self._expect(TokenType.R_PAREN)
                left = (
                    exp.In(this=left, query=values, expressions=[], negated=negated)
                    if isinstance(values, exp.Query)
                    else exp.In(this=left, expressions=values, negated=negated)
                )
                continue
            if token_type is TokenType.IS:
                negated = bool(self._match(TokenType.NOT))
                right = self._parse_expression(precedence + 1)
                left = exp.Is(this=left, expression=right, negated=negated)
                continue
            if token_type in (TokenType.LIKE, TokenType.ILIKE):
                right = self._parse_expression(precedence + 1)
                left = exp.Like(
                    this=left,
                    expression=right,
                    insensitive=token_type is TokenType.ILIKE,
                    negated=negated,
                )
                continue
            right = self._parse_expression(precedence + 1)
            left = exp.Binary(left, right, _OP_TEXT[token_type])
        return left

    def _parse_unary(self) -> exp.Expression:
        if self._is(TokenType.NOT, TokenType.PLUS, TokenType.DASH, TokenType.TILDE):
            token = self._advance()
            op = {
                TokenType.NOT: "NOT",
                TokenType.PLUS: "+",
                TokenType.DASH: "-",
                TokenType.TILDE: "~",
            }[token.token_type]
            return exp.Unary(self._parse_unary(), op)
        if self._match(TokenType.EXISTS):
            self._expect(TokenType.L_PAREN)
            query = self._parse_query()
            self._expect(TokenType.R_PAREN)
            return exp.Unary(exp.Subquery(this=query), "EXISTS")
        value = self._parse_atom()
        while True:
            if self._match(TokenType.DCOLON):
                value = exp.Cast(this=value, to=self._parse_data_type(), safe=False)
            elif self._match(TokenType.OVER):
                self._expect(TokenType.L_PAREN)
                partition: list[exp.Expression] = []
                order: list[exp.Order] = []
                if self._match(TokenType.PARTITION_BY):
                    partition = self._parse_csv_expressions()
                if self._match(TokenType.ORDER_BY):
                    order = [self._parse_order()]
                    while self._match(TokenType.COMMA):
                        order.append(self._parse_order())
                self._expect(TokenType.R_PAREN)
                value = exp.Window(this=value, partition=partition, order=order)
            else:
                break
        return value

    def _parse_atom(self) -> exp.Expression:
        token = self.current
        if token is None:
            self._error("expected expression")
        if self._match(TokenType.L_PAREN):
            if self._is(TokenType.SELECT, TokenType.WITH):
                value: exp.Expression = exp.Subquery(this=self._parse_query())
            else:
                first = self._parse_expression()
                if self._match(TokenType.COMMA):
                    values = [first, self._parse_expression()]
                    while self._match(TokenType.COMMA):
                        values.append(self._parse_expression())
                    value = exp.Tuple(expressions=values)
                else:
                    value = exp.Paren(this=first)
            self._expect(TokenType.R_PAREN)
            return value
        if self._is(TokenType.NUMBER):
            return exp.Literal.number(self._advance().text)
        if self._is(TokenType.STRING):
            return exp.Literal.string(self._advance().text)
        if self._match(TokenType.NULL):
            return exp.Null()
        if self._match(TokenType.TRUE):
            return exp.Boolean(True)
        if self._match(TokenType.FALSE):
            return exp.Boolean(False)
        if self._match(TokenType.STAR):
            return exp.Star()
        if self._is(TokenType.PLACEHOLDER, TokenType.COLON):
            value = self._advance()
            return exp.Parameter(this=value.raw)
        if self._match(TokenType.CASE):
            return self._parse_case()
        if self._is(TokenType.CAST, TokenType.TRY_CAST):
            safe = self._advance().token_type is TokenType.TRY_CAST
            self._expect(TokenType.L_PAREN)
            value = self._parse_expression()
            self._expect(TokenType.AS)
            data_type = self._parse_data_type()
            self._expect(TokenType.R_PAREN)
            return exp.Cast(this=value, to=data_type, safe=safe)
        if not self._is(TokenType.VAR, TokenType.IDENTIFIER):
            self._error("expected expression")
        parts = [self._parse_identifier()]
        while self._match(TokenType.DOT):
            if self._match(TokenType.STAR):
                return exp.Star(table=parts)
            parts.append(self._parse_identifier())
        if self._match(TokenType.L_PAREN):
            distinct = bool(self._match(TokenType.DISTINCT))
            args: list[exp.Expression] = []
            if not self._match(TokenType.R_PAREN):
                args = self._parse_csv_expressions()
                self._expect(TokenType.R_PAREN)
            return exp.Func(parts[-1], args, distinct=distinct)
        return exp.Column(parts[-1], parts=parts)

    def _parse_case(self) -> exp.Case:
        base = None
        if not self._is(TokenType.WHEN):
            base = self._parse_expression()
        whens: list[exp.When] = []
        while self._match(TokenType.WHEN):
            condition = self._parse_expression()
            self._expect(TokenType.THEN)
            value = self._parse_expression()
            whens.append(exp.When(this=condition, expression=value))
        default = None
        if self._match(TokenType.ELSE):
            default = self._parse_expression()
        self._expect(TokenType.END)
        return exp.Case(this=base, ifs=whens, default=default)

    def _parse_data_type(self) -> exp.DataType:
        if not self._is(TokenType.VAR, TokenType.IDENTIFIER):
            self._error("expected data type")
        name = self._advance().text
        params: list[exp.Expression] = []
        if self._match(TokenType.L_PAREN):
            params = self._parse_csv_expressions()
            self._expect(TokenType.R_PAREN)
        return exp.DataType(name, params)


def parse(
    sql: str,
    read: Any = None,
    dialect: Any = None,
    **opts: Any,
) -> list[exp.Expression | None]:
    return Parser(dialect=read or dialect, **opts).parse(sql)


def parse_one(
    sql: str,
    read: Any = None,
    dialect: Any = None,
    into: type[exp.Expression] | None = None,
    **opts: Any,
) -> exp.Expression:
    return Parser(dialect=read or dialect, **opts).parse_one(sql, into=into)
