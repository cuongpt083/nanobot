import React, { useState } from 'react';
import {
  Radio,
  MessageSquare,
  Mail,
  Send,
  Lock,
  Key,
  Plus,
  Trash2,
  CheckCircle2,
  Users,
  ShieldCheck,
  Globe
} from 'lucide-react';
import { NanobotFullConfig } from '../../../types';

interface ChannelsConfigTabProps {
  config: NanobotFullConfig;
  onUpdateConfig: (newConfig: Partial<NanobotFullConfig>) => void;
}

const CHANNELS_META = [
  {
    id: 'telegram',
    name: 'Telegram Bot',
    icon: Send,
    color: 'text-sky-400',
    description: 'Long polling & Webhook messenger bot via BotFather.',
    fields: [
      { key: 'botToken', label: 'Bot Token', placeholder: '123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11' },
      { key: 'webhookUrl', label: 'Webhook URL (Optional)', placeholder: 'https://gateway.domain.com/telegram' },
    ],
  },
  {
    id: 'discord',
    name: 'Discord Bot',
    icon: MessageSquare,
    color: 'text-indigo-400',
    description: 'Discord Gateway v10 slash commands and channel listener.',
    fields: [
      { key: 'token', label: 'Bot Token', placeholder: 'MTIzNDU2Nzg5MDEyMzQ1Njc4OQ...' },
      { key: 'appId', label: 'Application ID', placeholder: '123456789012345678' },
    ],
  },
  {
    id: 'slack',
    name: 'Slack App',
    icon: Lock,
    color: 'text-emerald-400',
    description: 'Socket Mode & Events API integration for enterprise workspaces.',
    fields: [
      { key: 'botToken', label: 'Bot User OAuth Token (xoxb-...)', placeholder: 'xoxb-123-456-789' },
      { key: 'appToken', label: 'App-Level Token (xapp-...)', placeholder: 'xapp-1-A111-222-333' },
    ],
  },
  {
    id: 'email',
    name: 'Email (IMAP / SMTP)',
    icon: Mail,
    color: 'text-amber-400',
    description: 'Agent monitoring inbox via IMAP and sending turn summaries via SMTP.',
    fields: [
      { key: 'email', label: 'Email Address', placeholder: 'agent@domain.com' },
      { key: 'password', label: 'App Password', placeholder: '••••••••••••' },
      { key: 'imapHost', label: 'IMAP Server', placeholder: 'imap.gmail.com:993' },
      { key: 'smtpHost', label: 'SMTP Server', placeholder: 'smtp.gmail.com:587' },
    ],
  },
];

