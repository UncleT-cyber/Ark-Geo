import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  domainLabel,
  domainsLabel,
  isCrossDomain,
  caseRisk,
  describeContradiction,
  groupFindingsByDomain,
  statusLabel,
} from './casePresentation.ts';

const summary = (over: Partial<import('../../types').CaseSummary> = {}) => ({
  case_id: 'ARK-CASE-1',
  domain: 'image',
  domains: ['image'],
  investigation_count: 1,
  evidence_count: 3,
  finding_count: 1,
  cross_domain_contradictions: 0,
  status: 'done',
  updated_at_ms: 1,
  ...over,
});

const view = (over: Partial<import('../../types').CaseView> = {}) => ({
  case_id: 'ARK-CASE-1',
  domain: 'cross',
  domains: ['image', 'osint'],
  investigation_ids: [],
  objectives: [],
  status: 'done',
  evidence_count: 3,
  finding_count: 0,
  findings: [],
  domains_by_finding: [],
  cross_domain_contradictions: [],
  audit_trail: [],
  graph: { case_id: 'ARK-CASE-1', nodes: {}, edges: [], findings: [] },
  ...over,
});

test('domainLabel renders cross as CROSS-DOMAIN', () => {
  assert.equal(domainLabel('cross'), 'CROSS-DOMAIN');
  assert.equal(domainLabel('image'), 'IMAGE');
  assert.equal(domainLabel(''), 'UNKNOWN');
});

test('domainsLabel joins multiple domains with +', () => {
  assert.equal(domainsLabel(['image', 'osint']), 'IMAGE + OSINT');
  assert.equal(domainsLabel(['network']), 'NETWORK');
  assert.equal(domainsLabel([]), 'NO EVIDENCE');
});

test('isCrossDomain requires two domains', () => {
  assert.equal(isCrossDomain({ domains: ['image', 'osint'] }), true);
  assert.equal(isCrossDomain({ domains: ['image'] }), false);
  assert.equal(isCrossDomain({ domains: [] }), false);
});

test('caseRisk ranks cross-domain conflicts highest', () => {
  assert.equal(caseRisk(summary({ cross_domain_contradictions: 1 })), 'critical');
  assert.equal(caseRisk(summary({ domains: ['image', 'osint'] })), 'medium');
  assert.equal(caseRisk(summary()), 'low');
});

test('describeContradiction names both domains and tools', () => {
  const s = describeContradiction({
    edge_id: 'E1', src_domain: 'image', dst_domain: 'osint',
    src_tool: 'resolve_telemetry', dst_tool: 'geocode_place',
    src_claim: 'a', dst_claim: 'b',
  });
  assert.match(s, /IMAGE \(resolve_telemetry\)/);
  assert.match(s, /OSINT \(geocode_place\)/);
});

test('groupFindingsByDomain counts and sorts, unattributed last by count', () => {
  const v = view({
    findings: [
      { finding_id: 'F1', case_id: 'c', claim_type: 'location', claim: '', value: {},
        confidence: 1, supporting_node_ids: [], contradicting_node_ids: [],
        finding_type: 'other', severity: 'medium', status: 'draft', domain: 'image' },
      { finding_id: 'F2', case_id: 'c', claim_type: 'source', claim: '', value: {},
        confidence: 1, supporting_node_ids: [], contradicting_node_ids: [],
        finding_type: 'other', severity: 'medium', status: 'draft', domain: 'osint' },
      { finding_id: 'F3', case_id: 'c', claim_type: 'location', claim: '', value: {},
        confidence: 1, supporting_node_ids: [], contradicting_node_ids: [],
        finding_type: 'other', severity: 'medium', status: 'draft', domain: null },
    ],
  });
  const groups = groupFindingsByDomain(v);
  assert.equal(groups.length, 3);
  assert.deepEqual(groups.map(g => g.count), [1, 1, 1]);
  assert.ok(groups.some(g => g.domain === 'unattributed'));
});

test('statusLabel maps backend rollup to a display label', () => {
  assert.equal(statusLabel('done'), 'CLOSED');
  assert.equal(statusLabel('paused'), 'PAUSED');
  assert.equal(statusLabel('weird'), 'WEIRD');
});
