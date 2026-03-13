/**
 * ROAR Protocol — did:web method for persistent, DNS-bound agent identities.
 *
 * A did:web DID is tied to a domain name, resolved via HTTPS.
 * The DID Document is hosted at a well-known URL derived from the DID.
 *
 * Format: did:web:example.com  or  did:web:example.com:agents:planner
 * Resolves to:
 *   https://example.com/.well-known/did.json        (no path)
 *   https://example.com/agents/planner/did.json     (with path)
 *
 * Ref: https://w3c-ccg.github.io/did-method-web/
 */

/**
 * Convert a URL to a did:web DID.
 *
 * - Strips the https:// scheme.
 * - Replaces path separators (/) with colons (:).
 * - Removes trailing colons.
 *
 * Examples:
 *   "https://example.com"                  → "did:web:example.com"
 *   "https://example.com/agents/planner"   → "did:web:example.com:agents:planner"
 */
export function urlToDidWeb(url: string): string {
  // Strip scheme
  let stripped = url;
  if (stripped.startsWith("https://")) {
    stripped = stripped.slice("https://".length);
  } else if (stripped.startsWith("http://")) {
    stripped = stripped.slice("http://".length);
  }

  // Encode colons in host:port as %3A (matching Python reference)
  // e.g. "example.com:8080/path" → "example.com%3A8080:path"
  const slashIdx = stripped.indexOf("/");
  let hostPart: string;
  let pathPart: string;

  if (slashIdx === -1) {
    hostPart = stripped;
    pathPart = "";
  } else {
    hostPart = stripped.slice(0, slashIdx);
    pathPart = stripped.slice(slashIdx + 1);
  }

  // Encode port colon in host as %3A
  hostPart = hostPart.replace(":", "%3A");

  // Build DID
  let did = "did:web:" + hostPart;
  if (pathPart) {
    // Replace slashes with colons, strip trailing slash
    const pathSegments = pathPart.replace(/\/$/, "").replace(/\//g, ":");
    if (pathSegments) {
      did += ":" + pathSegments;
    }
  }

  return did;
}

/**
 * Convert a did:web DID to its HTTPS resolution URL.
 *
 * - If the DID has no path (only domain), the URL is
 *   https://<domain>/.well-known/did.json
 * - If the DID has path segments, the URL is
 *   https://<domain>/<path>/did.json
 *
 * Examples:
 *   "did:web:example.com"                  → "https://example.com/.well-known/did.json"
 *   "did:web:example.com:agents:planner"   → "https://example.com/agents/planner/did.json"
 */
export function didWebToUrl(did: string): string {
  if (!did.startsWith("did:web:")) {
    throw new Error(`Not a did:web DID: ${did}`);
  }

  const remainder = did.slice("did:web:".length); // e.g. "example.com" or "example.com:agents:planner"
  const parts = remainder.split(":");
  const domain = parts[0].replace("%3A", ":");

  if (parts.length === 1) {
    return `https://${domain}/.well-known/did.json`;
  }

  const path = parts.slice(1).join("/");
  return `https://${domain}/${path}/did.json`;
}
