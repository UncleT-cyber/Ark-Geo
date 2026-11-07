/**
 * Phase D — Reporting engine.
 *
 * Composes a single, court-ready report model from the two finding sources the
 * platform actually produces:
 *   * the deterministic pipeline's findings (`consistency_findings`,
 *     `contradictions`) carried on the analysis result, and
 *   * the ARK AI investigation graph's promoted findings, with their
 *     supporting / contradicting evidence-node lineage.
 *
 * The engine's job is honesty, not prose. It refuses to present a contested
 * claim as a conclusion, marks an unsupported AI hypothesis as a hypothesis,
 * and keeps every claim traceable to the nodes that back it. Pure and
 * dependency-free so it is unit-testable and reusable by the PDF exporter.
 */
import type {
  ConsistencyFinding,
  EvidenceGraphPayload,
  InvestigationFinding,
} from '../../../types';

export type ReportProvenance = 'deterministic' | 'tool' | 'ai_hypothesis';
export type ReportSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type ReportStatus = 'conclusion' | 'contested' | 'hypothesis' | 'unsupported';

export interface ReportFinding {
  id: string;
  type: string;
  severity: ReportSeverity;
  message: string;
  provenance: ReportProvenance;
  status: ReportStatus;
  confidence: number | null;
  supportingNodeIds: string[];
  contradictingNodeIds: string[];
  /** Node ids are resolved to their originating tool for traceability. */
  supportingTools: string[];
}

export interface ReportSection {
  id: string;
  title: string;
  findings: ReportFinding[];
}

export interface InvestigationReportModel {
  generatedAtMs: number;
  totals: {
    findings: number;
    conclusions: number;
    contested: number;
    hypotheses: number;
    unsupported: number;
  };
  severityCounts: Record<ReportSeverity, number>;
  sections: ReportSection[];
}

/** Epistemic weight of a node's provenance — mirrors the backend tiers. */
const _PROVENANCE_WEIGHT: Record<string, number> = {
  cryptographic: 0,
  tool_inference: 1,
  ai_hypothesis: 2,
};

function _normalizeSeverity(raw: string | undefined | null): ReportSeverity {
  const s = (raw ?? '').toUpperCase();
  if (s === 'CRITICAL') return 'CRITICAL';
  if (s === 'HIGH' || s === 'ERROR') return 'HIGH';
  if (s === 'LOW' || s === 'INFO') return 'LOW';
  return 'MEDIUM';
}

/** Map a graph node's provenance to the report's provenance vocabulary. */
function _provenanceFromNodes(
  nodeIds: string[],
  graph?: EvidenceGraphPayload | null,
): ReportProvenance {
  if (!graph || !nodeIds.length) return 'ai_hypothesis';
  let strongest = 2;
  for (const id of nodeIds) {
    const node = graph.nodes?.[id];
    if (!node) continue;
    const w = _PROVENANCE_WEIGHT[node.provenance_type] ?? 2;
    if (w < strongest) strongest = w;
  }
  return strongest === 0 ? 'deterministic' : strongest === 1 ? 'tool' : 'ai_hypothesis';
}

/**
 * Derive the report status of a graph finding.
 *
 * A finding with a higher-tier contradiction is CONTESTED and must not read as
 * a conclusion. A finding with no supporting node is UNSUPPORTED. Otherwise it
 * is a CONCLUSION when backed by deterministic/tool evidence, or a HYPOTHESIS
 * when it rests only on AI nodes.
 */
export function deriveReportStatus(
  finding: InvestigationFinding,
  graph?: EvidenceGraphPayload | null,
): ReportStatus {
  if ((finding.contradicting_node_ids?.length ?? 0) > 0) return 'contested';
  if (!(finding.supporting_node_ids?.length ?? 0)) return 'unsupported';
  const provenance = _provenanceFromNodes(finding.supporting_node_ids, graph);
  return provenance === 'ai_hypothesis' ? 'hypothesis' : 'conclusion';
}

/** Resolve supporting node ids to their originating tool ids. */
function _supportingTools(
  nodeIds: string[],
  graph?: EvidenceGraphPayload | null,
): string[] {
  if (!graph) return [];
  const tools = new Set<string>();
  for (const id of nodeIds) {
    const node = graph.nodes?.[id];
    if (node?.tool_id) tools.add(node.tool_id);
  }
  return [...tools];
}

