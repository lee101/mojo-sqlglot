"""UTF-8 SQL lexical scanner used by the Python parser."""

from std.sys.info import simd_width_of as simdwidthof

comptime BytePtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime IntPtr = UnsafePointer[Int64, AnyOrigin[mut=True]]

comptime K_WORD = 1
comptime K_NUMBER = 2
comptime K_STRING = 3
comptime K_QUOTED = 4
comptime K_COMMA = 5
comptime K_DOT = 6
comptime K_LPAREN = 7
comptime K_RPAREN = 8
comptime K_PLUS = 9
comptime K_MINUS = 10
comptime K_STAR = 11
comptime K_SLASH = 12
comptime K_PERCENT = 13
comptime K_EQ = 14
comptime K_NEQ = 15
comptime K_LT = 16
comptime K_LTE = 17
comptime K_GT = 18
comptime K_GTE = 19
comptime K_SEMICOLON = 20
comptime K_PARAMETER = 21
comptime K_COLON = 22
comptime K_DCOLON = 23
comptime K_CONCAT = 24
comptime K_AMP = 25
comptime K_PIPE = 26
comptime K_CARET = 27
comptime K_TILDE = 28
comptime K_ARROW = 29
comptime K_FARROW = 30
comptime K_UNKNOWN = 31


def is_space(c: UInt8) -> Bool:
    return c == 32 or c == 9 or c == 10 or c == 13 or c == 12


def is_digit(c: UInt8) -> Bool:
    return c >= 48 and c <= 57


def is_word_start(c: UInt8) -> Bool:
    return (
        (c >= 65 and c <= 90)
        or (c >= 97 and c <= 122)
        or c == 95
        or c >= 128
    )


def is_word(c: UInt8) -> Bool:
    return is_word_start(c) or is_digit(c) or c == 36


def emit(
    starts: IntPtr,
    ends: IntPtr,
    kinds: IntPtr,
    count: Int,
    start: Int,
    end: Int,
    kind: Int,
):
    starts[count] = Int64(start)
    ends[count] = Int64(end)
    kinds[count] = Int64(kind)


