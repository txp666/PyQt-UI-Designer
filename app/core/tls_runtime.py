"""TLS contexts that trust what the operating system trusts.

A Python runtime bundled into an application keeps OpenSSL's certificate paths from the
machine that built it. On another computer those paths usually do not exist, so a default
context trusts nothing and every HTTPS or MQTT-over-TLS connection fails with "unable to
get local issuer certificate". truststore verifies through the operating system instead
(the macOS keychain, the Windows certificate store), including certificates the user
added there.
"""
import ssl


def system_ssl_context():
    """A client context that verifies servers against the operating system's trust store."""
    try:
        import truststore
        return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except Exception:  # not installed, or the platform's certificate API is unavailable
        return ssl.create_default_context()
