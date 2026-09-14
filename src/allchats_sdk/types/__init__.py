"""Internal media / metadata helpers used by providers.

Not part of the stable public API. Import from concrete modules::

    from allchats_sdk.types.media import MESSAGE_TYPE_PHOTO
    from allchats_sdk.types.voice import MESSAGE_TYPE_VOICE

Layout is already a package because helpers outgrew a single file.
Do not split further until a module itself becomes hard to navigate.
"""

from __future__ import annotations

__all__: list[str] = []