export const ChannelsConfigTab: React.FC<ChannelsConfigTabProps> = ({
  config,
  onUpdateConfig,
}) => {
  const channels = config.channels || {};
  const [selectedChannelId, setSelectedChannelId] = useState<string>('telegram');

  const currentChannel = channels[selectedChannelId] || { enabled: false };
  const meta = CHANNELS_META.find((c) => c.id === selectedChannelId) || CHANNELS_META[0];

  const handleUpdateChannel = (key: string, value: any) => {
    const updated = {
      ...channels,
      [selectedChannelId]: {
        ...currentChannel,
        [key]: value,
      },
    };
    onUpdateConfig({ channels: updated });
  };

  const handleToggleChannel = (channelId: string) => {
    const existing = channels[channelId] || { enabled: false };
    const updated = {
      ...channels,
      [channelId]: {
        ...existing,
        enabled: !existing.enabled,
      },
    };
    onUpdateConfig({ channels: updated });
  };

  return (
    <div className="flex h-full gap-6 text-zinc-300">
      {/* Channels Sidebar List */}
      <div className="w-72 flex-shrink-0 border-r border-zinc-800/80 pr-4 space-y-1.5 overflow-y-auto">
        <div className="px-2 py-1 text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
          Chat Integrations
        </div>

        {CHANNELS_META.map((item) => {
          const chData = channels[item.id] || { enabled: false };
          const isSelected = selectedChannelId === item.id;
          const Icon = item.icon;

          return (
            <button
              key={item.id}
              onClick={() => setSelectedChannelId(item.id)}
              className={`w-full text-left p-3 rounded-xl transition-all cursor-pointer flex items-center justify-between border ${
                isSelected
                  ? 'bg-amber-500/10 border-amber-500/50 text-amber-300 font-medium'
                  : 'bg-zinc-950/40 hover:bg-zinc-900 border-zinc-800/60 text-zinc-300'
              }`}
            >
              <div className="flex items-center gap-2.5 min-w-0">
                <div
                  className={`w-7 h-7 rounded-lg flex items-center justify-center bg-zinc-900 border border-zinc-800 ${item.color}`}
                >
                  <Icon className="w-3.5 h-3.5" />
                </div>
                <div className="truncate">
                  <div className="text-xs font-semibold text-zinc-200 truncate">{item.name}</div>
                  <div className="text-[10px] text-zinc-500 truncate font-mono">
                    {chData.enabled ? 'Enabled' : 'Disabled'}
                  </div>
                </div>
              </div>

              <div
                className={`w-2 h-2 rounded-full ${
                  chData.enabled ? 'bg-emerald-400 shadow-xs shadow-emerald-400/50' : 'bg-zinc-700'
                }`}
              />
            </button>
          );
        })}
      </div>

      {/* Channel Config Panel */}
      <div className="flex-1 overflow-y-auto pr-2 space-y-5">
        <div className="p-4 rounded-xl bg-zinc-950/60 border border-zinc-800/80 flex items-center justify-between">
          <div>
            <h4 className="text-sm font-bold text-zinc-100">{meta.name}</h4>
            <p className="text-xs text-zinc-400 mt-1">{meta.description}</p>
          </div>

          <button
            onClick={() => handleToggleChannel(selectedChannelId)}
            className={`px-3 py-1.5 rounded-lg text-xs font-semibold transition-all cursor-pointer ${
              currentChannel.enabled
                ? 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
                : 'bg-zinc-800 hover:bg-zinc-700 text-zinc-400'
            }`}
          >
            {currentChannel.enabled ? '✓ Channel Enabled' : 'Enable Channel'}
          </button>
        </div>

        {/* Dynamic Fields */}
        <div className="space-y-4">
          {meta.fields.map((field) => (
            <div key={field.key} className="space-y-1.5">
              <label className="text-xs font-semibold text-zinc-200">{field.label}</label>
              <input
                type={field.key.toLowerCase().includes('password') || field.key.toLowerCase().includes('token') ? 'password' : 'text'}
                value={currentChannel[field.key] || ''}
                onChange={(e) => handleUpdateChannel(field.key, e.target.value)}
                placeholder={field.placeholder}
                className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200 focus:outline-none focus:border-amber-500"
              />
            </div>
          ))}

          {/* Whitelist / allowFrom */}
          <div className="space-y-1.5 pt-3 border-t border-zinc-800">
            <div className="flex items-center justify-between">
              <label className="text-xs font-semibold text-zinc-200 flex items-center gap-1.5">
                <Users className="w-3.5 h-3.5 text-amber-400" />
                <span>Allowed User IDs / Handles (allowFrom)</span>
              </label>
              <span className="text-[10px] text-zinc-500">Comma separated</span>
            </div>
            <input
              type="text"
              value={currentChannel.allowFrom?.join(', ') || ''}
              onChange={(e) =>
                handleUpdateChannel(
                  'allowFrom',
                  e.target.value
                    .split(',')
                    .map((s) => s.trim())
                    .filter(Boolean)
                )
              }
              placeholder="e.g. 12345678, @username (leave empty for open/pairing mode)"
              className="w-full bg-zinc-950 border border-zinc-800 rounded-lg p-2.5 text-xs font-mono text-zinc-200"
            />
            <p className="text-[11px] text-zinc-500">
              Only whitelisted senders can trigger agent execution. Unknown senders receive a DM pairing code.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
};