def scan(
    src: BytePtr,
    n: Int,
    starts: IntPtr,
    ends: IntPtr,
    kinds: IntPtr,
    capacity: Int,
) -> Int:
    comptime W = simdwidthof[DType.float64]()
    var i = 0
    var count = 0
    while i < n:
        var c = src[i]
        if is_space(c):
            i += 1
            continue

        if c == 45 and i + 1 < n and src[i + 1] == 45:
            i += 2
            while i < n and src[i] != 10 and src[i] != 13:
                i += 1
            continue

        if c == 47 and i + 1 < n and src[i + 1] == 42:
            i += 2
            var depth = 1
            while i < n and depth > 0:
                if i + 1 < n and src[i] == 47 and src[i + 1] == 42:
                    depth += 1
                    i += 2
                elif i + 1 < n and src[i] == 42 and src[i + 1] == 47:
                    depth -= 1
                    i += 2
                else:
                    i += 1
            if depth > 0:
                return -3
            continue

        if count >= capacity:
            return -count - 1
        var start = i

        if c == 39:
            i += 1
            var closed = False
            while i < n:
                if src[i] == 39:
                    if i + 1 < n and src[i + 1] == 39:
                        i += 2
                        continue
                    i += 1
                    closed = True
                    break
                if src[i] == 92 and i + 1 < n:
                    i += 2
                else:
                    i += 1
            if not closed:
                return -3
            emit(starts, ends, kinds, count, start, i, K_STRING)
            count += 1
            continue

        if c == 34 or c == 96 or c == 91:
            var close = c
            if c == 91:
                close = 93
            i += 1
            var closed = False
            while i < n:
                if src[i] == close:
                    if i + 1 < n and src[i + 1] == close:
                        i += 2
                        continue
                    i += 1
                    closed = True
                    break
                i += 1
            if not closed:
                return -3
            emit(starts, ends, kinds, count, start, i, K_QUOTED)
            count += 1
            continue

        if is_digit(c) or (c == 46 and i + 1 < n and is_digit(src[i + 1])):
            if c == 46:
                i += 1
            while i < n and is_digit(src[i]):
                i += 1
            if i < n and src[i] == 46:
                i += 1
                while i < n and is_digit(src[i]):
                    i += 1
            if i < n and (src[i] == 69 or src[i] == 101):
                var exponent = i
                i += 1
                if i < n and (src[i] == 43 or src[i] == 45):
                    i += 1
                var digit_start = i
                while i < n and is_digit(src[i]):
                    i += 1
                if digit_start == i:
                    i = exponent
            emit(starts, ends, kinds, count, start, i, K_NUMBER)
            count += 1
            continue

        if is_word_start(c):
            i += 1
            while i + W <= n:
                var chars = src.load[width=W](i)
                var word_chars = (
                    (chars.ge(65) & chars.le(90))
                    | (chars.ge(97) & chars.le(122))
                    | chars.eq(95)
                    | chars.ge(128)
                    | (chars.ge(48) & chars.le(57))
                    | chars.eq(36)
                )
                if not Bool(word_chars.reduce_and()):
                    break
                i += W
            while i < n and is_word(src[i]):
                i += 1
            emit(starts, ends, kinds, count, start, i, K_WORD)
            count += 1
            continue

        var kind = K_UNKNOWN
        i += 1
        if c == 44:
            kind = K_COMMA
        elif c == 46:
            kind = K_DOT
        elif c == 40:
            kind = K_LPAREN
        elif c == 41:
            kind = K_RPAREN
        elif c == 43:
            kind = K_PLUS
        elif c == 45:
            if i < n and src[i] == 62:
                i += 1
                if i < n and src[i] == 62:
                    i += 1
                    kind = K_FARROW
                else:
                    kind = K_ARROW
            else:
                kind = K_MINUS
        elif c == 42:
            kind = K_STAR
        elif c == 47:
            kind = K_SLASH
        elif c == 37:
            kind = K_PERCENT
        elif c == 61:
            kind = K_EQ
        elif c == 33:
            if i < n and src[i] == 61:
                i += 1
                kind = K_NEQ
        elif c == 60:
            kind = K_LT
            if i < n and src[i] == 61:
                i += 1
                kind = K_LTE
            elif i < n and src[i] == 62:
                i += 1
                kind = K_NEQ
        elif c == 62:
            kind = K_GT
            if i < n and src[i] == 61:
                i += 1
                kind = K_GTE
        elif c == 59:
            kind = K_SEMICOLON
        elif c == 63 or c == 64 or c == 36:
            kind = K_PARAMETER
            while i + W <= n:
                var chars = src.load[width=W](i)
                var word_chars = (
                    (chars.ge(65) & chars.le(90))
                    | (chars.ge(97) & chars.le(122))
                    | chars.eq(95)
                    | chars.ge(128)
                    | (chars.ge(48) & chars.le(57))
                    | chars.eq(36)
                )
                if not Bool(word_chars.reduce_and()):
                    break
                i += W
            while i < n and is_word(src[i]):
                i += 1
        elif c == 58:
            kind = K_COLON
            if i < n and src[i] == 58:
                i += 1
                kind = K_DCOLON
            else:
                while i < n and is_word(src[i]):
                    i += 1
        elif c == 124:
            kind = K_PIPE
            if i < n and src[i] == 124:
                i += 1
                kind = K_CONCAT
        elif c == 38:
            kind = K_AMP
        elif c == 94:
            kind = K_CARET
        elif c == 126:
            kind = K_TILDE
        emit(starts, ends, kinds, count, start, i, kind)
        count += 1
    return count


@export("msg_tokenize")
def msg_tokenize(
    src_addr: Int,
    n: Int,
    starts_addr: Int,
    ends_addr: Int,
    kinds_addr: Int,
    capacity: Int,
) abi("C") -> Int:
    # Reject malformed C callers before constructing or dereferencing pointers.
    # Empty input is valid and does not require any backing allocations.
    if n < 0 or capacity < 0:
        return -2
    if n == 0:
        return 0
    if src_addr == 0:
        return -2
    if capacity > 0 and (
        starts_addr == 0
        or ends_addr == 0
        or kinds_addr == 0
        or starts_addr % 8 != 0
        or ends_addr % 8 != 0
        or kinds_addr % 8 != 0
    ):
        return -2
    return scan(
        BytePtr(unsafe_from_address=src_addr),
        n,
        IntPtr(unsafe_from_address=starts_addr),
        IntPtr(unsafe_from_address=ends_addr),
        IntPtr(unsafe_from_address=kinds_addr),
        capacity,
    )
