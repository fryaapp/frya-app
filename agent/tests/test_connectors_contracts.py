import pytest

from app.connectors.accounting_akaunting import AkauntingConnector
from app.connectors.notifications_telegram import TelegramConnector


@pytest.mark.asyncio
async def test_akaunting_stub_returns_safe_response():
    connector = AkauntingConnector('http://akaunting.local', token=None)
    result = await connector.create_booking_draft({'amount': 10})
    assert result['status'] == 'stub'


@pytest.mark.asyncio
async def test_telegram_without_token_is_explicit():
    connector = TelegramConnector(bot_token=None)
    result = await connector.send(type('Msg', (), {'target': '1', 'text': 'x', 'metadata': None})())
    assert result['ok'] is False
    assert result['reason'] == 'telegram_bot_token_missing'
