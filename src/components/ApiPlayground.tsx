import React, { useState } from 'react';
import {
  Code,
  Play,
  Copy,
  Check,
  Server,
  Layers,
  Terminal,
  Globe,
  CheckCircle2,
  Clock
} from 'lucide-react';

export const ApiPlayground: React.FC = () => {
  const [endpoint, setEndpoint] = useState('/v1/chat/completions');
  const [method, setMethod] = useState('POST');
  const [requestBody, setRequestBody] = useState(
    JSON.stringify(
      {
        model: 'gemini-2.5-flash',
        messages: [{ role: 'user', content: 'What are the core capabilities of nanobot?' }],
        temperature: 0.7,
      },
      null,
      2,
    ),
  );
  const [responseOutput, setResponseOutput] = useState<string | null>(null);
  const [statusCode, setStatusCode] = useState<number | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [copiedCode, setCopiedCode] = useState(false);

  const handleSendRequest = async () => {
    setIsLoading(true);
    setResponseOutput(null);
    setStatusCode(null);
    setLatencyMs(null);

    const start = performance.now();
    try {
      let res: Response;
      if (method === 'GET') {
        res = await fetch(endpoint);
      } else {
        res = await fetch(endpoint, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: requestBody,
        });
      }

      const end = performance.now();
      setLatencyMs(Math.round(end - start));
      setStatusCode(res.status);

      const data = await res.json();
      setResponseOutput(JSON.stringify(data, null, 2));
    } catch (err: any) {
      const end = performance.now();
      setLatencyMs(Math.round(end - start));
      setStatusCode(500);
      setResponseOutput(JSON.stringify({ error: err.message || 'Request failed' }, null, 2));
    } finally {
      setIsLoading(false);
    }
  };

  const curlCommand = `curl -X ${method} "http://localhost:3000${endpoint}" \\
  -H "Content-Type: application/json" \\
  ${method === 'POST' ? `-d '${requestBody.replace(/\n\s*/g, '')}'` : ''}`;

  const handleCopyCurl = () => {
    navigator.clipboard.writeText(curlCommand);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 2000);
  };

  return (
    <div className="h-full overflow-y-auto p-8 max-w-6xl mx-auto space-y-6">
      <div>
        <div className="flex items-center gap-2 mb-1">
          <Server className="w-6 h-6 text-amber-400" />
          <h2 className="text-xl font-bold text-zinc-100">OpenAI-Compatible Gateway API</h2>
        </div>
        <p className="text-xs text-zinc-400 leading-relaxed">
          Nanobot exposes drop-in OpenAI-compatible endpoints (<code className="text-amber-400 font-mono">/v1/chat/completions</code>, <code className="text-amber-400 font-mono">/v1/models</code>) so you can point any LLM tool, LangChain, or Claude Code directly at your local agent.
        </p>
      </div>

      {/* Request Sandbox */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Request Configuration */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 space-y-4 flex flex-col justify-between">
          <div className="space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <span className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">
                HTTP Request
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => {
                    setEndpoint('/v1/chat/completions');
                    setMethod('POST');
                  }}
                  className={`px-2.5 py-1 rounded text-xs font-mono ${
                    endpoint === '/v1/chat/completions'
                      ? 'bg-amber-500 text-zinc-950 font-bold'
                      : 'bg-zinc-800 text-zinc-400'
                  }`}
                >
                  /v1/chat/completions
                </button>
                <button
                  onClick={() => {
                    setEndpoint('/v1/models');
                    setMethod('GET');
                  }}
                  className={`px-2.5 py-1 rounded text-xs font-mono ${
                    endpoint === '/v1/models'
                      ? 'bg-amber-500 text-zinc-950 font-bold'
                      : 'bg-zinc-800 text-zinc-400'
                  }`}
                >
                  /v1/models
                </button>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <span className="px-3 py-2 bg-zinc-800 font-mono text-xs text-amber-400 font-bold rounded-lg border border-zinc-700">
                {method}
              </span>
              <input
                type="text"
                value={endpoint}
                onChange={(e) => setEndpoint(e.target.value)}
                className="flex-1 bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
              />
            </div>

            {method === 'POST' && (
              <div className="space-y-1.5">
                <label className="block text-xs font-medium text-zinc-400">JSON Body</label>
                <textarea
                  rows={9}
                  value={requestBody}
                  onChange={(e) => setRequestBody(e.target.value)}
                  className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-3 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
                />
              </div>
            )}
          </div>

          <div className="pt-4 border-t border-zinc-800 flex items-center justify-between">
            <button
              onClick={handleCopyCurl}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-mono transition-colors cursor-pointer"
            >
              {copiedCode ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
              <span>{copiedCode ? 'Copied cURL' : 'Copy cURL'}</span>
            </button>

            <button
              id="btn-execute-api-req"
              onClick={handleSendRequest}
              disabled={isLoading}
              className="flex items-center gap-2 px-4 py-2 bg-amber-500 hover:bg-amber-400 text-zinc-950 font-semibold text-xs rounded-lg transition-colors disabled:opacity-50 cursor-pointer shadow-md"
            >
              <Play className="w-3.5 h-3.5 fill-current" />
              <span>{isLoading ? 'Executing...' : 'Send Request'}</span>
            </button>
          </div>
        </div>

        {/* Right: Response Inspector */}
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 space-y-4 flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between pb-3 border-b border-zinc-800">
              <span className="text-xs font-semibold text-zinc-200 uppercase tracking-wider">
                Gateway Response
              </span>
              <div className="flex items-center gap-3 text-xs font-mono">
                {statusCode && (
                  <span
                    className={`px-2 py-0.5 rounded text-[11px] font-bold ${
                      statusCode >= 200 && statusCode < 300
                        ? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
                        : 'bg-red-950 text-red-300 border border-red-800'
                    }`}
                  >
                    HTTP {statusCode}
                  </span>
                )}
                {latencyMs !== null && (
                  <span className="text-zinc-400 flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5 text-zinc-500" />
                    {latencyMs}ms
                  </span>
                )}
              </div>
            </div>

            <div className="mt-4">
              {responseOutput ? (
                <pre className="p-4 rounded-xl bg-zinc-950 border border-zinc-800 text-xs font-mono text-emerald-300/90 overflow-x-auto max-h-[360px] overflow-y-auto leading-relaxed">
                  {responseOutput}
                </pre>
              ) : (
                <div className="p-12 text-center text-zinc-600 text-xs rounded-xl bg-zinc-950/60 border border-zinc-800/80 font-mono">
                  Send a request to see the live gateway response.
                </div>
              )}
            </div>
          </div>

          <div className="pt-3 border-t border-zinc-800 text-[11px] text-zinc-500 flex items-center justify-between">
            <span>Compatible with OpenAI Python SDK, LangChain, Cursor, and LiteLLM</span>
          </div>
        </div>
      </div>
    </div>
  );
};
