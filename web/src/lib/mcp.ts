/* Types and hooks for the MCP inspector. The account's SSE feed carries protocol events too: `mcp` (one traced
   message), `elicit` / `elicit_done` (a question from the server) and `change` (a resource-updated notification). */
import { useEffect, useRef } from "react";
import type { LedgerEvent } from "./events";

export interface TraceEntry {
  seq: number;
  ts: string;
  client: string;
  dir: "out" | "in";
  method: string;
  kind: "session" | "tool" | "resource" | "prompt" | "completion" | "subscription" | "sampling" | "elicitation" | "roots" | "log" | "progress";
  detail: string;
  ok: boolean;
  ms: number | null;
  [key: string]: unknown;
}

export interface TraceStats { total: number; since: string; by_kind: Record<string, number>; by_method: Record<string, number>; by_client: Record<string, number> }

export interface Question { id: string; client: string; message: string; schema: JsonSchema; asked_at: string }

export interface JsonSchema {
  type?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  enum?: (string | number)[];
  default?: unknown;
  description?: string;
  title?: string;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  minimum?: number;
  maximum?: number;
}

export interface Session {
  client: string;
  protocol: string;
  offers: string[];
  server: { name: string | null; version: string | null };
  server_capabilities: Record<string, unknown>;
}

export interface McpOverview {
  endpoint: string;
  sessions: Session[];
  subscribed: string[];
  sampling_model: string | null;
  stats: TraceStats;
  open_questions: Question[];
}

export interface McpSchema {
  tools: { name: string; description: string | null; input_schema: JsonSchema; annotations: Record<string, unknown> }[];
  prompts: { name: string; description: string | null; arguments: { name: string; description: string | null; required: boolean }[] }[];
  resources: { uri: string; name: string; description: string | null }[];
  templates: { uri_template: string; name: string; description: string | null }[];
}

export type McpEvent = LedgerEvent & Partial<TraceEntry> & Partial<Question> & { uri?: string };

/** Listen to every event on the account feed (the ledger provider re-broadcasts them on window). */
export function useFeed(handler: (ev: McpEvent) => void): void {
  const ref = useRef(handler);
  ref.current = handler;
  useEffect(() => {
    const on = (e: Event) => ref.current((e as CustomEvent<McpEvent>).detail);
    window.addEventListener("finmcp:event", on);
    return () => window.removeEventListener("finmcp:event", on);
  }, []);
}

export const KIND_LABEL: Record<string, string> = {
  session: "Session", tool: "Tools", resource: "Resources", prompt: "Prompts", completion: "Completion", subscription: "Subscriptions",
  sampling: "Sampling", elicitation: "Elicitation", roots: "Roots", log: "Logging", progress: "Progress",
};
