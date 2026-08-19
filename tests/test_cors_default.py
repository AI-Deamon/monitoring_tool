import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


class TestCorsDefault(unittest.TestCase):
    def setUp(self):
        self._saved = {
            'CORS_ORIGINS': os.environ.get('CORS_ORIGINS'),
            'FLASK_ENV': os.environ.get('FLASK_ENV'),
        }

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_default_origins_is_not_wildcard(self):
        os.environ.pop('CORS_ORIGINS', None)
        import importlib, server_app
        importlib.reload(server_app)
        self.assertEqual(server_app.resolve_cors_origins(), [])

    def test_env_allowlist_is_split(self):
        os.environ['CORS_ORIGINS'] = 'https://a.example, https://b.example'
        import importlib, server_app
        importlib.reload(server_app)
        self.assertEqual(server_app.resolve_cors_origins(),
                         ['https://a.example', 'https://b.example'])

    def test_wildcard_refused_in_production(self):
        os.environ['CORS_ORIGINS'] = '*'
        os.environ['FLASK_ENV'] = 'production'
        import importlib, server_app
        importlib.reload(server_app)
        with self.assertRaises(RuntimeError):
            server_app.resolve_cors_origins()


if __name__ == "__main__":
    unittest.main()
