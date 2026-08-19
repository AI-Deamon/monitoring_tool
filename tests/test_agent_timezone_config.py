"""
Agent-local timezone configuration.

The UTC offset that decides "what day is it for this user" was hardcoded as
IST (+05:30) in four modules (buffer, state_machine, state_detector,
live_telemetry). core.agent_time now owns it, so a deployment outside India
can set it once (config.json agent.timezone_offset_minutes /
AGENT_TZ_OFFSET_MINUTES) and every day-boundary agrees.

Default remains IST so existing agents are unchanged.
"""

import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'agent'))

from core import agent_time
from core import buffer as buffer_module
from core import state_machine as sm_module


class TestAgentTimeDefaults(unittest.TestCase):
    def tearDown(self):
        agent_time.set_offset_minutes(agent_time.DEFAULT_OFFSET_MINUTES)

    def test_default_offset_is_ist(self):
        self.assertEqual(agent_time.get_offset_minutes(), 330)
        self.assertEqual(
            agent_time.get_timezone().utcoffset(None),
            timedelta(hours=5, minutes=30),
        )

    def test_invalid_offset_is_ignored_not_crashing(self):
        agent_time.set_offset_minutes('not-a-number')
        self.assertEqual(agent_time.get_offset_minutes(), 330)

        agent_time.set_offset_minutes(99999)  # out of range
        self.assertEqual(agent_time.get_offset_minutes(), 330)


class TestOffsetIsHonoredEverywhere(unittest.TestCase):
    """A configured offset must reach every module that decides a day."""

    def tearDown(self):
        agent_time.set_offset_minutes(agent_time.DEFAULT_OFFSET_MINUTES)

    def test_all_modules_follow_reconfigured_offset(self):
        from core.live_telemetry import get_ist_now

        agent_time.set_offset_minutes(0)  # UTC deployment

        self.assertEqual(
            buffer_module._get_ist_now().utcoffset(), timedelta(0),
            "buffer timestamps still on the old offset"
        )
        self.assertEqual(
            sm_module._now_ist().utcoffset(), timedelta(0),
            "state machine day boundary still on the old offset"
        )
        self.assertEqual(
            sm_module._local_tz().utcoffset(None), timedelta(0),
            "state machine midnight split still on the old offset"
        )
        self.assertEqual(
            get_ist_now().utcoffset(), timedelta(0),
            "live telemetry still resolving Asia/Kolkata instead of the "
            "configured offset (also breaks in a frozen build with no tzdata)"
        )

    def test_day_boundary_moves_with_offset(self):
        """18:30 UTC is 'today' in UTC but already 'tomorrow' in IST - the
        exact bug class this centralization prevents."""
        instant = datetime(2026, 7, 10, 19, 0, tzinfo=timezone.utc)

        agent_time.set_offset_minutes(0)
        self.assertEqual(agent_time.to_local(instant).date().isoformat(),
                         '2026-07-10')

        agent_time.set_offset_minutes(330)  # IST: 00:30 next day
        self.assertEqual(agent_time.to_local(instant).date().isoformat(),
                         '2026-07-11')

    def test_config_load_applies_offset(self):
        """config.json's timezone_offset_minutes must reach agent_time.

        _apply_config_to_attributes goes on to touch install paths we don't
        have in a test env; the offset is applied early, so assert that and
        let the later AttributeError be irrelevant to this contract.
        """
        from core.config import CoreConfig

        cfg = CoreConfig.__new__(CoreConfig)
        cfg._load_authoritative_agent_id = lambda: 'id'
        cfg._load_authoritative_agent_key = lambda: 'key'
        try:
            cfg._apply_config_to_attributes({
                'agent': {
                    'agent_id': 'id',
                    'local_agent_key': 'key',
                    'timezone_offset_minutes': -300,  # US Eastern (UTC-5)
                },
                'server': {'url': 'http://localhost:5050'},
            })
        except AttributeError:
            pass  # unrelated install-path attrs, not part of this contract

        self.assertEqual(agent_time.get_offset_minutes(), -300)


if __name__ == '__main__':
    unittest.main()
