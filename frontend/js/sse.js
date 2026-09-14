// WebRAG SSE helpers.
// EventSource cannot send a POST body, and /api/chat/stream requires one,
// so we consume Server-Sent Events manually via fetch + ReadableStream.

/**
 * Consume a GET-based SSE stream (e.g. crawl progress).
 * @param {string} url
 * @param {(data: any) => void} onEvent
 * @param {(err: Error) => void} onError
 * @returns {() => void} cancel function
 */
export function streamGetSSE(url, onEvent, onError) {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(url, { signal: controller.signal, headers: { Accept: 'text/event-stream' } });
      if (!res.ok || !res.body) {
        throw new Error(`Stream failed (${res.status})`);
      }
      await pumpStream(res.body, onEvent);
    } catch (err) {
      if (err.name !== 'AbortError' && onError) onError(err);
    }
  })();

  return () => controller.abort();
}

/**
 * Consume a POST-based SSE stream (e.g. /api/chat/stream).
 * @param {string} url
 * @param {object} body
 * @param {(data: any) => void} onEvent
 * @param {(err: Error) => void} onError
 * @returns {() => void} cancel function
 */
export function streamPostSSE(url, body, onEvent, onError) {
  const controller = new AbortController();

  (async () => {
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        let message = `Stream failed (${res.status})`;
        try {
          const errBody = await res.json();
          message = errBody.detail || errBody.error || message;
        } catch (_) {}
        throw new Error(message);
      }
      await pumpStream(res.body, onEvent);
    } catch (err) {
      if (err.name !== 'AbortError' && onError) onError(err);
    }
  })();

  return () => controller.abort();
}

async function pumpStream(body, onEvent) {
  const reader = body.getReader();
  const decoder = new TextDecoder('utf-8');
  let buffer = '';

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let boundary;
    while ((boundary = buffer.indexOf('\n\n')) !== -1) {
      const rawEvent = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      emitEvent(rawEvent, onEvent);
    }
  }
  if (buffer.trim()) emitEvent(buffer, onEvent);
}

function emitEvent(rawEvent, onEvent) {
  const lines = rawEvent.split('\n');
  const dataLines = lines.filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim());
  if (!dataLines.length) return;
  const raw = dataLines.join('\n');
  try {
    onEvent(JSON.parse(raw));
  } catch (_) {
    onEvent(raw);
  }
}
