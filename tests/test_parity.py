import pytest
import sqlglot as upstream

import mojosqlglot as mojo
from mojosqlglot import exp


QUERIES = [
    "select a,b+1 as c from db.t x where a>=10 and b!='x' order by c desc limit 5",
    "SELECT DISTINCT department, COUNT(*) AS n FROM employees GROUP BY department HAVING COUNT(*) > 1",
    "WITH recent AS (SELECT id, created_at FROM events WHERE created_at >= '2025-01-01') SELECT * FROM recent",
    "SELECT CASE WHEN score >= 90 THEN 'A' ELSE 'B' END AS grade FROM exams",
    "SELECT CAST(price AS DECIMAL(10, 2)) FROM products",
    "SELECT * FROM a LEFT JOIN b ON a.id = b.a_id",
    "SELECT x FROM t WHERE x BETWEEN 1 AND 10 AND y IN (1, 2, 3) AND z IS NOT NULL",
    "SELECT a FROM t UNION ALL SELECT a FROM u",
    "SELECT ROW_NUMBER() OVER (PARTITION BY department ORDER BY salary DESC) AS n FROM employees",
    "SELECT * FROM a INNER JOIN b USING (id) CROSS JOIN c",
    "SELECT x FROM t WHERE x NOT IN (1, 2) OR name ILIKE 'a%'",
    "SELECT (a + b) * c AS result, t.* FROM t OFFSET 3 LIMIT 10",
]


@pytest.mark.parametrize("sql", QUERIES)
def test_parse_and_generate_matches_upstream(sql):
    assert mojo.parse_one(sql).sql() == upstream.parse_one(sql).sql()


def test_parse_multiple_statements_matches_upstream():
    sql = "SELECT 1; SELECT a FROM t WHERE a > 2"
    assert [item.sql() for item in mojo.parse(sql)] == [
        item.sql() for item in upstream.parse(sql)
    ]


def test_pretty_generation_matches_upstream():
    sql = "SELECT a, b + 1 AS c FROM t WHERE a > 0 ORDER BY c DESC LIMIT 5"
    assert mojo.parse_one(sql).sql(pretty=True) == upstream.parse_one(sql).sql(pretty=True)


def test_expression_tree_column_traversal():
    sql = "SELECT u.id, SUM(o.total) AS total FROM users u JOIN orders o ON u.id = o.user_id GROUP BY u.id"
    got = [column.sql() for column in mojo.parse_one(sql).find_all(exp.Column)]
    ref = [column.sql() for column in upstream.parse_one(sql).find_all(upstream.exp.Column)]
    assert got == ref


def test_expression_copy_is_independent():
    original = mojo.parse_one("SELECT a FROM t")
    copied = original.copy()
    copied.expressions[0].this = exp.Identifier("b")
    assert original.sql() == "SELECT a FROM t"
    assert copied.sql() == "SELECT b FROM t"


def test_expression_transform_is_independent():
    original = mojo.parse_one("SELECT a FROM t")
    transformed = original.transform(
        lambda node: exp.Identifier("b")
        if isinstance(node, exp.Identifier) and node.name == "a"
        else node
    )
    assert original.sql() == "SELECT a FROM t"
    assert transformed.sql() == "SELECT b FROM t"


def test_builder_api_matches_upstream():
    got = exp.select("a", "b + 1").from_("t").where("a > 0").sql()
    ref = upstream.exp.select("a", "b + 1").from_("t").where("a > 0").sql()
    assert got == ref


@pytest.mark.parametrize(
    ("sql", "read", "write"),
    [
        ("SELECT IF(a > 0, a, 0) FROM x", None, "postgres"),
        ("SELECT APPROX_DISTINCT(a) FROM x", "presto", "spark"),
        ("SELECT EPOCH_MS(1618088028295)", "duckdb", "hive"),
        ("SELECT `a` FROM `x`", "mysql", "postgres"),
        ("SELECT TOP 10 a FROM x", "tsql", "mysql"),
        ("SELECT a::INT FROM x", "postgres", "mysql"),
    ],
)
def test_transpile_matches_upstream(sql, read, write):
    assert mojo.transpile(sql, read=read, write=write) == upstream.transpile(
        sql, read=read, write=write
    )


def test_identifier_generation_options():
    tree = mojo.parse_one("SELECT Foo FROM Bar")
    assert tree.sql(identify=True) == upstream.parse_one("SELECT Foo FROM Bar").sql(
        identify=True
    )
    assert tree.sql(normalize=True) == "SELECT foo FROM bar"


def test_parse_error_contains_location():
    with pytest.raises(mojo.ParseError, match="line 1"):
        mojo.parse_one("SELECT a FROM")


@pytest.mark.parametrize(
    "sql",
    [
        "WITH RECURSIVE x (n) AS (SELECT 1) SELECT n FROM x",
        "SELECT * FROM (SELECT a FROM t) AS x",
        "SELECT a FROM t INTERSECT SELECT a FROM u",
        "SELECT a FROM t EXCEPT SELECT a FROM u",
        "SELECT * FROM a NATURAL JOIN b",
        "SELECT * FROM a RIGHT JOIN b USING (id)",
        "SELECT a FROM t QUALIFY ROW_NUMBER() OVER (PARTITION BY b ORDER BY c) = 1",
        "SELECT (a, b), TRY_CAST(c AS INT) FROM t",
    ],
)
def test_documented_parser_features_are_exercised(sql):
    assert mojo.parse_one(sql).sql()


@pytest.mark.parametrize("sql", ["CREATE TABLE x (a INT)", "INSERT INTO x VALUES (1)"])
def test_unsupported_statements_raise_parse_error(sql):
    with pytest.raises(mojo.ParseError):
        mojo.parse_one(sql)
