import { useState } from "react";

import { CoworkerInspectorPopover } from "@/components/coworker/CoworkerInspectorPopover";
import { CoworkerParticipantsStrip } from "@/components/coworker/CoworkerParticipants";
import { useCoworkerStatus } from "@/hooks/useCoworkerStatus";

interface CoworkerHeaderControlsProps {
  sessionKey: string;
  token: string;
  /** An agent turn is streaming right now. */
  turnActive?: boolean;
  /** Changes when a harness-driven message (`[auto-…]`) arrives, forcing a refresh. */
  refreshKey?: string | number;
}

/**
 * Header cluster: the participants strip plus the inspector it opens.
 * Owns the single status poll that both share.
 */
export function CoworkerHeaderControls({
  sessionKey,
  token,
  turnActive = false,
  refreshKey,
}: CoworkerHeaderControlsProps) {
  const [open, setOpen] = useState(false);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const feed = useCoworkerStatus(open, token, sessionKey, {
    hint: turnActive,
    refreshKey,
    probe: true,
  });

  return (
    <>
      <CoworkerParticipantsStrip
        participants={feed.status?.participants}
        onSelect={(participant) => {
          setHighlightId(participant.id);
          setOpen(true);
        }}
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
