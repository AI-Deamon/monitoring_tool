"""
Dashboard data scoping (get_user_filter).

Every dashboard query does `if user_filter: <scope to that username>`, so a
FALSY return means "no filtering - show every agent". get_user_filter()
previously returned None for a non-admin whose linked_username was unset (and
for a missing session), which handed that account admin-wide visibility of
all agents' data. It must fail closed instead.
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

os.environ.setdefault('FLASK_ENV', 'development')
os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-unit-tests')

import auth as auth_module
from auth import get_user_filter, NO_ACCESS_USERNAME


class _FakeG:
    def __init__(self, user=None):
        if user is not None:
            self.current_user = user


class TestGetUserFilter(unittest.TestCase):
    def _filter_for(self, user):
        with patch.object(auth_module, 'g', _FakeG(user)):
            return get_user_filter()

    def test_admin_gets_no_filter(self):
        admin = SimpleNamespace(role='admin', linked_username=None)
        self.assertIsNone(self._filter_for(admin))

    def test_linked_user_is_scoped_to_their_username(self):
        user = SimpleNamespace(role='user', linked_username='jdoe')
        self.assertEqual(self._filter_for(user), 'jdoe')

    def test_user_without_linked_username_sees_nothing(self):
        """The privilege-escalation case: must NOT return a falsy filter."""
        user = SimpleNamespace(role='user', linked_username=None)

        result = self._filter_for(user)

        self.assertTrue(
            result,
            "a falsy filter disables scoping - this user would see ALL agents"
        )
        self.assertEqual(result, NO_ACCESS_USERNAME)

    def test_empty_linked_username_sees_nothing(self):
        user = SimpleNamespace(role='user', linked_username='')

        result = self._filter_for(user)

        self.assertTrue(result)
        self.assertEqual(result, NO_ACCESS_USERNAME)

    def test_no_session_fails_closed(self):
        with patch.object(auth_module, 'g', _FakeG(None)):
            result = get_user_filter()

        self.assertEqual(result, NO_ACCESS_USERNAME)

    def test_sentinel_cannot_match_a_real_windows_username(self):
        # Windows usernames cannot contain '\' or start/end with the double
        # underscore pattern used here; keep it obviously non-matching.
        self.assertNotEqual(NO_ACCESS_USERNAME, '')
        self.assertIn('__', NO_ACCESS_USERNAME)


if __name__ == '__main__':
    unittest.main()
