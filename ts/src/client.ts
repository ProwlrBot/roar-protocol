/**
 * ROAR Protocol — HTTP client for sending ROAR messages.
 *
 * Mirrors Python's roar_sdk/transports/http.py.
 * Uses Node.js built-in http/https modules — no external dependencies.
 */

import * as http from "http";
import * as https from "https";
import { ConnectionConfig, ROARMessage, messageFromWire, messageToWire } from "./types.js";

export class ROARClient {
  constructor(private readonly config: ConnectionConfig) {}

  /** Send a ROARMessage via HTTP POST to /roar/message and return the response. */
  async send(msg: ROARMessage): Promise<ROARMessage> {
    const url = this.config.url.replace(/\/$/, "");
    if (!url) throw new Error("ROARClient: ConnectionConfig.url is required");

    const body = JSON.stringify(messageToWire(msg));
    const fullUrl = new URL(`${url}/roar/message`);
    const isHttps = fullUrl.protocol === "https:";

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "Accept": "application/json",
      "X-ROAR-Protocol": msg.roar,
      "Content-Length": Buffer.byteLength(body).toString(),
    };

    if (this.config.auth_method === "jwt" && this.config.secret) {
      headers["Authorization"] = `Bearer ${this.config.secret}`;
    }

    return new Promise((resolve, reject) => {
      const timeoutMs = this.config.timeout_ms ?? 30000;
      const transport = isHttps ? https : http;

      const req = transport.request(
        {
          hostname: fullUrl.hostname,
          port: fullUrl.port || (isHttps ? 443 : 80),
          path: fullUrl.pathname,
          method: "POST",
          headers,
        },
        (res) => {
          let data = "";
          let dataBytes = 0;
          const MAX_RESPONSE_BYTES = 1 * 1024 * 1024; // 1 MiB
          res.on("data", (chunk: Buffer | string) => {
            dataBytes += typeof chunk === "string" ? Buffer.byteLength(chunk) : chunk.length;
            if (dataBytes > MAX_RESPONSE_BYTES) {
              res.destroy(new Error(`Response from ${url} exceeded 1 MiB`));
              return;
            }
            data += chunk;
          });
          res.on("end", () => {
            if (res.statusCode && res.statusCode >= 400) {
              reject(
                new Error(
                  `HTTP ${res.statusCode} from ${url}: ${data.slice(0, 200)}`,
                ),
              );
              return;
            }
            try {
              const raw = JSON.parse(data) as Record<string, unknown>;
              resolve(messageFromWire(raw));
            } catch (err) {
              reject(new Error(`Failed to parse response: ${err}`));
            }
          });
        },
      );

      req.setTimeout(timeoutMs, () => {
        req.destroy(new Error(`Request to ${url} timed out after ${timeoutMs}ms`));
      });

      req.on("error", reject);
      req.write(body);
      req.end();
    });
  }
}
