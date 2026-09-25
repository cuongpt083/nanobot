"""Zalo management contract."""

from nanobot.channels._manifest import GROUP_POLICIES, field
from nanobot.channels.contracts import ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.zalo.validation import validate

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "bridgeUrl": field(default="ws://127.0.0.1:3002"),
        "bridgeToken": field("secret"),
        "allowFrom": field("list"),
        "groupPolicy": field(
            "enum",
            choices=GROUP_POLICIES,
            default="mention",
        ),
        "groupAllowFrom": field("list"),
        "botUserId": field(),
        "botName": field(),
        "replyWithQuote": field("bool", default=True),
    },
    official_url="https://zalo.me/",
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="zalo",
    display_name="Zalo",
    runtime=f"{__package__}.runtime:ZaloChannel",
    setup=SETUP_SPEC,
    dependencies=(),
)
