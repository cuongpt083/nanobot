import { useCallback, useEffect, useRef, useState } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchCoworkerStatus } from "@/lib/api";
import type { CoworkerParticipant, CoworkerStatus } from "@/lib/types";

const OPEN_REFRESH_INTERVAL_MS = 4000;
const ACTIVE_REFRESH_INTERVAL_MS = 3000;

/** States that mean "something is still going on" (idle/done/error/paused are settled). */
const LIVE_STATES = new Set<CoworkerParticipant["state"]>(["queued", "working", "waiting"]);

export function hasLiveParticipants(status: CoworkerStatus | null): boolean {
  return status?.participants?.some((p) => LIVE_STATES.has(p.state)) ?? false;
}

export interface UseCoworkerStatusOptions {
  /** True while the host knows work is happening (e.g. an agent turn is streaming). */
  hint?: boolean;
  /** Changing this value forces an immediate refresh (e.g. a new chat message arrived). */
  refreshKey?: string | number;
  /** Fetch once on mount / key change even when idle, so work started elsewhere shows up. */
  probe?: boolean;
}

/**
 * Polls the coworker status of a session.
 *
 * Polling runs while `open` (inspector visible) or `options.hint`, and keeps going for as long as
 * any participant is still queued / working / waiting. Once everything settles it stops after a
 * final refresh, so an idle chat costs nothing.
 */
export function useCoworkerStatus(
  open: boolean,
  token: string,
  sessionKey: string,
  options: UseCoworkerStatusOptions = {},
) {
  const { hint = false, refreshKey, probe = false } = options;
  const pageVisible = usePageVisibility();
  const [status, setStatus] = useState<CoworkerStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [liveRemainingSeconds, setLiveRemainingSeconds] = useState<number>(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;
  const enabled = open || hint || probe;

  useEffect(() => {
    if (!enabled || !pageVisible || !sessionKey) return;
    let cancelled = false;
    let loadedOnce = false;
    let refreshing = false;
    let timer: number | undefined;
    let latest: CoworkerStatus | null = null;

    const schedule = () => {
      if (cancelled) return;
      const live = hasLiveParticipants(latest);
      if (!open && !hint && !live) return; // settled: stop until something changes
      timer = window.setTimeout(
        () => void refresh(false),
        live ? ACTIVE_REFRESH_INTERVAL_MS : OPEN_REFRESH_INTERVAL_MS,
      );
    };

    const refresh = async (showLoading = false) => {
      if (refreshing) return;
      refreshing = true;
      window.clearTimeout(timer);
      if (showLoading) {
        setLoading(true);
        setLoadFailed(false);
      }
      try {
        const next = await fetchCoworkerStatus(tokenRef.current, sessionKey);
        if (cancelled) return;
        latest = next;
        setStatus(next);
        setLiveRemainingSeconds(next.caching.remaining_seconds || 0);
        setLoadFailed(false);
        loadedOnce = true;
      } catch {
        if (!cancelled && !loadedOnce) setLoadFailed(true);
      } finally {
        refreshing = false;
        if (!cancelled && showLoading) setLoading(false);
        schedule();
      }
    };

    void refresh(open);
    const refreshOnFocus = () => void refresh(false);
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [enabled, open, hint, pageVisible, sessionKey, refreshKey]);

  // Live 1-second countdown for remaining warm cache
  useEffect(() => {
    if (!open || !pageVisible || !status?.caching?.is_warm) return;
    const interval = window.setInterval(() => {
      setLiveRemainingSeconds((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => window.clearInterval(interval);
  }, [open, pageVisible, status?.caching?.is_warm]);

  /** Adopt a status returned by a mutation so the UI reflects it without waiting for the next poll. */
  const applyStatus = useCallback((next: CoworkerStatus) => {
    setStatus(next);
    setLiveRemainingSeconds(next.caching.remaining_seconds || 0);
  }, []);

  return {
    status,
    applyStatus,
    loading,
    loadFailed,
    liveRemainingSeconds,
  };
}
