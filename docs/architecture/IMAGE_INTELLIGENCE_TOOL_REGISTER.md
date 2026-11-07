# IMAGE INTELLIGENCE — Verified Tool Register

> Status: **Phase A — read-only audit.** Branch `main` @ `0548d2de`.
> Generated from a live `unified_registry.populate()` plus source inspection.
> Every row was read from source; nothing here is inferred from a config field.

---

## 0. How to read this document

The platform registers **98 tools across 12 domains** in one namespace
(`app/agent/unified_registry.py`), merged from three sources:

- **`ark_substrate`** — `app/agent/tool_registry.py` (the AI-substrate
  `ToolSpec` wrappers over the deterministic pipeline).
- **`ark_catalogue`** — `app/engine/tool_adapter.py` (the forensic catalogue).
- **`cai_native`** — the CAI toolkit (not exercised by image investigations).

Availability is **runtime-gated**, not config-declared. `orchestrator._adapter_available`
removes a tool from the model's advertised set when its binary (`exiftool`,
`nmap`, `gobuster`, `dig`), key (Geospy/TinEye/Serper/Google), or Playwright
runtime is absent. So "registered" ≠ "offered". This is the honest behaviour
required by directive principle #3 and it is preserved.

Legend — **Status**: 🟢 working (deterministic path exists) · 🟡 partial
(needs key/provider to produce a result, degrades honestly) · ⚪ disconnected
(registered but not reachable in the provider loop) · ⛔ placeholder.

---

## 1. IMAGE substrate (`ark_substrate`, domain `image`) — 22 tools

| Tool | Implementation | Provider | Status | Risk | Perm | ARK-callable | UI | Tests |
|---|---|---|---|---|---|---|---|---|
| `extract_exif` | tool_registry.py `_extract_exif` | local (Pillow/piexif) | 🟢 | low | read:evidence | ✅ | FileForensicsTool | test_metadata, test_pipeline |
| `extract_deep_metadata` | `_extract_deep_metadata` → `services/exiftool_service` | exiftool binary | 🟡 binary-gated | low | read:evidence | ✅ | FileForensicsTool | test_workbench_forensics |
| `validate_format` | `_validate_format` | local | 🟢 | low | read:evidence | ✅ | FileForensicsTool | test_integration |
| `compute_custody_hash` | `_compute_custody_hash` | local | 🟢 | low | read:evidence | ✅ | CaseReportView | test_agent_substrate |
| `analyze_ela` | `_analyze_ela` | local | 🟢 | low | read:evidence | ✅ | FileForensicsTool | test_image_upgrades |
| `detect_eof_anomaly` | `_detect_eof_anomaly` | local | 🟢 | low | read:evidence | ✅ | FileForensicsTool | test_image_upgrades |
| `verify_c2pa` | `services/c2pa_service` | local (c2pa lib) | 🟡 lib-gated | low | read:evidence | ✅ | ProvenanceTool | test_workbench_forensics |
| `run_consistency` | `brain/consistency_engine` | local | 🟢 | low | read:evidence | ✅ | InvestigationOverview | test_consensus |
| `detect_contradictions` | `brain/contradiction_engine` | local | 🟢 | low | read:evidence | ✅ | InvestigationOverview | test_phase_* |
| `fuse_geolocation` | `brain/geolocation_fusion` | local | 🟢 | medium | read:evidence | ✅ | SpatialTool | test_cascade |
| `aggregate_consensus` | `brain/consensus_engine` | local | 🟢 | medium | read:evidence | ✅ | SpatialTool | test_consensus |
| `resolve_telemetry` | `services/telemetry_service` | local/provider | 🟡 | low | read:evidence | ✅ | TelecomWorkspace | test_telemetry |
| `reverse_geocode` | tool_registry `_reverse_geocode` | Mapbox / Nominatim | 🟡 key-or-public | low | query:external | ✅ | SpatialTool | test_phase_c |
| `geocode_place` (`osint`) | `_geocode_place` | Nominatim | 🟡 | low | query:external | ✅ | SpatialTool | test_osint_tools |
| `geocode_batch_texts` (`osint`) | `_geocode_batch_texts` | Nominatim | 🟡 | low | query:external | ✅ | SpatialTool | test_osint_tools |
| `fetch_streetview_panorama` | `_fetch_streetview_panorama` | Google Street View | 🟡 key-gated | low | query:external | ✅ | SpatialTool | test_agent_substrate |
| `predict_geospy_coordinates` | `_predict_geospy_coordinates` | GeoSpy | 🟡 key-gated | elevated | call:provider | ✅ | VisionTool | test_cascade |
| `analyze_vision_scene` | `_analyze_vision_scene` | vision LLM | 🟡 key-gated | elevated | call:provider | ✅ | VisionTool | test_ai_gateway |
| `run_vision_ensemble` | `brain/vision_ensemble` | GeoSpy/GeoInfer | 🟡 key-gated | elevated | call:provider | ✅ | VisionTool | test_cascade |
| `run_ocr` | `_run_ocr` | OCR engine | 🟡 | elevated | call:provider | ✅ | VisionTool | test_ocr_fallback |
| `discover_sources` | `services/source_discovery` | provider registry | 🟡 provider-gated | elevated | query:external | ✅ | DiscoveryTool | test_osint_tools |
| `search_reverse_source` | `_search_reverse_source` | pHash + providers | 🟡 provider-gated | elevated | query:external | ✅ | DiscoveryTool | test_osint_tools |
| `brain_analyze` | `brain/pipeline.brain` | local (4-tier) | 🟢 | low | read:evidence | ✅ | InvestigationOverview | test_pipeline |
| `enhance_image` | `_enhance_image` | local | 🟢 | low | read:evidence | ✅ | VisionTool | test_image_upgrades |

