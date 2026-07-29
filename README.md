# mojo-sqlglot

`mojo-sqlglot` is a standalone SQL parser, transpiler, and local optimizer with
its lexical scanner implemented in [Mojo](https://www.modular.com/mojo). Its
Python API follows sqlglot's names and signatures for the covered subset:

```python
import mojosqlglot as sqlglot
from mojosqlglot import exp

query = sqlglot.parse_one(
    "select department, sum(amount) as revenue "
    "from sales where amount > 0 group by department"
)

print(query.sql())
print([column.sql() for column in query.find_all(exp.Column)])
print(sqlglot.transpile("SELECT `user_id` FROM `events`", read="mysql", write="postgres"))
```

Output:

```text
SELECT department, SUM(amount) AS revenue FROM sales WHERE amount > 0 GROUP BY department
['department', 'department', 'amount', 'amount']
['SELECT "user_id" FROM "events"']
```

This does not import or fall back to Python sqlglot at runtime. The upstream
package is present in the development environment only for parity tests and
benchmarks.

## Covered subset

The parser covers analytical `SELECT` queries:

- multiple statements, `WITH`/recursive CTEs, `DISTINCT`, aliases, qualified
  names, quoted identifiers, subqueries, and `UNION`/`INTERSECT`/`EXCEPT`;
- `FROM`, comma/cross/inner/outer/natural joins, `ON`, and `USING`;
- `WHERE`, `GROUP BY`, `HAVING`, `QUALIFY`, `ORDER BY`, `LIMIT`, `OFFSET`, and
  T-SQL `TOP`;
- arithmetic, comparison and Boolean operators, `BETWEEN`, `IN`, `IS`,
  `LIKE`/`ILIKE`, tuples, `CASE`, `CAST`/`TRY_CAST`, PostgreSQL `::` casts,
  function calls, and `OVER (PARTITION BY ... ORDER BY ...)`;
- sqlglot-style expression traversal, copying, transformation, builders, and
  canonical or pretty SQL generation.

The transpiler supports syntax represented by that grammar and includes tested
rewrites for identifier quoting, T-SQL `TOP`, PostgreSQL casts, MySQL signed
casts, `IF` to PostgreSQL `CASE`, Spark approximate distinct, and DuckDB epoch
milliseconds to Hive. The optimizer performs local constant folding, Boolean
reduction, constant comparisons and `BETWEEN`, parenthesis cleanup, and
constant `CASE` pruning. Custom optimizer rule sequences are accepted.

The native tokenizer handles UTF-8 identifiers, decimal/exponent numbers,
parameters, escaped strings, quoted identifiers, nested block comments, line
comments, and multi-character operators. It exposes `Tokenizer`, `Token`, and
`TokenType` with upstream-compatible fields for the covered tokens.

Not covered:

- DDL, DML, commands, procedural SQL, and vendor-specific statement grammars;
- schema-aware qualification, type inference, join reordering, predicate
  pushdown, or the rest of upstream's optimizer rule pipeline;
- window frames, array/map literals, lambdas, pivots, pattern matching clauses,
  and many long-tail dialect extensions;
- preservation of SQL comments in the generated expression tree.

Unsupported syntax raises `ParseError`; it is never silently delegated to
upstream. This is intentionally a useful, tested analytical core rather than a
claim of parity with sqlglot's full dialect matrix.

## Install and run

The repository pins the Mojo nightly used to build it.

```bash
pixi install
pixi run build
pixi run test
pixi run bench
```

`pixi run build` creates `dist/libmojo-sqlglot.so`. The Python bridge also
rebuilds a missing or stale library on first use. Set `MOJOSQLGLOT_LIB` to use
an already-built shared library elsewhere.

## Performance

Measured on an Intel Xeon E5-2697 v4 at 2.30 GHz, Linux
6.8.0-136-generic, Python 3.13.14, and sqlglot 28.10.1. The benchmark warms each
case, takes the best of repeated runs, verifies identical generated SQL or
tokens, and runs behind the machine-wide flock in `pixi run bench`.

| case | mojo-sqlglot | sqlglot 28.10.1 | relative |
| --- | ---: | ---: | ---: |
| tokenize 750 queries (0.23 MB) | 165.89 ms | 360.96 ms | 2.18x faster |
| parse 750 SELECT queries | 600.63 ms | 1812.89 ms | 3.02x faster |
| transpile 500 MySQL queries | 189.00 ms | 559.71 ms | 2.96x faster |
| simplify 1,000 queries | 483.08 ms | 1823.72 ms | 3.78x faster |

Creating compatible Python `Token` objects and decoding their text is included
in the tokenization measurement. These numbers measure the supported subset,
not full-feature equivalence with upstream.

There is no GPU path. Lexing is a branch-heavy, ordered scan with low arithmetic
intensity, while the public API must also create Python token and expression
objects.

## How it works

`src/sqlglot.mojo` is one compilation unit and exports one C-ABI scanning
function. Python encodes SQL once as contiguous UTF-8 and allocates one
contiguous NumPy backing buffer with three `int64` views for token starts,
exclusive ends, and kinds. The zero-copy views cross `ctypes` as integer
addresses; Mojo reconstructs
`UnsafePointer[..., AnyOrigin[mut=True]]` values inside the non-parametric
`@export` wrapper. Mojo allocates nothing and retains no pointer after the call.
The wrapper rejects negative lengths, null pointers for non-empty buffers, and
misaligned output pointers before constructing Mojo pointers.

The scanner makes one pass over the byte buffer. Python then turns its spans
into compatible token objects, folds compound keywords such as `GROUP BY`, and
feeds a recursive-descent query parser with a Pratt expression parser. The
expression tree remains ordinary Python so traversal, mutation, custom rules,
and dialect-specific generation do not require object ownership across the
FFI boundary.

## License

MIT
