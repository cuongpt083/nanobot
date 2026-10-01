import { useEffect, useState } from "react";

import { CoworkerAdvisorControl } from "@/components/coworker/CoworkerAdvisorControl";
import { CoworkerInspectorPopover } from "@/components/coworker/CoworkerInspectorPopover";
import { CoworkerParticipantsStrip } from "@/components/coworker/CoworkerParticipants";
import { useCoworkerStatus } from "@/hooks/useCoworkerStatus";
import type { WebUIMutationTransport } from "@/lib/api";
import type { CoworkerMention } from "@/lib/types";

interface CoworkerHeaderControlsProps {
  client: WebUIMutationTransport;
  sessionKey: string;
  token: string;
  /** An agent turn is streaming right now. */
  turnActive?: boolean;
  /** Changes when a harness-driven message (`[auto-…]`) arrives, forcing a refresh. */
  refreshKey?: string | number;
  /** Names the composer can offer after "@" (coding agents, teammates, advisor). */
  onMentionsChange?: (mentions: CoworkerMention[]) => void;
}

/**
 * Header cluster: the participants strip plus the inspector it opens.
 * Owns the single status poll that both share.
 */
export function CoworkerHeaderControls({
  client,
  sessionKey,
  token,
  turnActive = false,
  refreshKey,
  onMentionsChange,
}: CoworkerHeaderControlsProps) {
  const [open, setOpen] = useState(false);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const feed = useCoworkerStatus(open, token, sessionKey, {
    hint: turnActive,
    refreshKey,
    probe: true,
  });
  const mentions = feed.status?.mentions;
  useEffect(() => {
    if (mentions) onMentionsChange?.(mentions);
  }, [mentions, onMentionsChange]);

  return (
    <>
      <CoworkerParticipantsStrip
        participants={feed.status?.participants}
        reviewNudge={feed.status?.advisor?.review_nudge}
        onSelect={(participant) => {
          setHighlightId(participant.id);
          setOpen(true);
        }}
      />
      <CoworkerAdvisorControl
        client={client}
        sessionKey={sessionKey}
        token={token}
        status={feed.status}
        onStatus={feed.applyStatus}
      />
      <CoworkerInspectorPopover
        sessionKey={sessionKey}
        token={token}
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (!next) setHighlightId(null);
        }}
        feed={feed}
        highlightId={highlightId}
      />
    </>
  );
}
