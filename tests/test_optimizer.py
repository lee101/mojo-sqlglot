import pytest
import sqlglot
from sqlglot.optimizer.simplify import simplify as upstream_simplify

import mojosqlglot as mojo


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 + 2 * 3 AS x FROM t WHERE TRUE AND a = 1",
        "SELECT * FROM t WHERE FALSE OR (a = 1 AND TRUE)",
        "SELECT CASE WHEN FALSE THEN 1 WHEN TRUE THEN 2 ELSE 3 END AS value",
        "SELECT 2 > 1 AS yes, 'a' = 'b' AS no",
        "SELECT (1 + 2) AS n, 2 BETWEEN 1 AND 3 AS inside",
    ],
)
def test_optimizer_matches_upstream_simplify(sql):
    expected = upstream_simplify(sqlglot.parse_one(sql)).sql()
    assert mojo.optimize(sql).sql() == expected


def test_optimizer_does_not_mutate_expression():
    tree = mojo.parse_one("SELECT 1 + 2")
    optimized = mojo.optimize(tree)
    assert tree.sql() == "SELECT 1 + 2"
    assert optimized.sql() == "SELECT 3"


def test_custom_optimizer_rules_are_supported():
    tree = mojo.parse_one("SELECT a FROM t")

    def replace_a(expression, **_):
        for column in expression.find_all(mojo.exp.Column):
            if column.name == "a":
                column.set("parts", [mojo.exp.Identifier("b")])
                column.this = column.args["parts"][-1]
        return expression

    assert mojo.optimize(tree, rules=[replace_a]).sql() == "SELECT b FROM t"