/** Build a report finding from a promoted graph finding. */
export function fromGraphFinding(
  finding: InvestigationFinding,
  graph?: EvidenceGraphPayload | null,
): ReportFinding {
  const supporting = finding.supporting_node_ids ?? [];
  const contradicting = finding.contradicting_node_ids ?? [];
  return {
    id: finding.finding_id,
    type: finding.finding_type || finding.claim_type || 'FINDING',
    severity: _normalizeSeverity(finding.severity),
    message: finding.claim,
    provenance: _provenanceFromNodes(supporting, graph),
    status: deriveReportStatus(finding, graph),
    confidence: typeof finding.confidence === 'number' ? finding.confidence : null,
    supportingNodeIds: supporting,
    contradictingNodeIds: contradicting,
    supportingTools: _supportingTools(supporting, graph),
  };
}

/** Build a report finding from a deterministic pipeline finding. */
export function fromPipelineFinding(f: ConsistencyFinding, index = 0): ReportFinding {
  return {
    id: `${f.type || 'CONSISTENCY'}-${index}`,
    type: f.type || 'CONSISTENCY',
    severity: _normalizeSeverity(f.severity),
    message: f.message,
    // The consistency engine is deterministic — not an AI guess.
    provenance: 'deterministic',
    status: 'conclusion',
    confidence: null,
    supportingNodeIds: [],
    contradictingNodeIds: [],
    supportingTools: [],
  };
}

const _SEVERITY_ORDER: Record<ReportSeverity, number> = {
  CRITICAL: 0, HIGH: 1, MEDIUM: 2, LOW: 3,
};

/** Most severe first, then most corroborated, then stable by id. */
function _bySeverityThenSupport(a: ReportFinding, b: ReportFinding): number {
  const s = _SEVERITY_ORDER[a.severity] - _SEVERITY_ORDER[b.severity];
  if (s !== 0) return s;
  const support = b.supportingNodeIds.length - a.supportingNodeIds.length;
  if (support !== 0) return support;
  return a.id.localeCompare(b.id);
}

/**
 * Compose the report model. Deterministic findings and graph findings are kept
 * in separate sections so a reader always knows which epistemic tier a claim
 * came from. Graph findings that merely restate a deterministic finding (same
 * claim text) are folded into the deterministic section rather than duplicated.
 */
export function buildReportModel(input: {
  caseId?: string | null;
  pipelineFindings?: ConsistencyFinding[];
  graphFindings?: InvestigationFinding[];
  graph?: EvidenceGraphPayload | null;
  nowMs?: number;
}): InvestigationReportModel {
  const now = input.nowMs ?? Date.now();
  const deterministic = (input.pipelineFindings ?? []).map(fromPipelineFinding);
  const deterministicMessages = new Set(deterministic.map(f => f.message.trim()));

  const graph = (input.graphFindings ?? [])
    .map(f => fromGraphFinding(f, input.graph))
    .filter(f => !deterministicMessages.has(f.message.trim()));

  const deterministicSorted = [...deterministic].sort(_bySeverityThenSupport);
  const graphSorted = [...graph].sort(_bySeverityThenSupport);
  const all = [...deterministicSorted, ...graphSorted];

  const severityCounts: Record<ReportSeverity, number> = { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 };
  for (const f of all) severityCounts[f.severity] += 1;

  const sections: ReportSection[] = [];
  if (deterministicSorted.length) {
    sections.push({ id: 'deterministic', title: 'Deterministic findings', findings: deterministicSorted });
  }
  if (graphSorted.length) {
    sections.push({ id: 'ark-ai', title: 'ARK AI findings', findings: graphSorted });
  }

  return {
    generatedAtMs: now,
    totals: {
      findings: all.length,
      conclusions: all.filter(f => f.status === 'conclusion').length,
      contested: all.filter(f => f.status === 'contested').length,
      hypotheses: all.filter(f => f.status === 'hypothesis').length,
      unsupported: all.filter(f => f.status === 'unsupported').length,
    },
    severityCounts,
    sections,
  };
}
