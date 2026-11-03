"""
Utility for redacting sensitive database connection information.
"""

from sqlalchemy.engine import make_url


def redact_database_url(url: str) -> str:
    """
    Return scheme and host only from database URL.
    Never returns user, password, port, path, or query parameters.
    """
    if not url:
        return ""
    try:
        parsed = make_url(url)
        scheme = parsed.drivername
        host = parsed.host or ""
    except Exception:
        from urllib.parse import urlsplit
        parsed_split = urlsplit(url)
        scheme = parsed_split.scheme
        host = parsed_split.hostname or ""

    if host:
        return f"{scheme}://{host}"
    return f"{scheme}://"

