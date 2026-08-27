import React, { useState } from 'react';
import {
  Send,
  MessageSquare,
  Slack,
  Layers,
  Smartphone,
  Mail,
  Radio,
  CheckCircle2,
  AlertCircle,
  Clock,
  Key,
  Globe,
  Copy,
  Check,
  ExternalLink,
  ShieldCheck,
  RefreshCw
} from 'lucide-react';
import { ChannelInfo } from '../types';

interface ChannelsViewProps {
  channels: ChannelInfo[];
  onSaveChannelConfig: (channelId: string, values: Record<string, string>) => Promise<void>;
}

export const ChannelsView: React.FC<ChannelsViewProps> = ({ channels, onSaveChannelConfig }) => {
  const [selectedChannel, setSelectedChannel] = useState<ChannelInfo | null>(null);
  const [formValues, setFormValues] = useState<Record<string, string>>({});
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  const getIcon = (iconName: string) => {
    switch (iconName) {
      case 'Send':
        return <Send className="w-5 h-5 text-sky-400" />;
      case 'MessageSquare':
        return <MessageSquare className="w-5 h-5 text-indigo-400" />;
      case 'Slack':
        return <Slack className="w-5 h-5 text-emerald-400" />;
      case 'Layers':
        return <Layers className="w-5 h-5 text-cyan-400" />;
      case 'Smartphone':
        return <Smartphone className="w-5 h-5 text-teal-400" />;
      case 'Mail':
        return <Mail className="w-5 h-5 text-amber-400" />;
      case 'Radio':
      default:
        return <Radio className="w-5 h-5 text-orange-400" />;
    }
  };

  const handleOpenConfig = (channel: ChannelInfo) => {
    setSelectedChannel(channel);
    const initial: Record<string, string> = {};
    (channel.configFields || []).forEach((f) => {
      initial[f.key] = f.value || '';
    });
    setFormValues(initial);
  };

  const handleCopy = (text: string, id: string) => {
    navigator.clipboard.writeText(text);
    setCopiedId(id);
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedChannel) return;
    setIsSaving(true);
    try {
      await onSaveChannelConfig(selectedChannel.id, formValues);
      setSelectedChannel(null);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-8 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-zinc-100">Multi-Channel Inbound Gateway</h2>
          <p className="text-xs text-zinc-400 mt-1">
            Nanobot connects to messaging apps and webhooks over an asynchronous MessageBus, routing messages directly to the agent loop.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <span className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-950/60 border border-emerald-800 text-emerald-300 text-xs font-mono">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
            MessageBus Active (Port 3000)
          </span>
        </div>
      </div>

      {/* Grid of channels */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {channels.map((ch) => {
          const isConnected = ch.status === 'connected';
          const isIdle = ch.status === 'idle';

          return (
            <div
              key={ch.id}
              id={`channel-card-${ch.id}`}
              className="rounded-xl border border-zinc-800/90 bg-zinc-900/60 p-5 flex flex-col justify-between hover:border-zinc-700 transition-all shadow-sm"
            >
              <div>
                <div className="flex items-start justify-between mb-3">
                  <div className="flex items-center gap-3">
                    <div className="p-2.5 rounded-lg bg-zinc-800/80 border border-zinc-700/60">
                      {getIcon(ch.icon)}
                    </div>
                    <div>
                      <h3 className="text-sm font-semibold text-zinc-100">{ch.name}</h3>
                      <span className="text-[10px] text-zinc-500 uppercase font-mono tracking-wider">
                        {ch.type}
                      </span>
                    </div>
                  </div>

                  <span
                    className={`px-2 py-0.5 rounded-full text-[10px] font-medium flex items-center gap-1 ${
                      isConnected
                        ? 'bg-emerald-950/60 text-emerald-300 border border-emerald-800/80'
                        : isIdle
                        ? 'bg-amber-950/60 text-amber-300 border border-amber-800/80'
                        : 'bg-zinc-800 text-zinc-400 border border-zinc-700'
                    }`}
                  >
                    {isConnected ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-400" />
                    ) : (
                      <Clock className="w-3 h-3 text-amber-400" />
                    )}
                    <span className="capitalize">{ch.status}</span>
                  </span>
                </div>

                <p className="text-xs text-zinc-400 mb-4 line-clamp-2 leading-relaxed">
                  {ch.description}
                </p>

                {ch.pairingCode && (
                  <div className="mb-3 p-2.5 rounded-lg bg-zinc-950/70 border border-zinc-800 flex items-center justify-between text-xs font-mono">
                    <span className="text-zinc-400 text-[11px]">Pairing Code:</span>
                    <div className="flex items-center gap-1.5">
                      <span className="text-amber-400 font-bold">{ch.pairingCode}</span>
                      <button
                        onClick={() => handleCopy(ch.pairingCode!, `pair-${ch.id}`)}
                        className="p-1 hover:text-zinc-200 text-zinc-500"
                        title="Copy Code"
                      >
                        {copiedId === `pair-${ch.id}` ? (
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                        ) : (
                          <Copy className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  </div>
                )}
              </div>

              <div className="pt-3 border-t border-zinc-800/70 flex items-center justify-between">
                <span className="text-[11px] text-zinc-500">
                  {ch.configFields.length} config parameters
                </span>

                <button
                  id={`btn-configure-${ch.id}`}
                  onClick={() => handleOpenConfig(ch)}
                  className="px-3 py-1.5 rounded-md bg-zinc-800 hover:bg-zinc-700 text-zinc-200 text-xs font-medium transition-colors cursor-pointer"
                >
                  Configure
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Configuration Modal */}
      {selectedChannel && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl w-full max-w-lg overflow-hidden shadow-2xl">
            <div className="p-5 border-b border-zinc-800 flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="p-2 rounded-lg bg-zinc-800">
                  {getIcon(selectedChannel.icon)}
                </div>
                <div>
                  <h3 className="text-base font-semibold text-zinc-100">
                    Configure {selectedChannel.name}
                  </h3>
                  <p className="text-xs text-zinc-400">Update bot credentials & routing rules</p>
                </div>
              </div>

              <button
                onClick={() => setSelectedChannel(null)}
                className="text-zinc-500 hover:text-zinc-300 text-sm"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleSave} className="p-5 space-y-4">
              {selectedChannel.configFields.map((field) => (
                <div key={field.key} className="space-y-1.5">
                  <label className="block text-xs font-medium text-zinc-300">
                    {field.label}
                  </label>
                  {field.type === 'select' ? (
                    <select
                      value={formValues[field.key] || ''}
                      onChange={(e) =>
                        setFormValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                      }
                      className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-amber-500"
                    >
                      {field.options?.map((opt) => (
                        <option key={opt} value={opt}>
                          {opt}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={field.type}
                      placeholder={field.placeholder}
                      value={formValues[field.key] || ''}
                      onChange={(e) =>
                        setFormValues((prev) => ({ ...prev, [field.key]: e.target.value }))
                      }
                      className="w-full bg-zinc-950 border border-zinc-800 rounded-lg px-3 py-2 text-xs text-zinc-200 placeholder:text-zinc-600 focus:outline-none focus:border-amber-500"
                    />
                  )}
                </div>
              ))}

              <div className="pt-4 border-t border-zinc-800 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => setSelectedChannel(null)}
                  className="px-4 py-2 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-zinc-300 text-xs font-medium transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSaving}
                  className="px-4 py-2 rounded-lg bg-amber-500 hover:bg-amber-400 text-zinc-950 text-xs font-semibold transition-colors disabled:opacity-50"
                >
                  {isSaving ? 'Saving...' : 'Save Configuration'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