---

## 2. IMINT catalogue (`ark_catalogue`, domain `imint`) — 12 tools

These are the forensic-catalogue wrappers (`app/engine/tool_adapter.py:475-501`).
They are registered but, in the current provider loop, several are the
**redundant twins** of the substrate tools above. This duplication is a
Phase B consolidation target, not a defect to delete.

| Tool | Impl | Provider | Status | Notes |
|---|---|---|---|---|
| `imint.exiftool` | `_imint_exiftool` | exiftool | 🟡 binary-gated | twin of `extract_deep_metadata` |
| `imint.c2pa` | `_imint_c2pa` | c2pa lib | 🟡 lib-gated | twin of `verify_c2pa` |
| `imint.phash` | `_imint_phash` | local | 🟢 | perceptual hash |
| `imint.reverse_image` | `_imint_reverse_image` | pHash + providers | 🟡 | twin of `search_reverse_source` |
| `imint.source_discovery` | `_imint_source_discovery` | providers | 🟡 | twin of `discover_sources` |
| `imint.tineye` | `_imint_tineye` | TinEye API | 🟡 key-gated | official API only |
| `imint.serper` | `_imint_serper` | Serper | 🟡 key-gated | |
| `imint.extract_urls` | `_imint_extract_urls` | local (exiftool groups) | 🟡 | needs deep metadata first |
| `imint.geocode` | `_imint_geocode` | Nominatim | 🟡 | |
| `imint.geocode_batch` | `_imint_geocode_batch` | Nominatim | 🟡 | |
| `imint.reverse_geocode` | `_imint_reverse_geocode` | Mapbox/Nominatim | 🟡 | |
| `imint.streetview` | `_imint_streetview` | Google | 🟡 key-gated | |

---

## 3. Case / evidence (`ark_catalogue`, domain `case`) — 6 tools

| Tool | Impl | Status | Notes |
|---|---|---|---|
| `case.attach` | `_case_attach` | 🟢 | create case vault |
| `case.custody_hash` | `_case_custody_hash` | 🟢 | chain-of-custody |
| `case.evidence` | `_case_evidence` | 🟢 | inspect custody |
| `case.list` | `_case_list` | 🟢 | list vaults |
| `evidence.analyst_override` | `_evidence_override` | 🟢 | confirm/reject/needs_review |
| `evidence.analyst_overrides` | `_evidence_overrides` | 🟢 | list overrides |

