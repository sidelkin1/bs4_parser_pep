class ParserFindTagException(Exception):
    """Вызывается, когда парсер не может найти тег."""
    pass


class ParserFindAllVersionsException(Exception):
    """Вызывается, когда парсер не может найти строку 'All versions'."""
    pass


class ParserStatusAbbreviationException(Exception):
    """Вызывается, когда парсер не может найти аббревиатуру PEP-статуса."""
    pass
