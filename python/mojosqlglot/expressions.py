"""Small, composable expression tree for the covered SQL grammar."""

from __future__ import annotations

import copy
from collections import deque
from typing import Any, Callable, Iterator, TypeVar

E = TypeVar("E", bound="Expression")


class Expression:
    key = "expression"

    def __init__(self, **args: Any) -> None:
        self.args = args
        self.parent: Expression | None = None
        self._set_parents()

    def _set_parents(self) -> None:
        for value in self.args.values():
            if isinstance(value, Expression):
                value.parent = self
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, Expression):
                        item.parent = self

    @property
    def this(self) -> Any:
        return self.args.get("this")

    @this.setter
    def this(self, value: Any) -> None:
        self.set("this", value)

    @property
    def expression(self) -> Any:
        return self.args.get("expression")

    @property
    def expressions(self) -> list[Expression]:
        return self.args.get("expressions") or []

    @property
    def name(self) -> str:
        value = self.this
        if isinstance(value, Identifier):
            return value.name
        return str(value) if value is not None else ""

    @property
    def alias(self) -> str:
        value = self.args.get("alias")
        return value.name if isinstance(value, Identifier) else ""

    @property
    def alias_or_name(self) -> str:
        return self.alias or self.name

    def set(self, arg_key: str, value: Any) -> Expression:
        self.args[arg_key] = value
        if isinstance(value, Expression):
            value.parent = self
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, Expression):
                    item.parent = self
        return self

    def append(self, arg_key: str, value: Expression) -> Expression:
        self.args.setdefault(arg_key, []).append(value)
        value.parent = self
        return self

    def copy(self: E) -> E:
        result = copy.deepcopy(self)
        result.parent = None
        result._set_parents()
        return result

    def walk(self) -> Iterator[Expression]:
        queue = deque([self])
        while queue:
            node = queue.popleft()
            yield node
            for value in node.args.values():
                if isinstance(value, Expression):
                    queue.append(value)
                elif isinstance(value, list):
                    queue.extend(item for item in value if isinstance(item, Expression))

    def find_all(self, *expression_types: type[E]) -> Iterator[E]:
        for node in self.walk():
            if isinstance(node, expression_types):
                yield node

    def find(self, *expression_types: type[E]) -> E | None:
        return next(self.find_all(*expression_types), None)

    def transform(
        self: E, fun: Callable[[Expression], Expression], copy: bool = True
    ) -> E:
        root: Expression = self.copy() if copy else self

        def visit(node: Expression) -> Expression:
            for key, value in list(node.args.items()):
                if isinstance(value, Expression):
                    node.args[key] = visit(value)
                elif isinstance(value, list):
                    node.args[key] = [
                        visit(item) if isinstance(item, Expression) else item for item in value
                    ]
            replaced = fun(node)
            replaced._set_parents()
            return replaced

        result = visit(root)
        result.parent = None
        return result  # type: ignore[return-value]

    def sql(self, dialect: Any = None, **opts: Any) -> str:
        from .generator import Generator

        return Generator(dialect=dialect, **opts).generate(self)

    def as_(self, alias: str, quoted: bool = False) -> Alias:
        return Alias(this=self, alias=Identifier(alias, quoted=quoted))

    def dump(self) -> dict[str, Any]:
        def encode(value: Any) -> Any:
            if isinstance(value, Expression):
                return value.dump()
            if isinstance(value, list):
                return [encode(item) for item in value]
            return value

        return {"class": type(self).__name__, "args": {k: encode(v) for k, v in self.args.items()}}

    def __str__(self) -> str:
        return self.sql()

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.args!r})"

    def __eq__(self, other: object) -> bool:
        return type(self) is type(other) and self.args == other.args


class Query(Expression):
    key = "query"


class Select(Query):
    key = "select"

    def __init__(self, expressions: list[Expression] | None = None, **args: Any) -> None:
        super().__init__(expressions=expressions or [], **args)

    def from_(self, expression: str | Expression) -> Select:
        self.set("from_", to_table(expression) if isinstance(expression, str) else expression)
        return self

    def where(self, expression: str | Expression) -> Select:
        from .parser import parse_one

        self.set(
            "where",
            parse_one(expression, into=Condition) if isinstance(expression, str) else expression,
        )
        return self

    def select(self, *expressions: str | Expression, append: bool = True) -> Select:
        from .parser import parse_one

        parsed = [
            parse_one(value, into=Condition) if isinstance(value, str) else value
            for value in expressions
        ]
        self.set("expressions", self.expressions + parsed if append else parsed)
        return self


class SetOperation(Query):
    pass


class Union(SetOperation):
    key = "union"


class Intersect(SetOperation):
    key = "intersect"


class Except(SetOperation):
    key = "except"


class Identifier(Expression):
    key = "identifier"

    def __init__(self, this: str, quoted: bool = False) -> None:
        super().__init__(this=this, quoted=quoted)

    @property
    def name(self) -> str:
        return self.this


class Column(Expression):
    key = "column"

    def __init__(self, this: Identifier, parts: list[Identifier] | None = None) -> None:
        super().__init__(this=this, parts=parts or [this])

    @property
    def parts(self) -> list[Identifier]:
        return self.args["parts"]

    @property
    def this(self) -> Identifier:
        return self.args["this"]

    @this.setter
    def this(self, value: Identifier) -> None:
        self.args["this"] = value
        if self.args.get("parts"):
            self.args["parts"][-1] = value
        self._set_parents()

    @property
    def table(self) -> str:
        return self.parts[-2].name if len(self.parts) > 1 else ""

    @property
    def name(self) -> str:
        return self.parts[-1].name


