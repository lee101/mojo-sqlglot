"""sqlglot-compatible token objects backed by the Mojo scanner."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from ._lib import scan


class TokenType(Enum):
    VAR = auto()
    IDENTIFIER = auto()
    NUMBER = auto()
    STRING = auto()
    COMMA = auto()
    DOT = auto()
    L_PAREN = auto()
    R_PAREN = auto()
    PLUS = auto()
    DASH = auto()
    STAR = auto()
    SLASH = auto()
    MOD = auto()
    EQ = auto()
    NEQ = auto()
    LT = auto()
    LTE = auto()
    GT = auto()
    GTE = auto()
    SEMICOLON = auto()
    PLACEHOLDER = auto()
    COLON = auto()
    DCOLON = auto()
    DPIPE = auto()
    AMP = auto()
    PIPE = auto()
    CARET = auto()
    TILDE = auto()
    ARROW = auto()
    DARROW = auto()
    UNKNOWN = auto()
    SELECT = auto()
    FROM = auto()
    WHERE = auto()
    GROUP_BY = auto()
    HAVING = auto()
    ORDER_BY = auto()
    LIMIT = auto()
    OFFSET = auto()
    JOIN = auto()
    LEFT = auto()
    RIGHT = auto()
    FULL = auto()
    INNER = auto()
    OUTER = auto()
    CROSS = auto()
    NATURAL = auto()
    ON = auto()
    USING = auto()
    ALIAS = auto()
    AS = ALIAS
    AND = auto()
    OR = auto()
    NOT = auto()
    NULL = auto()
    TRUE = auto()
    FALSE = auto()
    DISTINCT = auto()
    ALL = auto()
    UNION = auto()
    INTERSECT = auto()
    EXCEPT = auto()
    WITH = auto()
    RECURSIVE = auto()
    CASE = auto()
    WHEN = auto()
    THEN = auto()
    ELSE = auto()
    END = auto()
    CAST = auto()
    TRY_CAST = auto()
    BETWEEN = auto()
    IN = auto()
    IS = auto()
    LIKE = auto()
    ILIKE = auto()
    ASC = auto()
    DESC = auto()
    NULLS = auto()
    FIRST = auto()
    LAST = auto()
    BY = auto()
    TOP = auto()
    QUALIFY = auto()
    OVER = auto()
    PARTITION_BY = auto()
    EXISTS = auto()


_PUNCTUATION = {
    5: TokenType.COMMA,
    6: TokenType.DOT,
    7: TokenType.L_PAREN,
    8: TokenType.R_PAREN,
    9: TokenType.PLUS,
    10: TokenType.DASH,
    11: TokenType.STAR,
    12: TokenType.SLASH,
    13: TokenType.MOD,
    14: TokenType.EQ,
    15: TokenType.NEQ,
    16: TokenType.LT,
    17: TokenType.LTE,
    18: TokenType.GT,
    19: TokenType.GTE,
    20: TokenType.SEMICOLON,
    21: TokenType.PLACEHOLDER,
    22: TokenType.COLON,
    23: TokenType.DCOLON,
    24: TokenType.DPIPE,
    25: TokenType.AMP,
    26: TokenType.PIPE,
    27: TokenType.CARET,
    28: TokenType.TILDE,
    29: TokenType.ARROW,
    30: TokenType.DARROW,
    31: TokenType.UNKNOWN,
}

_KEYWORDS = {
    name: getattr(TokenType, name)
    for name in (
        "SELECT FROM WHERE HAVING LIMIT OFFSET JOIN LEFT RIGHT FULL INNER OUTER "
        "CROSS NATURAL ON USING AS AND OR NOT NULL TRUE FALSE DISTINCT ALL UNION "
        "INTERSECT EXCEPT WITH RECURSIVE CASE WHEN THEN ELSE END CAST TRY_CAST "
        "BETWEEN IN IS LIKE ILIKE ASC DESC NULLS FIRST LAST BY TOP QUALIFY OVER "
        "EXISTS"
    ).split()
}

_COMPOUND_KEYWORDS = {
    "GROUP": TokenType.GROUP_BY,
    "ORDER": TokenType.ORDER_BY,
    "PARTITION": TokenType.PARTITION_BY,
}


@dataclass(slots=True)
class Token:
    token_type: TokenType
    text: str
    line: int = 1
    col: int = 1
    start: int = 0
    end: int = 0
    comments: list[str] = field(default_factory=list)
    raw: str = ""
    quoted: bool = False


def _positions(sql: str, offsets: list[int]) -> dict[int, int]:
    wanted = set(offsets)
    result: dict[int, int] = {}
    byte_offset = 0
    for char_offset, char in enumerate(sql):
        if byte_offset in wanted:
            result[byte_offset] = char_offset
        byte_offset += len(char.encode("utf-8"))
    result[byte_offset] = len(sql)
    return result


def tokenize(sql: str) -> list[Token]:
    data = sql.encode("utf-8")
    starts, ends, kinds = scan(data)
    start_values = memoryview(starts)
    end_values = memoryview(ends)
    kind_values = memoryview(kinds)
    char_pos = (
        None
        if len(data) == len(sql)
        else _positions(
            sql,
            [offset for pair in zip(start_values, end_values) for offset in pair],
        )
    )
    next_newline = sql.find("\n")
    newline_count = 0
    last_newline = -1
    tokens: list[Token] = []
    append_token = tokens.append
    for byte_start, byte_end, kind in zip(start_values, end_values, kind_values):
        if char_pos is None:
            start, end_exclusive = byte_start, byte_end
        else:
            start, end_exclusive = char_pos[byte_start], char_pos[byte_end]
        raw = sql[start:end_exclusive]
        quoted = kind == 4
        if kind == 1:
            token_type = _KEYWORDS.get(raw)
            if token_type is None:
                token_type = _KEYWORDS.get(raw.upper(), TokenType.VAR)
            text = raw
        elif kind == 2:
            token_type, text = TokenType.NUMBER, raw
        elif kind == 3:
            token_type = TokenType.STRING
            text = raw[1:-1].replace("''", "'")
        elif quoted:
            token_type = TokenType.IDENTIFIER
            close = raw[-1:] if raw.startswith("[") else raw[:1]
            text = raw[1:-1].replace(close + close, close)
        else:
            token_type, text = _PUNCTUATION[kind], raw
        while next_newline != -1 and next_newline < end_exclusive:
            last_newline = next_newline
            newline_count += 1
            next_newline = sql.find("\n", next_newline + 1)
        line = newline_count + 1
        col = end_exclusive - last_newline - 1
        if token_type is TokenType.BY and tokens:
            previous = tokens[-1]
            if previous.token_type is TokenType.VAR:
                previous_upper = previous.text.upper()
                compound = _COMPOUND_KEYWORDS.get(previous_upper)
                if compound is not None:
                    tokens[-1] = Token(
                        compound,
                        f"{previous_upper} BY",
                        line,
                        col,
                        previous.start,
                        end_exclusive - 1,
                        raw=previous.raw + " " + raw,
                    )
                    continue
        append_token(
            Token(token_type, text, line, col, start, end_exclusive - 1, raw=raw, quoted=quoted)
        )
    return tokens


class Tokenizer:
    def __init__(
        self,
        dialect: Any = None,
        use_rs_tokenizer: bool | None = None,
        **opts: Any,
    ) -> None:
        self.dialect = dialect
        self.opts = opts
        self.use_rs_tokenizer = use_rs_tokenizer

    def tokenize(self, sql: str) -> list[Token]:
        return tokenize(sql)
