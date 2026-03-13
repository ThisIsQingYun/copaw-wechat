import asyncio
import logging

from wecom.channel import WeComChannel
from wecom.config import WeComConfig


def test_send_warns_when_no_delivery_path(caplog):
    async def run_case():
        config = WeComConfig.from_mapping({'bot_id': 'bot_123', 'secret': 'secret_456'})
        channel = WeComChannel(process=None, config=config)

        with caplog.at_level(logging.WARNING):
            command = await channel.send('chat_1', 'hello', {'req_id': 'req_1'})

        messages = [record.getMessage() for record in caplog.records]
        assert command['cmd'] == 'aibot_respond_msg'
        assert any('wecom outbound command not sent' in message for message in messages)

    asyncio.run(run_case())
