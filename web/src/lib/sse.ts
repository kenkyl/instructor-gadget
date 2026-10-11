// Server-Sent Events over fetch (not EventSource): the lesson endpoint is a POST (it generates
// and stores), and EventSource only does GET. Frames are "event: x\ndata: {json}\n\n"; lines
// starting with ":" are FastAPI's keepalive comments.
import { ApiError } from "@/lib/api";

export type SseEvent = { event: string; data: unknown };

export async function postSse(
  path: string,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`/api${path}`, { method: "POST", cache: "no-store", signal });
  if (!res.ok || !res.body) {
    let message = `POST /api${path} failed: ${res.status}`;
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, message);
  }
  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += value;
    let end: number;
    while ((end = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, end);
      buf = buf.slice(end + 2);
      let event = "message";
      const data: string[] = [];
      for (const line of frame.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) data.push(line.slice(6));
      }
      if (data.length) onEvent({ event, data: JSON.parse(data.join("\n")) });
    }
  }
}
