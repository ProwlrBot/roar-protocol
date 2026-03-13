/**
 * ROAR Protocol — stdio transport (newline-delimited JSON).
 *
 * Mirrors python/src/roar_sdk/transports/stdio.py exactly.
 * Suitable for local subprocess agent communication (MCP stdio mode).
 * Uses Node.js built-in process.stdin / process.stdout — no external deps.
 *
 * Usage:
 *   const response = await stdioSend(signedMessage);
 */

import { ROARMessage, messageFromWire, messageToWire } from "./types.js";

// ---------------------------------------------------------------------------
// Sync I/O helpers (run in worker thread via executor pattern)
// ---------------------------------------------------------------------------

function writeLine(line: string): void {
  process.stdout.write(line + "\n");
}

async function readLine(): Promise<string> {
  return new Promise((resolve, reject) => {
    let buf = "";
    const onData = (chunk: Buffer | string) => {
      buf += chunk.toString();
      const nl = buf.indexOf("\n");
      if (nl !== -1) {
        cleanup();
        resolve(buf.slice(0, nl));
      }
    };
    const onEnd = () => {
      cleanup();
      resolve(buf); // EOF — return whatever was buffered (may be empty)
    };
    const onError = (err: Error) => {
      cleanup();
      reject(err);
    };
    const cleanup = () => {
      process.stdin.removeListener("data", onData);
      process.stdin.removeListener("end", onEnd);
      process.stdin.removeListener("error", onError);
      // Pause so we don't consume bytes meant for the next call
      if (typeof process.stdin.pause === "function") process.stdin.pause();
    };

    if (typeof process.stdin.resume === "function") process.stdin.resume();
    process.stdin.on("data", onData);
    process.stdin.on("end", onEnd);
    process.stdin.on("error", onError);
  });
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Send a ROARMessage via stdio (newline-delimited JSON).
 *
 * Writes one JSON line to stdout, reads one JSON line from stdin,
 * and returns the parsed response ROARMessage.
 *
 * This is the ROAR equivalent of the MCP stdio transport — it lets two
 * processes communicate by piping each other's stdin/stdout.
 *
 * @param message - The message to send (should already be signed).
 * @returns The response ROARMessage read from stdin.
 * @throws ConnectionError if stdin reaches EOF before a response arrives.
 */
export async function stdioSend(message: ROARMessage): Promise<ROARMessage> {
  const line = JSON.stringify(messageToWire(message));
  writeLine(line);

  const raw = await readLine();
  if (!raw) {
    throw new Error("stdioSend: EOF on stdin — remote agent closed");
  }

  return messageFromWire(JSON.parse(raw) as Record<string, unknown>);
}
