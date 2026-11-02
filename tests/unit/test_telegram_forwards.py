from types import SimpleNamespace

from allchats_sdk.providers.telegram.forwards import extract_telegram_forward_meta


def test_extract_forward_none_without_header() -> None:
    assert extract_telegram_forward_meta(SimpleNamespace()) is None


def test_extract_forward_from_name() -> None:
    message = SimpleNamespace(
        fwd_from=SimpleNamespace(
            from_name="Alice",
            post_author="",
            channel_post=None,
            saved_from_peer=None,
        ),
    )
    meta = extract_telegram_forward_meta(message)
    assert meta == {"is_forwarded": True, "from_name": "Alice"}
