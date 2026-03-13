/**
 * ROAR Protocol — W3C DID Document generation (Layer 1 — Identity).
 *
 * Mirrors python/src/roar_sdk/did_document.py exactly.
 * No external dependencies.
 *
 * Ref: https://www.w3.org/TR/did-core/
 *
 * Usage:
 *   const doc = DIDDocument.forAgent({
 *     did: "did:roar:agent:planner-abc12345",
 *     publicKey: "<hex-encoded-ed25519-public-key>",
 *     endpoints: { http: "http://localhost:8089" },
 *   });
 *   const jsonLd = doc.toDict();
 */

// ---------------------------------------------------------------------------
// Sub-structures
// ---------------------------------------------------------------------------

export interface VerificationMethod {
  id: string;
  type: string;        // e.g. "Ed25519VerificationKey2020"
  controller: string;
  publicKeyMultibase: string;
}

export interface ServiceEndpoint {
  id: string;
  type: string;        // e.g. "ROARMessaging"
  serviceEndpoint: string;  // URL
}

// ---------------------------------------------------------------------------
// DIDDocument
// ---------------------------------------------------------------------------

export interface DIDDocumentDict {
  "@context": string[];
  id: string;
  controller: string;
  verificationMethod?: Array<{
    id: string; type: string; controller: string; publicKeyMultibase: string;
  }>;
  authentication?: string[];
  assertionMethod?: string[];
  service?: Array<{ id: string; type: string; serviceEndpoint: string }>;
}

export class DIDDocument {
  readonly id: string;
  readonly controller: string;
  readonly verificationMethods: VerificationMethod[];
  readonly authentication: string[];
  readonly assertionMethod: string[];
  readonly services: ServiceEndpoint[];
  readonly created: number;
  readonly updated: number;

  constructor(opts: {
    id: string;
    controller?: string;
    verificationMethods?: VerificationMethod[];
    authentication?: string[];
    assertionMethod?: string[];
    services?: ServiceEndpoint[];
    created?: number;
    updated?: number;
  }) {
    const now = Date.now() / 1000;
    this.id = opts.id;
    this.controller = opts.controller ?? opts.id;
    this.verificationMethods = opts.verificationMethods ?? [];
    this.authentication = opts.authentication ?? [];
    this.assertionMethod = opts.assertionMethod ?? [];
    this.services = opts.services ?? [];
    this.created = opts.created ?? now;
    this.updated = opts.updated ?? this.created;
  }

  /**
   * Create a DID Document for a ROAR agent.
   *
   * @param did        - The agent's DID.
   * @param publicKey  - Hex-encoded Ed25519 public key (optional).
   * @param endpoints  - Map of transport name → URL (optional).
   */
  static forAgent(opts: {
    did: string;
    displayName?: string;
    publicKey?: string;
    endpoints?: Record<string, string>;
  }): DIDDocument {
    const { did, publicKey, endpoints } = opts;

    const verificationMethods: VerificationMethod[] = [];
    const authentication: string[] = [];
    const assertionMethod: string[] = [];
    const services: ServiceEndpoint[] = [];

    if (publicKey) {
      // Multibase hex encoding: 'f' prefix per multibase spec
      verificationMethods.push({
        id: `${did}#key-1`,
        type: "Ed25519VerificationKey2020",
        controller: did,
        publicKeyMultibase: `f${publicKey}`,
      });
      authentication.push(`${did}#key-1`);
      assertionMethod.push(`${did}#key-1`);
    }

    if (endpoints) {
      for (const [transport, url] of Object.entries(endpoints)) {
        services.push({
          id: `${did}#svc-${transport}`,
          type: "ROARMessaging",
          serviceEndpoint: url,
        });
      }
    }

    return new DIDDocument({ id: did, verificationMethods, authentication, assertionMethod, services });
  }

  /** Serialize to a W3C DID Document JSON-LD structure. */
  toDict(): DIDDocumentDict {
    const doc: DIDDocumentDict = {
      "@context": [
        "https://www.w3.org/ns/did/v1",
        "https://w3id.org/security/suites/ed25519-2020/v1",
      ],
      id: this.id,
      controller: this.controller,
    };

    if (this.verificationMethods.length > 0) {
      doc.verificationMethod = this.verificationMethods.map((vm) => ({
        id: vm.id,
        type: vm.type,
        controller: vm.controller,
        publicKeyMultibase: vm.publicKeyMultibase,
      }));
    }

    if (this.authentication.length > 0) {
      doc.authentication = this.authentication;
    }

    if (this.assertionMethod.length > 0) {
      doc.assertionMethod = this.assertionMethod;
    }

    if (this.services.length > 0) {
      doc.service = this.services.map((svc) => ({
        id: svc.id,
        type: svc.type,
        serviceEndpoint: svc.serviceEndpoint,
      }));
    }

    return doc;
  }
}
