import React, { Component, ErrorInfo, ReactNode } from 'react';
import { AlertTriangle, RotateCcw, Home } from 'lucide-react';

interface Props {
  children: ReactNode;
  fallbackTitle?: string;
  onReset?: () => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
    errorInfo: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error, errorInfo: null };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('Uncaught error caught by ErrorBoundary:', error, errorInfo);
    this.setState({ errorInfo });
  }

  public handleReset = () => {
    this.setState({ hasError: false, error: null, errorInfo: null });
    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  public render() {
    if (this.state.hasError) {
      return (
        <div className="flex-1 flex flex-col items-center justify-center h-full p-8 bg-zinc-950 text-zinc-100 text-center">
          <div className="w-14 h-14 rounded-2xl bg-rose-500/10 border border-rose-500/30 flex items-center justify-center text-rose-400 mb-4 shadow-lg">
            <AlertTriangle className="w-7 h-7" />
          </div>

          <h2 className="text-lg font-bold text-zinc-100 mb-1">
            {this.props.fallbackTitle || 'Đã xảy ra sự cố giao diện'}
          </h2>

          <p className="text-xs text-zinc-400 max-w-md mb-4 leading-relaxed">
            {this.state.error?.message || 'Một lỗi không mong muốn đã được chặn lại để bảo vệ ứng dụng.'}
          </p>

          <div className="flex items-center gap-3">
            <button
              onClick={this.handleReset}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-semibold transition-colors cursor-pointer shadow-md"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Thử lại (Reload View)</span>
            </button>

            <button
              onClick={() => {
                this.setState({ hasError: false, error: null, errorInfo: null });
                window.location.reload();
              }}
              className="flex items-center gap-1.5 px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-200 border border-zinc-700 text-xs font-medium transition-colors cursor-pointer"
            >
              <Home className="w-3.5 h-3.5" />
              <span>Khởi động lại trang</span>
            </button>
          </div>

          {this.state.error && (
            <div className="mt-6 p-4 rounded-xl bg-zinc-900 border border-zinc-800 text-left max-w-xl w-full overflow-hidden">
              <span className="text-[10px] uppercase font-mono text-zinc-500 block mb-1">Chi tiết lỗi kỹ thuật:</span>
              <pre className="text-[11px] font-mono text-rose-300/90 whitespace-pre-wrap break-all max-h-40 overflow-y-auto">
                {this.state.error.stack || this.state.error.message}
              </pre>
            </div>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}
