import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyMetadataState } from './metadataAbsence.ts';

test('a missing extraction tool outranks every data claim', () => {
  const s = classifyMetadataState({ deepAvailable: false, metadataStatus: 'STRIPPED_BY_INTERMEDIARY', exifMissing: true });
  assert.equal(s.kind, 'TOOL_UNAVAILABLE');
  assert.equal(s.significant, false);
});

test('stripped metadata is reported as a significant finding', () => {
  assert.equal(classifyMetadataState({ metadataStatus: 'STRIPPED_BY_INTERMEDIARY' }).kind, 'STRIPPED');
  const s = classifyMetadataState({ exifMissing: true, deepAvailable: true });
  assert.equal(s.kind, 'STRIPPED');
  assert.equal(s.significant, true);
  assert.match(s.explanation, /does not by itself prove manipulation/);
});

test('present metadata is ok', () => {
  assert.equal(classifyMetadataState({ metadataStatus: 'EXIF_PRESENT' }).kind, 'PRESENT');
  assert.equal(classifyMetadataState({ deepAvailable: true, fieldCount: 12 }).kind, 'PRESENT');
});

test('a bare absence with no stripping signal is NEVER_PRESENT, not an alarm', () => {
  const s = classifyMetadataState({ deepAvailable: true, fieldCount: 0 });
  assert.equal(s.kind, 'NEVER_PRESENT');
  assert.equal(s.significant, false);
});

test('every state carries an explanation', () => {
  for (const sig of [
    { deepAvailable: false },
    { metadataStatus: 'STRIPPED_BY_INTERMEDIARY' },
    { metadataStatus: 'EXIF_PRESENT' },
    {},
  ]) {
    assert.ok(classifyMetadataState(sig).explanation.length > 0);
  }
});
