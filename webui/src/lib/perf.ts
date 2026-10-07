/**
 * Flag-gated performance recorder for desktop/WebUI baseline measurements.
 * Enabled only when `localStorage.getItem("nanobot_perf_record") === "1"`.
 * All exports are completely inactive / zero-overhead when disabled.
 */

export interface DesktopPerfSnapshot {
  enabled: boolean;
  timeOrigin: number;
  marks: Record<string, number>;
  measures: Record<string, number>;
  fpsSampler: {
    active: boolean;
    sampleCount: number;
    meanFps: number | null;
    p1Fps: number | null;
  };
  longTasksCount: number;
  maxLongTaskDurationMs: number;
}

class DesktopPerfMonitor {
  private enabled: boolean;
  private marks: Map<string, number> = new Map();
  private measures: Map<string, number> = new Map();
  private frameTimestamps: number[] = [];
  private rafHandle: number | null = null;
  private isSamplingFps = false;
  private longTasksCount = 0;
  private maxLongTaskDurationMs = 0;
  private longTaskObserver: PerformanceObserver | null = null;

  constructor() {
    this.enabled =
      typeof window !== "undefined" &&
      typeof window.localStorage !== "undefined" &&
      window.localStorage.getItem("nanobot_perf_record") === "1";

    if (this.enabled) {
      this.initLongTaskObserver();
      this.exposeGlobal();
    }
  }

  public isEnabled(): boolean {
    return this.enabled;
  }

  public mark(name: string): void {
    if (!this.enabled || typeof performance === "undefined") return;
    const now = performance.now();
    this.marks.set(name, now);
    try {
      performance.mark(name);
    } catch {
      // ignore
    }
  }

  public measure(name: string, startMark: string, endMark?: string): void {
    if (!this.enabled || typeof performance === "undefined") return;
    const start = this.marks.get(startMark);
    const end = endMark ? this.marks.get(endMark) : performance.now();
    if (start !== undefined && end !== undefined) {
      const duration = end - start;
      this.measures.set(name, duration);
      try {
        if (endMark) {
          performance.measure(name, startMark, endMark);
        } else {
          performance.measure(name, startMark);
        }
      } catch {
        // ignore
      }
    }
  }

  public startFpsSampling(): void {
    if (!this.enabled || this.isSamplingFps || typeof requestAnimationFrame === "undefined") return;
    this.isSamplingFps = true;
    this.frameTimestamps = [];

    const onFrame = (now: number) => {
      if (!this.isSamplingFps) return;
      this.frameTimestamps.push(now);
      this.rafHandle = requestAnimationFrame(onFrame);
    };

    this.rafHandle = requestAnimationFrame(onFrame);
  }

  public stopFpsSampling(): { meanFps: number | null; p1Fps: number | null } {
    if (!this.enabled || !this.isSamplingFps) {
      return { meanFps: null, p1Fps: null };
    }
    this.isSamplingFps = false;
    if (this.rafHandle !== null && typeof cancelAnimationFrame === "undefined") {
      // ignore
    } else if (this.rafHandle !== null) {
      cancelAnimationFrame(this.rafHandle);
      this.rafHandle = null;
    }

    if (this.frameTimestamps.length < 2) {
      return { meanFps: null, p1Fps: null };
    }

    const deltas: number[] = [];
    for (let i = 1; i < this.frameTimestamps.length; i++) {
      deltas.push(this.frameTimestamps[i] - this.frameTimestamps[i - 1]);
    }

    // Convert deltas (ms) to instantaneous FPS
    const fpsList = deltas.filter((d) => d > 0).map((d) => 1000 / d);
    if (fpsList.length === 0) {
      return { meanFps: null, p1Fps: null };
    }

    fpsList.sort((a, b) => a - b);
    const meanFps = Math.round(fpsList.reduce((acc, f) => acc + f, 0) / fpsList.length);
    // 1st percentile (p1) lowest FPS
    const p1Index = Math.max(0, Math.floor(fpsList.length * 0.01));
    const p1Fps = Math.round(fpsList[p1Index]);

    return { meanFps, p1Fps };
  }

  private initLongTaskObserver(): void {
    if (typeof PerformanceObserver === "undefined") return;
    try {
      this.longTaskObserver = new PerformanceObserver((entryList) => {
        for (const entry of entryList.getEntries()) {
          this.longTasksCount++;
          if (entry.duration > this.maxLongTaskDurationMs) {
            this.maxLongTaskDurationMs = entry.duration;
          }
        }
      });
      this.longTaskObserver.observe({ entryTypes: ["longtask"] });
    } catch {
      // Long Tasks API not supported or restricted in this environment
    }
  }

  public dump(): DesktopPerfSnapshot {
    const fps = this.isSamplingFps ? this.stopFpsSampling() : { meanFps: null, p1Fps: null };
    const snapshot: DesktopPerfSnapshot = {
      enabled: this.enabled,
      timeOrigin: typeof performance !== "undefined" ? performance.timeOrigin : 0,
      marks: Object.fromEntries(this.marks.entries()),
      measures: Object.fromEntries(this.measures.entries()),
      fpsSampler: {
        active: this.isSamplingFps,
        sampleCount: this.frameTimestamps.length,
        meanFps: fps.meanFps,
        p1Fps: fps.p1Fps,
      },
      longTasksCount: this.longTasksCount,
      maxLongTaskDurationMs: this.maxLongTaskDurationMs,
    };
    if (typeof console !== "undefined") {
      console.log("[nanobot-perf] Baseline Snapshot:", JSON.stringify(snapshot, null, 2));
    }
    return snapshot;
  }

  private exposeGlobal(): void {
    if (typeof window !== "undefined") {
      (window as unknown as { __nanobotPerf?: unknown }).__nanobotPerf = {
        dump: () => this.dump(),
        mark: (name: string) => this.mark(name),
        measure: (name: string, start: string, end?: string) => this.measure(name, start, end),
        startFpsSampling: () => this.startFpsSampling(),
        stopFpsSampling: () => this.stopFpsSampling(),
        enable: () => {
          window.localStorage.setItem("nanobot_perf_record", "1");
          console.log("[nanobot-perf] Flag enabled. Please reload page.");
        },
        disable: () => {
          window.localStorage.removeItem("nanobot_perf_record");
          console.log("[nanobot-perf] Flag disabled.");
        },
      };
    }
  }
}

export const desktopPerf = new DesktopPerfMonitor();
