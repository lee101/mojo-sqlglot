class SqlglotError(Exception):
    pass


class ParseError(SqlglotError):
    pass


class UnsupportedError(SqlglotError):
    pass
