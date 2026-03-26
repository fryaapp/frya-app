import pytest

from app.connectors.notifications_telegram import TelegramConnector


@pytest.mark.asyncio
async def test_telegram_without_token_is_explicit():
    connector = TelegramConnector(bot_token=None)
    result = await connector.send(type('Msg', (), {'target': '1', 'text': 'x', 'metadata': None})())
    assert result['ok'] is False
    assert result['reason'] == 'telegram_bot_token_missing'
