"""Canonical and pretty SQL generation for the expression tree."""

from __future__ import annotations

from typing import Any

from . import expressions as exp


_PRECEDENCE = {
    "OR": 1,
    "AND": 2,
    "=": 4,
    "<>": 4,
    "<": 4,
    "<=": 4,
    ">": 4,
    ">=": 4,
    "||": 5,
    "|": 5,
    "^": 5,
    "&": 5,
    "+": 6,
    "-": 6,
    "*": 7,
    "/": 7,
    "%": 7,
    "->": 8,
    "->>": 8,
}


class Generator:
    def __init__(
        self,
        dialect: Any = None,
        pretty: bool = False,
        identify: bool = False,
        normalize: bool = False,
        comments: bool = True,
        **opts: Any,
    ) -> None:
        self.dialect = str(dialect or "").lower()
        self.pretty = pretty
        self.identify = identify
        self.normalize = normalize
        self.comments = comments
        self.opts = opts

    def generate(self, expression: exp.Expression) -> str:
        if self.pretty and isinstance(expression, (exp.Query, exp.SetOperation)):
            return self._pretty_query(expression)
        return self.sql(expression)

    def sql(self, expression: exp.Expression, parent_precedence: int = 0) -> str:
        method = getattr(self, f"_{expression.key}", None)
        if method is None:
            raise TypeError(f"unsupported expression {type(expression).__name__}")
        return method(expression, parent_precedence)

    def _identifier(self, expression: exp.Identifier, _: int = 0) -> str:
        name = expression.name.lower() if self.normalize else expression.name
        quoted = expression.args.get("quoted") or self.identify
        if not quoted:
            return name
        quote = "`" if self.dialect in {"mysql", "hive", "spark", "spark2"} else '"'
        return quote + name.replace(quote, quote + quote) + quote

    def _column(self, expression: exp.Column, _: int = 0) -> str:
        return ".".join(self.sql(part) for part in expression.parts)

    def _table(self, expression: exp.Table, _: int = 0) -> str:
        sql = ".".join(self.sql(part) for part in expression.parts)
        alias = expression.args.get("alias")
        return f"{sql} AS {self.sql(alias)}" if alias else sql

    def _star(self, expression: exp.Star, _: int = 0) -> str:
        table = expression.args.get("table") or []
        return (".".join(self.sql(part) for part in table) + "." if table else "") + "*"

    def _literal(self, expression: exp.Literal, _: int = 0) -> str:
        if expression.is_string:
            return "'" + expression.this.replace("'", "''") + "'"
        return expression.this

    def _boolean(self, expression: exp.Boolean, _: int = 0) -> str:
        return "TRUE" if expression.this else "FALSE"

    def _null(self, expression: exp.Null, _: int = 0) -> str:
        return "NULL"

    def _parameter(self, expression: exp.Parameter, _: int = 0) -> str:
        return expression.this

    def _alias(self, expression: exp.Alias, _: int = 0) -> str:
        return f"{self.sql(expression.this)} AS {self.sql(expression.args['alias'])}"

    def _binary(self, expression: exp.Binary, parent_precedence: int = 0) -> str:
        op = expression.args["op"]
        precedence = _PRECEDENCE[op]
        sql = (
            f"{self.sql(expression.this, precedence)} {op} "
            f"{self.sql(expression.expression, precedence + 1)}"
        )
        return f"({sql})" if precedence < parent_precedence else sql

    def _unary(self, expression: exp.Unary, parent_precedence: int = 0) -> str:
        op = expression.args["op"]
        value = self.sql(expression.this, 3)
        sql = f"{op} {value}" if op in {"NOT", "EXISTS"} else f"{op}{value}"
        return f"({sql})" if parent_precedence > 3 else sql

    def _between(self, expression: exp.Between, parent_precedence: int = 0) -> str:
        prefix = "NOT " if expression.args.get("negated") else ""
        sql = (
            f"{self.sql(expression.this, 4)} {prefix}BETWEEN "
            f"{self.sql(expression.args['low'], 5)} AND {self.sql(expression.args['high'], 5)}"
        )
        return f"({sql})" if parent_precedence > 4 else sql

    def _in(self, expression: exp.In, parent_precedence: int = 0) -> str:
        if expression.args.get("query") is not None:
            inside = self.sql(expression.args["query"])
        else:
            inside = ", ".join(self.sql(value) for value in expression.expressions)
        left = self.sql(expression.this, 4)
        sql = (
            f"NOT {left} IN ({inside})"
            if expression.args.get("negated")
            else f"{left} IN ({inside})"
        )
        return f"({sql})" if parent_precedence > 4 else sql

    def _is(self, expression: exp.Is, parent_precedence: int = 0) -> str:
        left = self.sql(expression.this, 4)
        right = self.sql(expression.expression, 5)
        sql = f"NOT {left} IS {right}" if expression.args.get("negated") else f"{left} IS {right}"
        return f"({sql})" if parent_precedence > 4 else sql

    def _like(self, expression: exp.Like, parent_precedence: int = 0) -> str:
        op = "ILIKE" if expression.args.get("insensitive") else "LIKE"
        if expression.args.get("negated"):
            op = "NOT " + op
        sql = f"{self.sql(expression.this, 4)} {op} {self.sql(expression.expression, 5)}"
        return f"({sql})" if parent_precedence > 4 else sql

    def _func(self, expression: exp.Func, _: int = 0) -> str:
        name = expression.name.upper()
        args = expression.expressions
        if name == "IF" and self.dialect in {"postgres", "postgresql"} and len(args) == 3:
            return (
                f"CASE WHEN {self.sql(args[0])} THEN {self.sql(args[1])} "
                f"ELSE {self.sql(args[2])} END"
            )
        if name in {"APPROX_DISTINCT", "APPROX_COUNT_DISTINCT"}:
            name = "APPROX_COUNT_DISTINCT" if self.dialect in {"spark", "spark2"} else name
        if name == "EPOCH_MS" and self.dialect in {"hive", "spark", "spark2"} and len(args) == 1:
            value = self.sql(args[0])
            return f"FROM_UNIXTIME({value} / POW(10, 3))"
        prefix = "DISTINCT " if expression.args.get("distinct") else ""
        return f"{name}({prefix}{', '.join(self.sql(arg) for arg in args)})"

    def _cast(self, expression: exp.Cast, _: int = 0) -> str:
        name = "TRY_CAST" if expression.args.get("safe") else "CAST"
        data_type = expression.args["to"]
        if self.dialect == "mysql" and data_type.this in {"INT", "INTEGER", "BIGINT"}:
            type_sql = "SIGNED"
        else:
            type_sql = self.sql(data_type)
        return f"{name}({self.sql(expression.this)} AS {type_sql})"

    def _datatype(self, expression: exp.DataType, _: int = 0) -> str:
        name = expression.this
        if self.dialect in {"postgres", "postgresql"} and name == "DATETIME":
            name = "TIMESTAMP"
        params = expression.expressions
        return f"{name}({', '.join(self.sql(v) for v in params)})" if params else name

    def _case(self, expression: exp.Case, _: int = 0) -> str:
        chunks = ["CASE"]
        if expression.this is not None:
            chunks.append(" " + self.sql(expression.this))
        for when in expression.args["ifs"]:
            chunks.append(" " + self.sql(when))
        if expression.args.get("default") is not None:
            chunks.append(" ELSE " + self.sql(expression.args["default"]))
        chunks.append(" END")
        return "".join(chunks)

    def _when(self, expression: exp.When, _: int = 0) -> str:
        return f"WHEN {self.sql(expression.this)} THEN {self.sql(expression.expression)}"

    def _tuple(self, expression: exp.Tuple, _: int = 0) -> str:
        return f"({', '.join(self.sql(value) for value in expression.expressions)})"

    def _paren(self, expression: exp.Paren, _: int = 0) -> str:
        return f"({self.sql(expression.this)})"

    def _subquery(self, expression: exp.Subquery, _: int = 0) -> str:
        sql = f"({self.sql(expression.this)})"
        alias = expression.args.get("alias")
        return f"{sql} AS {self.sql(alias)}" if alias else sql

    def _cte(self, expression: exp.CTE, _: int = 0) -> str:
        alias = self.sql(expression.args["alias"])
        columns = expression.args.get("columns") or []
        if columns:
            alias += f" ({', '.join(self.sql(value) for value in columns)})"
        return f"{alias} AS ({self.sql(expression.this)})"

    def _join(self, expression: exp.Join, _: int = 0) -> str:
        chunks = []
        if expression.args.get("natural"):
            chunks.append("NATURAL")
        if expression.args.get("side"):
            chunks.append(expression.args["side"])
        if expression.args.get("kind"):
            chunks.append(expression.args["kind"])
        chunks.append("JOIN")
        chunks.append(self.sql(expression.this))
        sql = " ".join(chunks)
        if expression.args.get("on") is not None:
            sql += " ON " + self.sql(expression.args["on"])
        elif expression.args.get("using"):
            sql += " USING (" + ", ".join(self.sql(v) for v in expression.args["using"]) + ")"
        return sql

    def _order(self, expression: exp.Order, _: int = 0) -> str:
        sql = self.sql(expression.this)
        if expression.args.get("desc"):
            sql += " DESC"
        if expression.args.get("nulls"):
            sql += " NULLS " + expression.args["nulls"]
        return sql

    def _window(self, expression: exp.Window, _: int = 0) -> str:
        clauses = []
        if expression.args.get("partition"):
            clauses.append(
                "PARTITION BY "
                + ", ".join(self.sql(value) for value in expression.args["partition"])
            )
        if expression.args.get("order"):
            clauses.append(
                "ORDER BY " + ", ".join(self.sql(value) for value in expression.args["order"])
            )
        return f"{self.sql(expression.this)} OVER ({' '.join(clauses)})"

    def _select(self, expression: exp.Select, _: int = 0) -> str:
        ctes = expression.args.get("ctes") or []
        prefix = ""
        if ctes:
            recursive = " RECURSIVE" if expression.args.get("recursive") else ""
            prefix = f"WITH{recursive} " + ", ".join(self.sql(cte) for cte in ctes) + " "
        distinct = " DISTINCT" if expression.args.get("distinct") else ""
        limit = expression.args.get("limit")
        top = ""
        if self.dialect in {"tsql", "mssql"} and limit is not None:
            top = f" TOP {self.sql(limit)}"
        sql = (
            f"{prefix}SELECT{distinct}{top} "
            + ", ".join(self.sql(value) for value in expression.expressions)
        )
        if expression.args.get("from_") is not None:
            sql += " FROM " + self.sql(expression.args["from_"])
        joins = expression.args.get("joins") or []
        if joins:
            sql += " " + " ".join(self.sql(join) for join in joins)
        if expression.args.get("where") is not None:
            sql += " WHERE " + self.sql(expression.args["where"])
        if expression.args.get("group"):
            sql += " GROUP BY " + ", ".join(self.sql(value) for value in expression.args["group"])
        if expression.args.get("having") is not None:
            sql += " HAVING " + self.sql(expression.args["having"])
        if expression.args.get("qualify") is not None:
            sql += " QUALIFY " + self.sql(expression.args["qualify"])
        if expression.args.get("order"):
            sql += " ORDER BY " + ", ".join(self.sql(value) for value in expression.args["order"])
        if limit is not None and self.dialect not in {"tsql", "mssql"}:
            sql += " LIMIT " + self.sql(limit)
        if expression.args.get("offset") is not None:
            sql += " OFFSET " + self.sql(expression.args["offset"])
        return sql

    def _set_operation(self, expression: exp.SetOperation, keyword: str) -> str:
        modifier = "" if expression.args.get("distinct", True) else " ALL"
        return f"{self.sql(expression.this)} {keyword}{modifier} {self.sql(expression.expression)}"

    def _union(self, expression: exp.Union, _: int = 0) -> str:
        return self._set_operation(expression, "UNION")

    def _intersect(self, expression: exp.Intersect, _: int = 0) -> str:
        return self._set_operation(expression, "INTERSECT")

    def _except(self, expression: exp.Except, _: int = 0) -> str:
        return self._set_operation(expression, "EXCEPT")

    def _pretty_query(self, expression: exp.Expression, indent: int = 0) -> str:
        if isinstance(expression, exp.SetOperation):
            keyword = expression.key.upper()
            modifier = "" if expression.args.get("distinct", True) else " ALL"
            return (
                self._pretty_query(expression.this, indent)
                + f"\n{keyword}{modifier}\n"
                + self._pretty_query(expression.expression, indent)
            )
        if not isinstance(expression, exp.Select):
            return self.sql(expression)
        pad = " " * indent
        lines: list[str] = []
        ctes = expression.args.get("ctes") or []
        if ctes:
            recursive = " RECURSIVE" if expression.args.get("recursive") else ""
            lines.append(pad + "WITH" + recursive + " " + self.sql(ctes[0]))
            for cte in ctes[1:]:
                lines[-1] += ","
                lines.append(pad + self.sql(cte))
        head = "SELECT DISTINCT" if expression.args.get("distinct") else "SELECT"
        lines.append(pad + head)
        for index, value in enumerate(expression.expressions):
            suffix = "," if index + 1 < len(expression.expressions) else ""
            lines.append(pad + "  " + self.sql(value) + suffix)
        if expression.args.get("from_") is not None:
            lines.append(pad + "FROM " + self.sql(expression.args["from_"]))
        for join in expression.args.get("joins") or []:
            text = self.sql(join)
            if " ON " in text:
                relation, condition = text.split(" ON ", 1)
                lines.extend([pad + relation, pad + "  ON " + condition])
            else:
                lines.append(pad + text)
        for key, keyword in (
            ("where", "WHERE"),
            ("group", "GROUP BY"),
            ("having", "HAVING"),
            ("qualify", "QUALIFY"),
            ("order", "ORDER BY"),
        ):
            value = expression.args.get(key)
            if value is None or value == []:
                continue
            lines.append(pad + keyword)
            values = value if isinstance(value, list) else [value]
            for index, item in enumerate(values):
                suffix = "," if index + 1 < len(values) else ""
                lines.append(pad + "  " + self.sql(item) + suffix)
        if expression.args.get("limit") is not None:
            lines.append(pad + "LIMIT " + self.sql(expression.args["limit"]))
        if expression.args.get("offset") is not None:
            lines.append(pad + "OFFSET " + self.sql(expression.args["offset"]))
        return "\n".join(lines)
