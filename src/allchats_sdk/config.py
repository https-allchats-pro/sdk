"""Application config duck-types.

The host application passes its own Settings object. SDK code only reads
messenger-related attributes (telegram, vk, avito, whatsapp, discord, ...).
"""

from typing import Any

Settings = Any
TelegramProxySettings = Any
