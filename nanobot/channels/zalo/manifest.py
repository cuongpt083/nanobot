"""Zalo management contract."""

from nanobot.channels._manifest import DIRECT_GROUP_POLICIES, field
from nanobot.channels.contracts import ChannelManagementSpec, ChannelSetupSpec
from nanobot.channels.plugin import ChannelPlugin
from nanobot.channels.zalo.state import local_state_present
from nanobot.channels.zalo.validation import validate

SETUP_SPEC = ChannelSetupSpec(
    fields={
        "allowFrom": field("list"),
        "groupPolicy": field(
            "enum",
            choices=DIRECT_GROUP_POLICIES,
            default="mention",
        ),
        "stateDir": field(writable=False, snapshot=False),
        "nodePath": field(writable=False, snapshot=False),
    },
    official_url="https://zalo.me/",
    validator=validate,
)

PLUGIN = ChannelPlugin(
    name="zalo",
    display_name="Zalo",
    runtime=f"{__package__}.runtime:ZaloChannel",
    connector=f"{__package__}.connect:ZaloConnectStore",
    setup=SETUP_SPEC,
    management=ChannelManagementSpec(local_state_present=local_state_present),
    dependencies=("segno>=1.6.1,<2.0.0",),
    webui="webui/index.tsx",
)
