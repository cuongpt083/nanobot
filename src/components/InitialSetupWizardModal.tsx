import React, { useState, useEffect, useRef } from 'react';
import {
  Sparkles,
  CheckCircle2,
  AlertCircle,
  Loader2,
  Terminal,
  FolderTree,
  FileCode,
  Layers,
  Cpu,
  RefreshCw,
  X,
  ExternalLink,
  ChevronDown,
  ChevronUp,
  Copy,
  Check,
  PlayCircle
} from 'lucide-react';
import { SetupStepItem, SetupStatusResponse } from '../types';

interface InitialSetupWizardModalProps {
  isOpen: boolean;
  onClose: () => void;
  onSetupCompleted?: () => void;
}

export const InitialSetupWizardModal: React.FC<InitialSetupWizardModalProps> = ({
  isOpen,
  onClose,
  onSetupCompleted,
}) => {
  const [loadingStatus, setLoadingStatus] = useState<boolean>(true);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [statusData, setStatusData] = useState<SetupStatusResponse | null>(null);
  const [steps, setSteps] = useState<SetupStepItem[]>([]);
  const [logs, setLogs] = useState<string[]>([]);
  const [isLogExpanded, setIsLogExpanded] = useState<boolean>(true);
  const [copiedLog, setCopiedLog] = useState<boolean>(false);
  const logEndRef = useRef<HTMLDivElement>(null);

  // Fetch initial setup status
  const fetchStatus = async () => {
    setLoadingStatus(true);
    try {
      if (window.nanobotDesktop?.setup?.getStatus) {
        const data = await window.nanobotDesktop.setup.getStatus();
        setStatusData(data);
        setSteps(data.steps || []);
      } else {
        const res = await fetch('/api/setup/status');
        if (res.ok) {
          const data = await res.json();
          setStatusData(data);
          setSteps(data.steps || []);
        }
      }
    } catch (err: any) {
      console.warn('[SetupWizard] Could not fetch setup status:', err.message);
    } finally {
      setLoadingStatus(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchStatus();
    }
  }, [isOpen]);

  // Subscribe to progress events from desktop IPC if available
  useEffect(() => {
    if (window.nanobotDesktop?.setup?.onProgress) {
      const unsubscribe = window.nanobotDesktop.setup.onProgress((event) => {
        if (event.step) {
          setSteps((prev) =>
            prev.map((s) => (s.id === event.stepId ? { ...s, ...event.step } : s)),
          );
        }
        if (event.log) {
          setLogs((prev) => [...prev, `[${new Date().toLocaleTimeString()}] ${event.log}`]);
        }
      });
      return () => unsubscribe();
    }
  }, []);

  // Auto scroll terminal logs
  useEffect(() => {
    if (isLogExpanded && logEndRef.current) {
      logEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [logs, isLogExpanded]);

  // Run full setup sequence
  const handleStartSetup = async (forceReinstall = false) => {
    setIsRunning(true);
    setLogs([`[${new Date().toLocaleTimeString()}] Bắt đầu tiến trình thiết lập môi trường Nanobot...`]);

    // Reset steps to pending/running
    setSteps((prev) =>
      prev.map((s, idx) => ({
        ...s,
        status: idx === 0 ? 'running' : 'pending',
        details: undefined,
        error: undefined,
      })),
    );

    try {
      let resultData: any = null;
      if (window.nanobotDesktop?.setup?.runSetup) {
        resultData = await window.nanobotDesktop.setup.runSetup({ forceReinstall });
      } else {
        const res = await fetch('/api/setup/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ forceReinstall }),
        });
        resultData = await res.json();
      }

      if (resultData) {
        if (Array.isArray(resultData.steps)) {
          setSteps(resultData.steps);
        }
        if (Array.isArray(resultData.logs)) {
          setLogs((prev) => [...prev, ...resultData.logs]);
        }
      }

      await fetchStatus();
      if (onSetupCompleted) {
        onSetupCompleted();
      }
    } catch (err: any) {
      setLogs((prev) => [...prev, `[LỖI] Quá trình thiết lập gặp sự cố: ${err.message}`]);
    } finally {
      setIsRunning(false);
    }
  };

  const handleCopyLogs = () => {
    navigator.clipboard.writeText(logs.join('\n'));
    setCopiedLog(true);
    setTimeout(() => setCopiedLog(false), 2000);
  };

  if (!isOpen) return null;

  const completedCount = steps.filter((s) => s.status === 'completed').length;
  const totalCount = steps.length || 6;
  const isAllCompleted = completedCount === totalCount && totalCount > 0;
  const hasErrors = steps.some((s) => s.status === 'error');

  const getStepIcon = (id: string) => {
    switch (id) {
      case 'check_python':
        return <Cpu className="w-4 h-4 text-sky-400" />;
      case 'create_directories':
        return <FolderTree className="w-4 h-4 text-amber-400" />;
      case 'setup_venv':
        return <Layers className="w-4 h-4 text-emerald-400" />;
      case 'create_scripts':
        return <Terminal className="w-4 h-4 text-indigo-400" />;
      case 'init_config':
        return <FileCode className="w-4 h-4 text-pink-400" />;
      case 'verify_gateway':
        return <Sparkles className="w-4 h-4 text-amber-400" />;
      default:
        return <Layers className="w-4 h-4 text-zinc-400" />;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-in fade-in duration-200">
      <div className="bg-zinc-900 border border-zinc-700/80 rounded-2xl w-full max-w-3xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-zinc-800 flex items-center justify-between bg-zinc-950/80">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-amber-500/20 border border-amber-500/40 flex items-center justify-center text-amber-400 shadow-sm">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-base font-bold text-zinc-100">
                  Cài đặt Môi trường & Dependencies Nanobot
                </h2>
                <span className="px-2 py-0.5 rounded text-[10px] font-mono font-medium bg-zinc-800 text-zinc-300 border border-zinc-700">
                  HOME/.nanobot
                </span>
              </div>
              <p className="text-xs text-zinc-400 mt-0.5">
                Tự động khởi tạo thư mục chuẩn, scripts launcher, Python venv và workspace mặc định.
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800 transition-colors cursor-pointer"
            title="Đóng cửa sổ"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 space-y-5 overflow-y-auto flex-1 text-xs">
          {/* Target Location Card */}
          <div className="p-3.5 rounded-xl bg-zinc-950/60 border border-zinc-800/80 flex items-center justify-between">
            <div className="space-y-1">
              <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
                Vị trí cài đặt hệ thống (Current Home Directory):
              </div>
              <div className="font-mono text-zinc-200 text-xs flex items-center gap-2">
                <span className="text-amber-400 font-semibold">{statusData?.nanobotDir || '~/.nanobot'}</span>
                <span className="text-zinc-500">•</span>
                <span className="text-zinc-400">Workspace: {statusData?.workspaceDir || '~/.nanobot/workspace'}</span>
              </div>
            </div>

            {statusData?.detectedPython?.found && (
              <span className="px-2.5 py-1 rounded-md bg-emerald-950/60 border border-emerald-800/80 text-emerald-300 font-mono text-[11px] flex items-center gap-1.5">
                <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                <span>Python {statusData.detectedPython.version}</span>
              </span>
            )}
          </div>

          {/* Progress Bar */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between text-zinc-400 text-xs">
              <span className="font-medium">Tiến độ thiết lập các thành phần:</span>
              <span className="font-mono text-amber-400 font-bold">
                {completedCount} / {totalCount} bước hoàn tất
              </span>
            </div>
            <div className="w-full bg-zinc-950 rounded-full h-2 overflow-hidden border border-zinc-800">
              <div
                className="h-full bg-gradient-to-r from-amber-500 to-emerald-400 transition-all duration-500 rounded-full"
                style={{ width: `${(completedCount / totalCount) * 100}%` }}
              />
            </div>
          </div>

          {/* Steps List */}
          <div className="space-y-2.5">
            {steps.map((step, idx) => {
              const isStepRunning = step.status === 'running';
              const isStepDone = step.status === 'completed';
              const isStepError = step.status === 'error';

              return (
                <div
                  key={step.id}
                  className={`p-3 rounded-xl border transition-all ${
                    isStepRunning
                      ? 'bg-amber-950/20 border-amber-500/60 shadow-xs'
                      : isStepDone
                      ? 'bg-zinc-950/70 border-zinc-800 hover:border-zinc-700'
                      : isStepError
                      ? 'bg-rose-950/20 border-rose-800/80'
                      : 'bg-zinc-950/40 border-zinc-800/60 opacity-80'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-start gap-3 flex-1">
                      <div className="mt-0.5 p-1.5 rounded-lg bg-zinc-900 border border-zinc-800">
                        {getStepIcon(step.id)}
                      </div>
                      <div className="space-y-0.5 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="font-bold text-zinc-100">{step.title}</span>
                          <span className="text-[10px] text-zinc-500 font-mono">
                            Bước {idx + 1}/6
                          </span>
                        </div>
                        <p className="text-[11px] text-zinc-400 leading-relaxed">
                          {step.description}
                        </p>
                        {step.details && (
                          <div className="text-[11px] text-emerald-400/90 font-mono mt-1 flex items-center gap-1.5">
                            <Check className="w-3 h-3 text-emerald-400" />
                            <span>{step.details}</span>
                          </div>
                        )}
                        {step.error && (
                          <div className="text-[11px] text-rose-400 font-mono mt-1 flex items-center gap-1.5">
                            <AlertCircle className="w-3 h-3 text-rose-400" />
                            <span>{step.error}</span>
                          </div>
                        )}
                      </div>
                    </div>

                    {/* Step Status Badge */}
                    <div className="flex-shrink-0">
                      {isStepRunning && (
                        <span className="px-2.5 py-1 rounded-md bg-amber-500/20 text-amber-300 font-medium text-[11px] flex items-center gap-1.5 border border-amber-500/40 animate-pulse">
                          <Loader2 className="w-3 h-3 animate-spin" />
                          <span>Đang chạy...</span>
                        </span>
                      )}
                      {isStepDone && (
                        <span className="px-2.5 py-1 rounded-md bg-emerald-950/60 text-emerald-300 font-medium text-[11px] flex items-center gap-1.5 border border-emerald-800">
                          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                          <span>Hoàn tất</span>
                        </span>
                      )}
                      {isStepError && (
                        <span className="px-2.5 py-1 rounded-md bg-rose-950/60 text-rose-300 font-medium text-[11px] flex items-center gap-1.5 border border-rose-800">
                          <AlertCircle className="w-3.5 h-3.5 text-rose-400" />
                          <span>Lỗi</span>
                        </span>
                      )}
                      {step.status === 'pending' && (
                        <span className="px-2.5 py-1 rounded-md bg-zinc-900 text-zinc-500 font-medium text-[11px] border border-zinc-800">
                          Chờ thực thi
                        </span>
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Collapsible Terminal Output Console */}
          <div className="border border-zinc-800 rounded-xl overflow-hidden bg-zinc-950">
            <button
              type="button"
              onClick={() => setIsLogExpanded(!isLogExpanded)}
              className="w-full px-4 py-2.5 bg-zinc-900/90 hover:bg-zinc-900 border-b border-zinc-800 flex items-center justify-between text-xs font-semibold text-zinc-300 transition-colors cursor-pointer"
            >
              <div className="flex items-center gap-2">
                <Terminal className="w-4 h-4 text-amber-400" />
                <span>Nhật ký Quá trình Cài đặt (Live Terminal Logs)</span>
                <span className="text-[10px] text-zinc-500 font-mono">({logs.length} dòng)</span>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleCopyLogs();
                  }}
                  className="p-1 rounded hover:bg-zinc-800 text-zinc-400 hover:text-zinc-200 transition-colors"
                  title="Sao chép nhật ký"
                >
                  {copiedLog ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
                </button>
                {isLogExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
              </div>
            </button>

            {isLogExpanded && (
              <div className="p-3 font-mono text-[11px] text-zinc-300 max-h-44 overflow-y-auto space-y-1 select-text bg-black/60">
                {logs.length === 0 ? (
                  <div className="text-zinc-600 italic">Chưa có nhật ký nào được ghi lại.</div>
                ) : (
                  logs.map((line, i) => (
                    <div
                      key={i}
                      className={`${
                        line.includes('LỖI') || line.includes('error')
                          ? 'text-rose-400'
                          : line.includes('✓') || line.includes('THÀNH CÔNG')
                          ? 'text-emerald-400 font-semibold'
                          : line.includes('!')
                          ? 'text-amber-400'
                          : 'text-zinc-300'
                      }`}
                    >
                      {line}
                    </div>
                  ))
                )}
                <div ref={logEndRef} />
              </div>
            )}
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-4 border-t border-zinc-800 bg-zinc-950 flex items-center justify-between">
          <div className="flex items-center gap-2 text-zinc-500 text-xs">
            <ExternalLink className="w-3.5 h-3.5" />
            <a
              href="https://github.com/cuongpt083/nanobot/blob/main/docs/start-without-technical-background.md"
              target="_blank"
              rel="noreferrer"
              className="hover:text-amber-400 transition-colors underline underline-offset-2"
            >
              Xem hướng dẫn start-without-technical-background
            </a>
          </div>

          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 rounded-xl text-xs font-medium text-zinc-400 hover:text-zinc-200 hover:bg-zinc-800/80 transition-colors cursor-pointer"
            >
              {isAllCompleted ? 'Đóng' : 'Bỏ qua & Cài đặt sau'}
            </button>

            <button
              type="button"
              disabled={isRunning}
              onClick={() => handleStartSetup(isAllCompleted)}
              className={`px-5 py-2 rounded-xl text-xs font-bold flex items-center gap-2 shadow-md cursor-pointer transition-all ${
                isAllCompleted
                  ? 'bg-emerald-600 hover:bg-emerald-500 text-white'
                  : 'bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-zinc-950'
              } disabled:opacity-50 disabled:cursor-not-allowed`}
            >
              {isRunning ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  <span>Đang thiết lập...</span>
                </>
              ) : isAllCompleted ? (
                <>
                  <RefreshCw className="w-4 h-4" />
                  <span>Chạy lại Thiết lập Môi trường</span>
                </>
              ) : (
                <>
                  <PlayCircle className="w-4 h-4" />
                  <span>Bắt đầu Cài đặt Tự động</span>
                </>
              )}
            </button>

            {isAllCompleted && (
              <button
                type="button"
                onClick={onClose}
                className="px-5 py-2 rounded-xl text-xs font-bold bg-amber-500 hover:bg-amber-400 text-zinc-950 transition-colors shadow-md cursor-pointer"
              >
                Hoàn tất & Bắt đầu sử dụng
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
