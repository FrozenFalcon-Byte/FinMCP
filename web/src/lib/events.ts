/* The account's change feed over server-sent events (fetch-based so the bearer token travels in a header). */
import { apiUrl, authHeaders, isAbort, signalOffline, signalOnline } from "./api";

export interface LedgerEvent {
  type: string;
  entity?: string;
  action?: string;
  id?: number | null;
  client?: string;
  ts?: string;
}

export function subscribeEvents(onEvent: (ev: LedgerEvent) => void, onState: (live: boolean) => void): () => void {
  let stopped = false;
  let controller: AbortController | null = null;
  let backoff = 1000;

  const run = async () => {
    while (!stopped) {
      controller = new AbortController();
      try {
        const res = await fetch(apiUrl("/events"), { headers: { Accept: "text/event-stream", ...authHeaders() }, signal: controller.signal });
        signalOnline();
        if (!res.ok || !res.body) {
          if (res.status === 401) window.dispatchEvent(new Event("finmcp:unauthorized"));
          throw new Error(`events ${res.status}`);
        }
        onState(true);
        backoff = 1000;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx: number;
          while ((idx = buffer.indexOf("\n\n")) >= 0) {
            const chunk = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            let type = "message";
            let data = "";
            for (const line of chunk.split("\n")) {
              if (line.startsWith("event:")) type = line.slice(6).trim();
              else if (line.startsWith("data:")) data += line.slice(5).trim();
            }
            if (data) {
              try {
                onEvent({ ...(JSON.parse(data) as LedgerEvent), type });
              } catch {
                /* ignore malformed frames */
              }
            }
          }
        }
      } catch (e) {
        if (!stopped && !isAbort(e)) signalOffline(); // the stream dying is the first sign the backend went to sleep
      }
      onState(false);
      if (stopped) break;
      await new Promise((r) => setTimeout(r, backoff));
      backoff = Math.min(backoff * 2, 15000);
    }
  };
  void run();
  return () => {
    stopped = true;
    controller?.abort();
  };
}