---

## 4. OSINT / web (supporting image investigations)

| Tool | Domain | Provider | Status | Notes |
|---|---|---|---|---|
| `web_search` | osint | web | 🟡 | |
| `web_fetch` | osint | web | 🟡 | untrusted content — see §6 |
| `inspect_local_path` | osint | local | 🟢 | |
| `browser.*` (12 tools) | web | Playwright | 🟡 runtime-gated | navigate/click/type/extract/screenshot/… |
| `recon.web_search` / `recon.web_fetch` | recon | web | 🟡 | catalogue twins of osint web_* |

**Reverse-image search reality (directive §C5):** `source_discovery.py` is
explicitly provider-agnostic and **hardcodes no provider**; if none is
configured it returns `UNAVAILABLE` with an honest detail
(`source_discovery.py:174-177`). TinEye is only ever called through its official
API and only when a key is present. No unrestricted third-party access is
assumed anywhere.

---

## 5. Registry warnings found during audit

```
[Unified Registry] Ambiguous normalized alias: webfetch
[Unified Registry] Ambiguous normalized alias: siemquery
```

Two pairs normalize to the same id (`web.fetch` vs `webfetch`,
`siem.query` vs `siem_query`). The first registration wins; the second is
skipped. Both raw ids stay separately addressable, so no capability is lost —
but the collision should be made explicit in Phase B. **No image capability is
affected.**

---

## 6. Security notes per capability class

- **External-query tools** (`query:external`) — reverse image, geocode,
  Street View, web fetch — must pass `PolicyGuard` and honor engagement scope.
  They do today via `_adapter_available` + `guard.evaluate`.
- **Provider tools** (`call:provider`) — GeoSpy, vision, OCR, ensemble — are
  `deterministic=False`; their outputs are tier-2 hypotheses and cannot be
  promoted to findings without corroboration (evidence-graph rule).
- **Untrusted web/browser content** is evidence to evaluate, **not**
  instructions. Fencing fetched text against prompt injection is a Phase B
  hardening item (currently the system prompt asks the model to treat runtime
  facts precisely, but fetched text is not explicitly delimited).

---

## 7. What is genuinely missing (vs. the directive's §C list)

The directive asks for capabilities "including" metadata, hashing, C2PA, OCR,
landmark/clue detection, reverse image search, TinEye, browser OSINT,
geospatial, map rendering, source discovery, evidence collection, case
management, report generation. Audit result:

| Directive capability | Exists? | Where |
|---|---|---|
| EXIF/metadata | ✅ yes | `extract_exif`, `extract_deep_metadata` |
| Hashing/integrity | ✅ yes | `compute_custody_hash`, `imint.phash` |
| C2PA/provenance | ✅ yes | `verify_c2pa`, `c2pa_service` |
| OCR/visual analysis | ✅ yes | `run_ocr`, `analyze_vision_scene`, `vision_ensemble` |
| Landmark/environmental clues | ✅ yes (clue extractors) | `app/brain/clue_extractors` (architectural/botanical/OCR/infra/indoor) |
| Reverse-image search | ✅ (provider-gated) | `discover_sources`, `search_reverse_source` |
| TinEye | ✅ (key-gated, official API) | `imint.tineye` |
| Browser OSINT | ✅ (runtime-gated) | `browser.*` |
| Geospatial analysis | ✅ yes | `fuse_geolocation`, `aggregate_consensus` |
| Map rendering | ✅ yes (frontend) | `MapWorkspace.tsx`, `SpatialTool.tsx` |
| Source discovery | ✅ yes | `source_discovery.py` |
| Evidence collection | ✅ yes | `evidence_graph`, `evidence_recorder` |
| Case management | ✅ yes | `case.*`, `CaseExplorer.tsx` |
| Report generation | ✅ yes | `CaseReportView.tsx`, report generator |

**Nothing on the image list is missing.** The gap is not capability; it is
*orchestration wiring, deduplication, and diagnostics.* That is the core
finding of Phase A and shapes the Phase B plan.
