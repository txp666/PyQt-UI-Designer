"""HTTPS and MQTT TLS must trust the operating system, not the build machine's OpenSSL paths."""
import builtins
import ssl
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.common import update_checker
from app.core import mqtt_runtime, protocol_parser
from app.core.code_generator import _gen_mqtt_handler
from app.core.tls_runtime import system_ssl_context


class TlsRuntimeTests(unittest.TestCase):
    def test_context_verifies_through_the_system_trust_store(self):
        context = system_ssl_context()
        self.assertTrue(type(context).__module__.startswith("truststore"), type(context))
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_without_truststore_the_default_verifying_context_is_used(self):
        real_import = builtins.__import__

        def no_truststore(name, *args, **kwargs):
            if name == "truststore":
                raise ImportError(name)
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", no_truststore):
            context = system_ssl_context()
        self.assertIs(type(context), ssl.SSLContext)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_update_check_passes_the_system_context_to_urlopen(self):
        seen = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self): return b'{"tag_name": "v99.0.0", "html_url": "u", "body": ""}'

        def fake_urlopen(request, timeout, context):
            seen.append(context)
            return Response()

        results = []
        thread = update_checker.UpdateCheckThread("0.1.6")
        thread.result.connect(lambda *values: results.append(values))
        with patch.object(update_checker, "urlopen", fake_urlopen):
            thread.run()
        self.assertTrue(type(seen[0]).__module__.startswith("truststore"), seen)
        self.assertEqual(results[0][:2], (True, "v99.0.0"))

    def test_exported_mqtt_handler_carries_the_same_context_factory(self):
        namespace = {}
        with patch.dict(sys.modules, {"serial_handler": SimpleNamespace(
                create_parser=protocol_parser.create_parser)}):
            exec(_gen_mqtt_handler({}), namespace)
        self.assertIn("system_ssl_context", namespace)
        self.assertTrue(type(namespace["system_ssl_context"]()).__module__.startswith("truststore"))
        self.assertIs(mqtt_runtime.system_ssl_context, system_ssl_context)


if __name__ == "__main__":
    unittest.main()
