from app.utils.redact import redact_database_url


def test_redact_database_url_remote_postgres():
    url = "postgresql://alice:pw-sentinel-9x@db.example.com:5432/mydb?sslmode=require"
    redacted = redact_database_url(url)
    assert redacted == "postgresql://db.example.com"
    for forbidden in ["alice", "pw-sentinel-9x", "5432", "mydb", "sslmode"]:
        assert forbidden not in redacted


def test_redact_database_url_sqlite():
    assert redact_database_url("sqlite:///./a.db") == "sqlite://"


def test_redact_database_url_empty():
    assert redact_database_url("") == ""


def test_redact_database_url_unparseable():
    unparseable = ":::not-a-valid-url:::user:pw-sentinel-secret@bad-host:9999/mydb"
    result = redact_database_url(unparseable)
    assert "pw-sentinel-secret" not in result


# Error-path probe: incomplete bracketed IPv6 host should not raise
def test_redact_database_url_truncated_ipv6_host_does_not_raise():
    # Probes the error path for a malformed bracketed host
    result = redact_database_url("postgresql://user:pw-sentinel-secret@[bad")
    assert "pw-sentinel-secret" not in result


# Error-path probe: non-numeric port should not raise
def test_redact_database_url_nonnumeric_port_does_not_raise():
    # Probes the error path for a URL with a non-numeric port
    result = redact_database_url("postgresql://user:pw-sentinel-secret@host:notaport/db")
    assert "pw-sentinel-secret" not in result
