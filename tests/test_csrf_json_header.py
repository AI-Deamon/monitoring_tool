"""
CSRF token acceptance for JSON/fetch clients (Burp #10).

Form POSTs carry the HMAC CSRF token in a hidden `csrf_token` field. JSON API
clients have no form body, so `validate_csrf_token()` must also accept the same
token supplied in an `X-CSRF-Token` header. A token minted for the session must
validate via the header alone, and a missing/foreign token must still fail.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('SECRET_KEY', 'y' * 40)

from flask import Flask
import auth


def _make_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ['SECRET_KEY']
    return app


class TestCsrfHeader(unittest.TestCase):
    def test_header_token_is_accepted(self):
        app = _make_app()
        with app.test_request_context():
            token = auth.generate_csrf_token()
        # Header-only request (no form field) must validate.
        with app.test_request_context(method='POST', headers={'X-CSRF-Token': token}):
            self.assertTrue(auth.validate_csrf_token())

    def test_missing_token_is_rejected(self):
        app = _make_app()
        with app.test_request_context(method='POST'):
            self.assertFalse(auth.validate_csrf_token())

    def test_garbage_header_token_is_rejected(self):
        app = _make_app()
        with app.test_request_context(method='POST',
                                      headers={'X-CSRF-Token': 'not-a-real-token'}):
            self.assertFalse(auth.validate_csrf_token())


if __name__ == "__main__":
    unittest.main()
