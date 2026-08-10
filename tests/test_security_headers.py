import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('SECRET_KEY', 'x'*40)


class TestSecurityHeaders(unittest.TestCase):
    def _resp_headers(self, path='/auth/login'):
        import importlib, server_app
        importlib.reload(server_app)
        from flask import Response
        app = server_app.create_app()
        app.config.update(TESTING=True)
        # Apply every registered after_request hook in order against a plain
        # Response, inside a request context so `request.path`/`g` resolve.
        hooks = app.after_request_funcs.get(None, [])
        resp = Response("", status=200)
        with app.test_request_context(path=path):
            for hook in hooks:
                resp = hook(resp)
        return resp.headers

    def test_no_stale_cdn_in_csp(self):
        csp = self._resp_headers().get('Content-Security-Policy', '')
        self.assertNotIn('cdn.tailwindcss.com', csp)
        self.assertNotIn('cdn.jsdelivr.net', csp)
        self.assertNotIn('fonts.googleapis.com', csp)
        self.assertNotIn('fonts.gstatic.com', csp)

    def test_referrer_and_permissions_policy(self):
        h = self._resp_headers()
        self.assertIn('Referrer-Policy', h)
        self.assertIn('Permissions-Policy', h)

    def test_nosniff_and_frame_options(self):
        h = self._resp_headers()
        self.assertEqual(h.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(h.get('X-Frame-Options'), 'SAMEORIGIN')


if __name__ == "__main__":
    unittest.main()
