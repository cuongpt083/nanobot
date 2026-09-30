import { useEffect, useRef, useState } from "react";

import { usePageVisibility } from "@/hooks/usePageVisibility";
import { fetchCoworkerStatus } from "@/lib/api";
import type { CoworkerStatus } from "@/lib/types";

const REFRESH_INTERVAL_MS = 4000;

export function useCoworkerStatus(open: boolean, token: string, sessionKey: string) {
  const pageVisible = usePageVisibility();
  const [status, setStatus] = useState<CoworkerStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const [liveRemainingSeconds, setLiveRemainingSeconds] = useState<number>(0);
  const tokenRef = useRef(token);
  tokenRef.current = token;

  useEffect(() => {
    if (!open || !pageVisible || !sessionKey) return;
    let cancelled = false;
    let loadedOnce = false;
    let refreshing = false;

    const refresh = async (showLoading = false) => {
      if (refreshing) return;
      refreshing = true;
      if (showLoading) {
        setLoading(true);
        setLoadFailed(false);
      }
      try {
        const next = await fetchCoworkerStatus(tokenRef.current, sessionKey);
        if (cancelled) return;
        setStatus(next);
        setLiveRemainingSeconds(next.caching.remaining_seconds || 0);
        setLoadFailed(false);
        loadedOnce = true;
      } catch {
        if (!cancelled && !loadedOnce) setLoadFailed(true);
      } finally {
        refreshing = false;
        if (!cancelled && showLoading) setLoading(false);
      }
    };

    void refresh(true);
    const refreshId = window.setInterval(() => void refresh(false), REFRESH_INTERVAL_MS);
    const refreshOnFocus = () => void refresh(false);
    window.addEventListener("focus", refreshOnFocus);
    return () => {
      cancelled = true;
      window.clearInterval(refreshId);
      window.removeEventListener("focus", refreshOnFocus);
    };
  }, [open, pageVisible, sessionKey]);

  // Live 1-second countdown for remaining warm cache
  useEffect(() => {
    if (!open || !pageVisible || !status?.caching?.is_warm) return;
    const interval = window.setInterval(() => {
      setLiveRemainingSeconds((prev) => (prev > 0 ? prev - 1 : 0));
    }, 1000);
    return () => window.clearInterval(interval);
  }, [open, pageVisible, status?.caching?.is_warm]);

  return {
    status,
    loading,
    loadFailed,
    liveRemainingSeconds,
  };
}