class Table(Expression):
    key = "table"

    def __init__(
        self,
        this: Identifier,
        parts: list[Identifier] | None = None,
        alias: Identifier | None = None,
    ) -> None:
        super().__init__(this=this, parts=parts or [this], alias=alias)

    @property
    def parts(self) -> list[Identifier]:
        return self.args["parts"]

    @property
    def this(self) -> Identifier:
        return self.args["this"]

    @this.setter
    def this(self, value: Identifier) -> None:
        self.args["this"] = value
        if self.args.get("parts"):
            self.args["parts"][-1] = value
        self._set_parents()

    @property
    def name(self) -> str:
        return self.parts[-1].name


class Star(Expression):
    key = "star"

    def __init__(self, table: list[Identifier] | None = None) -> None:
        super().__init__(table=table or [])


class Literal(Expression):
    key = "literal"

    def __init__(self, this: str, is_string: bool = False) -> None:
        super().__init__(this=this, is_string=is_string)

    @classmethod
    def number(cls, value: str | int | float) -> Literal:
        return cls(str(value), is_string=False)

    @classmethod
    def string(cls, value: str) -> Literal:
        return cls(value, is_string=True)

    @property
    def is_string(self) -> bool:
        return bool(self.args["is_string"])


class Boolean(Expression):
    key = "boolean"

    def __init__(self, this: bool) -> None:
        super().__init__(this=this)


class Null(Expression):
    key = "null"

    def __init__(self) -> None:
        super().__init__()


class Parameter(Expression):
    key = "parameter"


class Alias(Expression):
    key = "alias"

    def __init__(self, this: Expression, alias: Identifier) -> None:
        super().__init__(this=this, alias=alias)


class Condition(Expression):
    key = "condition"


class Binary(Condition):
    key = "binary"

    def __init__(self, this: Expression, expression: Expression, op: str) -> None:
        super().__init__(this=this, expression=expression, op=op)


class Unary(Condition):
    key = "unary"

    def __init__(self, this: Expression, op: str) -> None:
        super().__init__(this=this, op=op)


class Between(Condition):
    key = "between"


class In(Condition):
    key = "in"


class Is(Condition):
    key = "is"


class Like(Condition):
    key = "like"


class Func(Expression):
    key = "func"

    def __init__(
        self,
        this: Identifier,
        expressions: list[Expression] | None = None,
        distinct: bool = False,
    ) -> None:
        super().__init__(this=this, expressions=expressions or [], distinct=distinct)

    @property
    def name(self) -> str:
        return self.this.name


class Cast(Expression):
    key = "cast"


class DataType(Expression):
    key = "datatype"

    def __init__(self, this: str, expressions: list[Expression] | None = None) -> None:
        super().__init__(this=this.upper(), expressions=expressions or [])


class Case(Expression):
    key = "case"


class When(Expression):
    key = "when"


class Tuple(Expression):
    key = "tuple"


class Paren(Expression):
    key = "paren"


class Subquery(Query):
    key = "subquery"


class CTE(Expression):
    key = "cte"


class Join(Expression):
    key = "join"


class Order(Expression):
    key = "order"


class Window(Expression):
    key = "window"


def to_identifier(name: str | Identifier, quoted: bool = False) -> Identifier:
    return name if isinstance(name, Identifier) else Identifier(name, quoted=quoted)


def to_column(name: str) -> Column:
    parts = [Identifier(part) for part in name.split(".")]
    return Column(parts[-1], parts=parts)


def to_table(name: str) -> Table:
    parts = [Identifier(part) for part in name.split(".")]
    return Table(parts[-1], parts=parts)


def column(name: str, table: str | None = None, quoted: bool = False) -> Column:
    parts = []
    if table:
        parts.extend(Identifier(part, quoted=quoted) for part in table.split("."))
    parts.append(Identifier(name, quoted=quoted))
    return Column(parts[-1], parts=parts)


def table_(name: str, db: str | None = None, catalog: str | None = None) -> Table:
    parts = [Identifier(part) for part in (catalog, db, name) if part]
    return Table(parts[-1], parts=parts)


def select(*expressions: str | Expression) -> Select:
    query = Select()
    return query.select(*expressions)


def func(name: str, *args: Expression | str | int | float) -> Func:
    values: list[Expression] = []
    for value in args:
        if isinstance(value, Expression):
            values.append(value)
        elif isinstance(value, str):
            values.append(to_column(value))
        else:
            values.append(Literal.number(value))
    return Func(Identifier(name), values)


def alias_(expression: Expression | str, alias: str, quoted: bool = False) -> Alias:
    value = to_column(expression) if isinstance(expression, str) else expression
    return Alias(value, Identifier(alias, quoted=quoted))


def and_(*expressions: Expression) -> Expression:
    if not expressions:
        return Boolean(True)
    result = expressions[0]
    for expression in expressions[1:]:
        result = Binary(result, expression, "AND")
    return result


def or_(*expressions: Expression) -> Expression:
    if not expressions:
        return Boolean(False)
    result = expressions[0]
    for expression in expressions[1:]:
        result = Binary(result, expression, "OR")
    return result


def not_(expression: Expression) -> Unary:
    return Unary(expression, "NOT")
