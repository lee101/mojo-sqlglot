"""Reproducible mojo-sqlglot benchmarks against upstream sqlglot."""

from __future__ import annotations

import os
import platform
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

import sqlglot as upstream  # noqa: E402
from sqlglot.optimizer.simplify import simplify as upstream_simplify  # noqa: E402

import mojosqlglot as mojo  # noqa: E402


def best_time(function, repeat: int = 5) -> tuple[float, object]:
    function()
    best = float("inf")
    result = None
    for _ in range(repeat):
        started = time.perf_counter()
        result = function()
        best = min(best, time.perf_counter() - started)
    return best, result


def cpu_name() -> str:
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or platform.machine()


def row(name: str, mojo_seconds: float, upstream_seconds: float) -> str:
    ratio = upstream_seconds / mojo_seconds
    if ratio >= 1:
        relative = f"{ratio:.2f}x faster"
    else:
        relative = f"{1 / ratio:.2f}x slower"
    return (
        f"| {name} | {mojo_seconds * 1e3:.2f} ms | "
        f"{upstream_seconds * 1e3:.2f} ms | {relative} |"
    )


def main() -> None:
    query = (
        "SELECT u.id, u.region, SUM(o.total * (1 - o.discount)) AS revenue, "
        "COUNT(DISTINCT o.id) AS orders FROM users AS u "
        "LEFT JOIN orders AS o ON u.id = o.user_id "
        "WHERE o.created_at >= '2025-01-01' AND o.status NOT IN ('void', 'test') "
        "GROUP BY u.id, u.region HAVING SUM(o.total) > 100 "
        "ORDER BY revenue DESC LIMIT 100"
    )
    script = ";\n".join([query] * 750)
    mojo_tokenizer = mojo.Tokenizer()
    upstream_tokenizer = upstream.Tokenizer()

    mojo_s, mojo_tokens = best_time(lambda: mojo_tokenizer.tokenize(script))
    upstream_s, upstream_tokens = best_time(lambda: upstream_tokenizer.tokenize(script))
    assert [(t.token_type.name, t.text) for t in mojo_tokens] == [
        (t.token_type.name, t.text) for t in upstream_tokens
    ]
    size_mb = len(script.encode("utf-8")) / 1_000_000
    rows = [row(f"tokenize 750 queries ({size_mb:.2f} MB)", mojo_s, upstream_s)]

    mojo_s, mojo_trees = best_time(lambda: mojo.parse(script), repeat=3)
    upstream_s, upstream_trees = best_time(lambda: upstream.parse(script), repeat=3)
    assert [tree.sql() for tree in mojo_trees] == [tree.sql() for tree in upstream_trees]
    rows.append(row("parse 750 SELECT queries", mojo_s, upstream_s))

    mysql_query = (
        "SELECT `u`.`id`, IF(`o`.`total` > 0, `o`.`total`, 0) AS `net` "
        "FROM `users` AS `u` LEFT JOIN `orders` AS `o` ON `u`.`id` = `o`.`user_id` "
        "WHERE `u`.`active` = 1 LIMIT 100"
    )
    mysql_script = ";\n".join([mysql_query] * 500)
    mojo_s, mojo_sql = best_time(
        lambda: mojo.transpile(mysql_script, read="mysql", write="postgres"), repeat=3
    )
    upstream_s, upstream_sql = best_time(
        lambda: upstream.transpile(mysql_script, read="mysql", write="postgres"), repeat=3
    )
    assert mojo_sql == upstream_sql
    rows.append(row("transpile 500 MySQL queries", mojo_s, upstream_s))

    optimize_queries = [
        f"SELECT 1 + 2 * 3 AS x FROM t WHERE FALSE OR (a = {index} AND TRUE)"
        for index in range(1_000)
    ]
    mojo_s, mojo_optimized = best_time(
        lambda: [mojo.optimize(sql).sql() for sql in optimize_queries], repeat=3
    )
    upstream_s, upstream_optimized = best_time(
        lambda: [
            upstream_simplify(upstream.parse_one(sql)).sql() for sql in optimize_queries
        ],
        repeat=3,
    )
    assert mojo_optimized == upstream_optimized
    rows.append(row("simplify 1,000 queries", mojo_s, upstream_s))

    print(f"Machine: {cpu_name()}; {platform.system()} {platform.release()}")
    print(f"Python {platform.python_version()}; sqlglot {upstream.__version__}")
    print()
    print(f"| case | mojo-sqlglot | sqlglot {upstream.__version__} | relative |")
    print("| --- | ---: | ---: | ---: |")
    print("\n".join(rows))


if __name__ == "__main__":
    main()
