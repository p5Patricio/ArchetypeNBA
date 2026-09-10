from app.services.telegram_service import TelegramService


def test_telegram_split_message():
    service = TelegramService(bot_token="test_token", chat_id="123456")
    short_text = "Hello Telegram!"
    assert service._split_message(short_text) == [short_text]

    # Test chunking on long text
    long_line = "A" * 2500
    text = f"{long_line}\n{long_line}"
    chunks = service._split_message(text, max_length=3000)
    assert len(chunks) == 2
    assert len(chunks[0]) <= 3000
    assert len(chunks[1]) <= 3000


def test_telegram_unconfigured_behavior():
    service = TelegramService(bot_token="", chat_id="")
    assert not service.is_configured
    # Should safely return False without raising exceptions
    assert service.send_message_sync("Test") is False
