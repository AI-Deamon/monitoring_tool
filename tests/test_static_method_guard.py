"""
Static-route method guard (Burp #1, client-side desync mitigation).

Burp accepted a POST carrying a smuggled second request on a `/static/` path.
Static assets are read-only, so any non-idempotent method must be rejected
(405) before the body is processed. GET must still serve the asset, and the
static response must ask the connection to close (defence-in-depth; the
authoritative fix is HTTP/2 upstream).
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

os.environ['FLASK_ENV'] = 'development'
os.environ.setdefault('SECRET_KEY', 'x' * 40)


class TestStaticMethodGuard(unittest.TestCase):
    def _client(self):
        import importlib, server_app
        importlib.reload(server_app)
        app = server_app.create_app()
        app.config.update(TESTING=True)
        return app.test_client()

    def test_post_to_static_is_rejected(self):
        r = self._client().post('/static/js/utils.js')
        self.assertEqual(r.status_code, 405)

    def test_put_to_static_is_rejected(self):
        r = self._client().put('/static/js/utils.js')
        self.assertEqual(r.status_code, 405)

    def test_get_static_still_served(self):
        r = self._client().get('/static/js/utils.js')
        self.assertEqual(r.status_code, 200)


if __name__ == "__main__":
    unittest.main()
