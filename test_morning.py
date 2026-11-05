import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import main


class MorningPauseTest(unittest.IsolatedAsyncioTestCase):
    async def test_paused_job_sends_nothing(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(main, "MORNING_ENABLED", False):
            await main.morning_job(SimpleNamespace(bot=bot))
        bot.send_message.assert_not_awaited()

    async def test_enabled_job_can_be_restored(self):
        bot = SimpleNamespace(send_message=AsyncMock())
        with patch.object(main, "MORNING_ENABLED", True):
            await main.morning_job(SimpleNamespace(bot=bot))
        self.assertEqual(bot.send_message.await_count, len(main.MORNING_RECIPIENTS))

    def test_only_morning_schedule_is_paused(self):
        for enabled in (False, True):
            builder = Mock()
            builder.token.return_value = builder
            builder.connect_timeout.return_value = builder
            builder.read_timeout.return_value = builder
            builder.write_timeout.return_value = builder
            builder.pool_timeout.return_value = builder
            app = builder.build.return_value
            with patch.object(main, "MORNING_ENABLED", enabled), patch.object(
                main, "BOT_TOKEN", "test"
            ), patch.object(main, "ApplicationBuilder", return_value=builder), patch.object(main.db, "init_db"):
                main.main()
            jobs = [call.kwargs["name"] for call in app.job_queue.run_daily.call_args_list]
            self.assertEqual(jobs, ["morning", "milestones"] if enabled else ["milestones"])
            app.run_polling.assert_called_once()


if __name__ == "__main__":
    unittest.main()
