"""F10: reply links between cached messages of one channel; IDs only, never bodies."""

import discord


def reply_target(message: object, guild_id: int, channel_id: int) -> int | None:
    """The replied-to message ID only when Discord says it is in this Guild and channel."""
    if getattr(message, "type", None) is not discord.MessageType.reply:
        return None
    reference = getattr(message, "reference", None)
    target = getattr(reference, "message_id", None)
    if (
        type(target) is not int or not 0 < target < getattr(message, "id", 0)
        or getattr(reference, "channel_id", None) != channel_id
        or getattr(reference, "guild_id", None) not in (None, guild_id)
    ):
        return None
    return target
