import { lazy } from "react";

import type { ChannelUiContribution } from "@/channel-plugins/types";
import { chatAppGuideUrl } from "@/components/settings/channels/catalog";

const ZaloConnectFlow = lazy(() =>
  import("./ZaloConnectFlow").then(({ ZaloConnectFlow: component }) => ({
    default: component,
  })),
);

export default {
  ConnectFlow: ZaloConnectFlow,
  canConnectBeforeConfigured: true,
  presentation: {
    displayName: "Zalo",
    initials: "ZL",
    color: "#0068FF",
    logoUrl: "https://cdn.simpleicons.org/zalo",
    setup: {
      mode: "connect",
      command: "nanobot channels login zalo",
      docsUrl: chatAppGuideUrl("zalo"),
      fields: [
        { key: "channels.zalo.allowFrom" },
        { key: "channels.zalo.groupPolicy" },
      ],
    },
  },
} satisfies ChannelUiContribution;
