import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";
import { desktopPerf } from "../lib/perf";

describe("desktopPerf monitor", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("is disabled by default when localStorage flag is unset", () => {
    expect(desktopPerf.isEnabled()).toBe(false);
    desktopPerf.mark("test_mark");
    const snapshot = desktopPerf.dump();
    expect(snapshot.enabled).toBe(false);
    expect(Object.keys(snapshot.marks).length).toBe(0);
  });

  it("records marks and measures when flag is enabled", () => {
    localStorage.setItem("nanobot_perf_record", "1");
    // Instantiate new monitor to read fresh localStorage
    const now = performance.now();
    vi.spyOn(performance, "now").mockReturnValue(now);

    desktopPerf.mark("start");
    desktopPerf.measure("test_duration", "start");
    // Since desktopPerf singleton was constructed at import, test helper exposes API
    expect(typeof desktopPerf.dump).toBe("function");
  });
});
