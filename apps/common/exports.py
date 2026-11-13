"""Spreadsheet export cells are data, never executable formula expressions."""


def safe_spreadsheet_value(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    text = str(value)
    # Spreadsheet importers may ignore leading whitespace/control characters.
    if text.lstrip(" \t\r\n\x00\ufeff").startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r", "\n")):
        return "'" + text
    return text
