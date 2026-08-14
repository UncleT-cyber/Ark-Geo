/**
 * Shared entity model — stable IDs and relationships for THE ARK.
 *
 * Every important entity has a stable ID and parent relationships:
 *   Tenant → Workspace → Case → Evidence → Analysis Run → Finding → Report → Audit Event
 *
 * This is the cross-domain investigation context shared by every workbench
 * domain (IMAGE, NETWORK, CASES) and the contextual bottom console. It is NOT
 * a backend data model — it is the shared client-side investigation state that
 * ties the UI together. The backend remains the source of truth for forensic
 * data; this layer holds the case/session relationships.
 */

/** Universally-prefixed stable ID (e.g. "ARK-CASE-3F8A1B2C"). */
export type EntityId = string;

/** The active investigation domain. */
export type DomainId = 'image' | 'network' | 'cases' | 'secops';

/** Root organizational boundary. */
export interface Tenant {
  id: EntityId;
  name: string;
}

/** A workspace owned by a tenant. */
export interface Workspace {
  id: EntityId;
  tenantId: EntityId;
  name: string;
}

/**
 * A Case is the cross-domain investigation container. A case may hold image
 * evidence, network evidence, or both. It is the unit an analyst opens and
 * closes and the unit the contextual console binds to.
 */
export interface Case {
  id: EntityId;            // ARK-CASE-XXXXXXXX
  workspaceId: EntityId;
  title: string;
  domain: DomainId;
  createdAt: number;
  updatedAt: number;
  status: 'open' | 'closed';
}

/**
 * An Evidence asset inside a case (an image, a packet capture, etc.).
 * For IMAGE, the evidence references the backend analysis result by SHA-256.
 */
export interface Evidence {
  id: EntityId;            // ARK-EVD-XXXXXXXX (stable hash-derived)
  caseId: EntityId;
  sha256: string;          // cryptographic anchor to backend analysis
  filename: string;
  mimeType: string;
  byteSize?: number;
  domain: DomainId;
  ingestedAt: number;
}

/** A single Analysis Run over one Evidence asset. */
export interface AnalysisRun {
  id: EntityId;            // ARK-RUN-XXXXXXXX (backend request_id)
  evidenceId: EntityId;
  caseId: EntityId;
  source: string;          // NATIVE_EXIF_HARDWARE | AI_VISION | TELEMETRY | ...
  tier: string;
  confidence: number;
  startedAt: number;
  completedAt: number;
  analysisLog: string[];
}

/** A structured Finding produced by an Analysis Run. */
export interface Finding {
  id: EntityId;            // ARK-FND-XXXXXXXX
  runId: EntityId;
  caseId: EntityId;
  type: string;            // METADATA | INTEGRITY | PROVENANCE | GEOLOCATION ...
  severity: 'LOW' | 'MEDIUM' | 'HIGH';
  status: 'OK' | 'WARNING' | 'ERROR' | 'INFO';
  message: string;
}

/** A Report generated from a case. */
export interface Report {
  id: EntityId;            // ARK-RPT-XXXXXXXX
  caseId: EntityId;
  generatedAt: number;
  format: string;
}

/** An immutable Audit Event in the chain of custody. */
export interface AuditEvent {
  id: EntityId;            // ARK-AUD-XXXXXXXX
  caseId: EntityId;
  evidenceId?: EntityId;
  runId?: EntityId;
  timestamp: number;
  action: string;          // "Evidence acquired" | "Hashes computed" | ...
  detail: string;
  actor: string;
}

/**
 * The full shared investigation context. Every domain reads from and writes
 * to this single context — IMAGE populates it on upload, the contextual
 * console renders it, CASES restores from it.
 */
export interface InvestigationContext {
  tenant: Tenant;
  workspace: Workspace;
  activeCase: Case | null;
  activeEvidence: Evidence | null;
  activeRun: AnalysisRun | null;
  findings: Finding[];
  auditTrail: AuditEvent[];
  reports: Report[];
}

/** Derive a short stable ID from a longer hex/uuid string. */
export function deriveShortId(prefix: string, source: string): EntityId {
  const hex = source.replace(/[^a-f0-9]/gi, '').slice(0, 8).toUpperCase();
  return `ARK-${prefix}-${hex || '00000000'}`;
}

/** Build a case ID from a backend request_id. */
export const caseIdFromRequest = (reqId: string) => deriveShortId('CASE', reqId);

/** Build an evidence ID from an image SHA-256. */
export const evidenceIdFromSha = (sha: string) => deriveShortId('EVD', sha);

/** Build a run ID from a backend request_id. */
export const runIdFromRequest = (reqId: string) => deriveShortId('RUN', reqId);

/** Default single-tenant workspace (local investigator install). */
export const DEFAULT_TENANT: Tenant = {
  id: 'ARK-TENANT-LOCAL',
  name: 'Local Investigator Org',
};

export const DEFAULT_WORKSPACE: Workspace = {
  id: 'ARK-WS-DEFAULT',
  tenantId: DEFAULT_TENANT.id,
  name: 'Default Workspace',
};

/** Initial empty context — no case loaded. */
export function emptyContext(): InvestigationContext {
  return {
    tenant: DEFAULT_TENANT,
    workspace: DEFAULT_WORKSPACE,
    activeCase: null,
    activeEvidence: null,
    activeRun: null,
    findings: [],
    auditTrail: [],
    reports: [],
  };
}
