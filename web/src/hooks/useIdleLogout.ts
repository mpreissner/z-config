import { useEffect, useRef, useCallback, useState } from "react";

const WARN_BEFORE_MS = 2 * 60 * 1000;
const WARN_SECONDS = Math.round(WARN_BEFORE_MS / 1000);
const ACTIVITY_THROTTLE_MS = 5_000;

export function useIdleLogout(active: boolean, logout: () => void, idleMinutes: number = 15) {
  const idleMs = idleMinutes * 60 * 1000;

  const [showWarning, setShowWarning] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(WARN_SECONDS);

  const warnTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const logoutTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const countdown = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastActivity = useRef(0);
  const idleMsRef = useRef(idleMs);
  idleMsRef.current = idleMs;

  const clearAll = useCallback(() => {
    if (warnTimer.current)   { clearTimeout(warnTimer.current);    warnTimer.current   = null; }
    if (logoutTimer.current) { clearTimeout(logoutTimer.current);  logoutTimer.current = null; }
    if (countdown.current)   { clearInterval(countdown.current);   countdown.current   = null; }
  }, []);

  const arm = useCallback(() => {
    clearAll();
    setShowWarning(false);

    warnTimer.current = setTimeout(() => {
      setShowWarning(true);
      setSecondsLeft(WARN_SECONDS);
      countdown.current = setInterval(() => {
        setSecondsLeft((s) => Math.max(0, s - 1));
      }, 1000);
    }, idleMsRef.current - WARN_BEFORE_MS);

    logoutTimer.current = setTimeout(logout, idleMsRef.current);
  }, [clearAll, logout]);

  const onActivity = useCallback((e: Event) => {
    // Reject synthetic/programmatic events — only genuine user input resets the clock.
    if (!e.isTrusted) return;
    const now = Date.now();
    if (now - lastActivity.current < ACTIVITY_THROTTLE_MS) return;
    lastActivity.current = now;
    arm();
  }, [arm]);

  // Called from the "Stay logged in" button — bypasses throttle.
  const extend = useCallback(() => {
    lastActivity.current = 0;
    arm();
  }, [arm]);

  useEffect(() => {
    if (!active) {
      clearAll();
      setShowWarning(false);
      return;
    }
    lastActivity.current = 0;
    arm();

    // mousemove is intentionally omitted: trackpads emit continuous move events
    // from vibration or incidental contact, which would silently reset the timer.
    // mousedown and click already cover all intentional mouse interactions.
    const events = ["keydown", "mousedown", "touchstart", "scroll", "click"] as const;
    events.forEach((e) => window.addEventListener(e, onActivity, { passive: true }));
    return () => {
      events.forEach((e) => window.removeEventListener(e, onActivity));
      clearAll();
    };
  }, [active, arm, onActivity, clearAll]);

  return { showWarning, secondsLeft, extend };
}
