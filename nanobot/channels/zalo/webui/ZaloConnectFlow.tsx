import { useTranslation } from "react-i18next";

import {
  channelTranslator,
  type ChannelTranslator,
} from "@/channel-plugins/i18n";
import type { ChannelPluginConnectFlowProps } from "@/channel-plugins/types";
import { ChannelQrConnectFlow } from "@/components/settings/channels/ChannelQrConnectFlow";
import type { ChannelConnectPayload } from "@/lib/types";

function zaloConnectMessage(
  payload: ChannelConnectPayload,
  tx: ChannelTranslator,
): string {
  if (payload.status === "succeeded") {
    return tx("custom.connected", "Zalo is connected.");
  }
  if (payload.status === "expired") {
    return tx("custom.expired", "Zalo login expired. Scan again to reconnect.");
  }
  if (payload.status === "failed") {
    return payload.message
      ?? tx("custom.failed", "Unable to connect Zalo. Try again.");
  }
  if (payload.status === "cancelled") {
    return tx("custom.stopped", "Zalo login stopped.");
  }
  return tx("custom.waiting", "Waiting for Zalo scan...");
}

export function ZaloConnectFlow({
  token,
  feature,
  idleLabel,
  connectRequestId,
  onFeaturesUpdate,
}: ChannelPluginConnectFlowProps) {
  const { t } = useTranslation();
  const tx = channelTranslator(t, "zalo");
  const scanAgainLabel = t("settings.channels.scanAgain", {
    defaultValue: "Scan again",
  });

  return (
    <ChannelQrConnectFlow
      token={token}
      channelName="zalo"
      idleLabel={idleLabel}
      connectRequestId={connectRequestId}
      forceOnRepeat
      onFeaturesUpdate={onFeaturesUpdate}
      resolveMessage={(payload) => zaloConnectMessage(payload, tx)}
      suppressSucceeded={feature.runtime_status === "failed"}
      labels={{
        qrAlt: tx("custom.qrAlt", "Zalo login QR code"),
        scanTitle: tx("custom.scanTitle", "Scan with Zalo"),
        scanDescription: tx(
          "custom.scanDescription",
          "Use the Zalo app on your phone to scan this code. nanobot saves the account session locally after login.",
        ),
        waiting: tx("custom.waiting", "Waiting for Zalo scan..."),
        connected: tx("custom.connected", "Zalo is connected."),
        stopped: tx("custom.stopped", "Zalo login stopped."),
        connecting: tx("custom.connecting", "Connecting..."),
        scanAgain: scanAgainLabel,
        connect: t("settings.channels.connect", { defaultValue: "Connect" }),
      }}
    />
  );
}
