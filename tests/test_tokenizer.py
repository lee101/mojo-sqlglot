import sqlglot as upstream
import pytest

import mojosqlglot as mojo
from mojosqlglot._lib import lib, scan


def token_rows(tokens):
    return [
        (token.token_type.name, token.text, token.line, token.col, token.start, token.end)
        for token in tokens
    ]


def test_tokenizer_matches_upstream_for_select():
    sql = "select a,b+1 as c from db.t x where a>=10 and b!='x' order by c desc limit 5"
    assert token_rows(mojo.Tokenizer().tokenize(sql)) == token_rows(
        upstream.Tokenizer().tokenize(sql)
    )


def test_tokenizer_matches_upstream_for_strings_numbers_and_comments():
    sql = "SELECT \"c\", 'it''s', 1.2e-3 -- ignored\nFROM \"t\" WHERE x <> ?"
    assert token_rows(mojo.Tokenizer().tokenize(sql)) == token_rows(
        upstream.Tokenizer().tokenize(sql)
    )


def test_tokenizer_matches_mysql_quoted_identifiers():
    sql = "SELECT `weird``name` FROM `some-table`"
    assert token_rows(mojo.Tokenizer("mysql").tokenize(sql)) == token_rows(
        upstream.Dialect.get_or_raise("mysql").tokenizer().tokenize(sql)
    )


def test_tokenizer_handles_nested_block_comments():
    sql = "SELECT /* outer /* nested */ done */ a FROM t"
    assert [token.text for token in mojo.Tokenizer().tokenize(sql)] == [
        "SELECT",
        "a",
        "FROM",
        "t",
    ]


def test_tokenizer_unicode_offsets_are_character_offsets():
    sql = "SELECT café, '東京' FROM résumé"
    got = mojo.Tokenizer().tokenize(sql)
    ref = upstream.Tokenizer().tokenize(sql)
    assert token_rows(got) == token_rows(ref)


def test_incremental_newline_positions_match_upstream():
    sql = "SELECT\n\n  café,\n  '東京\n駅' AS place\nFROM résumé"
    assert token_rows(mojo.Tokenizer().tokenize(sql)) == token_rows(
        upstream.Tokenizer().tokenize(sql)
    )


def test_compound_keywords_match_upstream():
    sql = "SELECT a FROM t GROUP BY a ORDER BY a"
    assert [token.token_type.name for token in mojo.Tokenizer().tokenize(sql)] == [
        token.token_type.name for token in upstream.Tokenizer().tokenize(sql)
    ]


def test_simd_word_scan_handles_full_vectors_and_scalar_tails():
    sql = "SELECT a, abcd,\nabcde, abcdefgh, abcdefghi FROM table_name"
    assert token_rows(mojo.Tokenizer().tokenize(sql)) == token_rows(
        upstream.Tokenizer().tokenize(sql)
    )


def test_simd_parameter_scan_handles_full_vectors_and_scalar_tails():
    sql = "SELECT $a, $abcd, $abcde, $abcdefgh, $abcdefghi"
    placeholders = [
        token.text
        for token in mojo.Tokenizer().tokenize(sql)
        if token.token_type is mojo.TokenType.PLACEHOLDER
    ]
    assert placeholders == ["$a", "$abcd", "$abcde", "$abcdefgh", "$abcdefghi"]


def test_native_span_views_share_one_backing_allocation():
    starts, ends, kinds = scan(b"SELECT abcde")
    assert starts.base is ends.base is kinds.base


def test_native_scanner_rejects_invalid_lengths_and_pointers():
    native = lib().msg_tokenize
    assert native(0, -1, 0, 0, 0, 0) == -2
    assert native(0, 1, 0, 0, 0, 1) == -2


def test_native_scanner_accepts_empty_input_without_buffers():
    assert lib().msg_tokenize(0, 0, 0, 0, 0, 0) == 0
    starts, ends, kinds = scan(b"")
    assert not starts.size and not ends.size and not kinds.size


def test_scan_rejects_implicit_buffer_conversions():
    with pytest.raises(TypeError, match="must be bytes"):
        scan(bytearray(b"SELECT 1"))  # type: ignore[arg-type]


@pytest.mark.parametrize("sql", ["SELECT 'open", 'SELECT "open', "SELECT /* open"])
def test_tokenizer_rejects_unterminated_lexemes(sql):
    with pytest.raises(RuntimeError, match="unterminated SQL"):
        mojo.Tokenizer().tokenize(sql)
