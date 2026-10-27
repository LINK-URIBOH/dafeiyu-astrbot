"""Exercise real quiet-hour and unanswered gates without sending messages."""
import asyncio
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo
from data.plugins.astrbot_plugin_proactive_chat.utils import time_utils
from data.plugins.astrbot_plugin_proactive_chat.core.features.gating_feature import GatingStage

async def main():
    hours = {}
    for hour, expected in [(0, True), (7, True), (8, False), (22, False), (23, True)]:
        with patch.object(time_utils, 'datetime') as clock:
            clock.now.return_value = datetime(2026, 10, 26, hour, tzinfo=ZoneInfo('Asia/Shanghai'))
            actual = time_utils.is_quiet_time('23-8', ZoneInfo('Asia/Shanghai'))
            assert actual == expected
            hours[str(hour)] = actual
    cfg = {'schedule_settings': {'max_unanswered_times': 2}}
    plugin = SimpleNamespace(data_lock=asyncio.Lock(), session_data={}, telemetry=None,
        config_service=SimpleNamespace(get_session_config=lambda _: cfg),
        session_service=SimpleNamespace(get_session_log_str=lambda *args: 'synthetic-test-session'))
    orchestrator = SimpleNamespace(plugin=plugin, is_chat_allowed=AsyncMock(return_value=(True, '')))
    stage = GatingStage(orchestrator)
    cases = {}
    for count, expected in [(0, 'CONTINUE'), (1, 'CONTINUE'), (2, 'STOP')]:
        plugin.session_data['test'] = {'unanswered_count': count}
        ctx = SimpleNamespace(session_id='test', abort=lambda _: None)
        result = await stage.handle(ctx)
        assert result.name == expected
        cases[str(count)] = result.name
    orchestrator.is_chat_allowed.return_value = (False, 'quiet_hours')
    result = await stage.handle(SimpleNamespace(session_id='test', abort=lambda _: None))
    assert result.name == 'RESCHEDULE'
    result = {'ok': True, 'quiet_hour_cases': hours, 'unanswered_count_cases': cases, 'quiet_gate': result.name}
    Path('/AstrBot/data/proactive-validation.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))

asyncio.run(main())
