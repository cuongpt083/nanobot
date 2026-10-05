import { mutation, type WebUIMutationTransport } from "./api";

export interface ContextSystemSection {
  key: string;
  label: string;
  content_preview: string;
  tokens: number;
  removable: boolean;
  excluded: boolean;
}

export interface ContextToolItem {
  name: string;
  preview: string;
  tokens: number;
  removable: boolean;
  excluded: boolean;
}

export interface ContextMessageItem {
  idx: number;
  role: string;
  preview: string;
  tokens: number;
  tool_use_ids: string[];
  removable: boolean;
  excluded: boolean;
}

export interface ContextBudget {
  used: number;
  max: number;
  model_id: string;
  provider: string;
  is_estimate: boolean;
  captured_at: number;
}

export interface ContextRules {
  system_sections: string[];
  tools: string[];
  message_idx: number[];
  wasted_ids: string[];
}

export interface ContextSnapshot {
  available: boolean;
  budget?: ContextBudget;
  system: {
    total_tokens: number;
    sections: ContextSystemSection[];
  };
  tools: {
    total_tokens: number;
    items: ContextToolItem[];
  };
  messages: {
    total_tokens: number;
    items: ContextMessageItem[];
  };
  rules?: ContextRules;
  session_key?: string;
}

export async function fetchContextInspect(
  sessionKey: string,
  token: string,
): Promise<ContextSnapshot | null> {
  try {
    const encodedKey = encodeURIComponent(sessionKey);
    const headers: Record<string, string> = {};
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    const res = await fetch(`/api/sessions/${encodedKey}/context/inspect`, {
      headers,
    });
    if (!res.ok) {
      return null;
    }
    return (await res.json()) as ContextSnapshot;
  } catch {
    return null;
  }
}

export async function updateContextExclusions(
  sessionKey: string,
  transport: WebUIMutationTransport,
  exclusions: {
    system_sections?: string[];
    tools?: string[];
    message_idx?: number[];
  },
): Promise<ContextRules | null> {
  try {
    const res = await mutation<{ status: string; rules: ContextRules }>(
      transport,
      "session.context.exclusions",
      {
        key: sessionKey,
        ...exclusions,
      },
    );
    return res.rules;
  } catch {
    return null;
  }
}
