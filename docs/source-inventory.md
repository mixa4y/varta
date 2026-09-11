# Source inventory

## Included from CMSD

- domain dataclasses and controlled dictionaries;
- safe KMU №55 transliteration and filename helpers;
- SQLite repository and append-only audit log;
- plugin boundaries for OCR, STT and KEP;
- tests and draft architecture documents.

## Included from CaseFlow

- local loopback server;
- intake and archive-processing pipeline;
- anomaly detector;
- primary HTML/CSS/JavaScript workspace UI;
- generic processing, extraction and staging scripts;
- Windows build/install/update scripts as migration material;
- server and anomaly tests.

## Instruction authority and supersession

- `AGENTS.md` defines the repository, privacy, product and verification
  boundaries.
- `docs/action-algorithm.md` is the canonical execution order; its interactive
  HTML map is a companion view, not a separate source of truth.
- `docs/blueprints/evidence-map-blueprint.md` is the canonical generic Evidence
  Map specification for VARTA.
- Case-specific instructions outside this repository remain read-only migration
  evidence and must not be copied into universal core documentation.
- The older downstream copy of the case-specific map instruction in the external
  ESUD workspace is `SUPERSEDED` for VARTA planning: it predates the current
  intake and snapshot contracts. The protected external file is intentionally
  left unchanged.

## Explicitly excluded

- `00_INBOX`, `01_ОПРАЦЬОВАНО`, `02_РОЗПАКОВАНО`, `03_РЕЄСТР`,
  `99_ПОТРЕБУЄ_ПЕРЕВІРКИ`;
- court documents, archives, signatures and screenshots;
- XLSX registers and manifests containing case data;
- `CaseFlow.exe`, release archives and generated build output;
- generated evidence maps with embedded data;
- `.caseflow` runtime indices, tokens, secrets and logs;
- scripts tied only to a numbered historical batch.

## Approved decisions with pending implementation

The first baseline preserves working internals before deeper refactoring.
C02 approved the target boundaries; the following items remain implementation
work and must not be described as undecided architecture:

1. route the CMSD repository and XLSX-based CaseFlow pipeline through
   application services (`C03`, `C06`, `C09`);
2. migrate read-only `.caseflow` compatibility state to the approved `.varta`
   target only after inventory/reconciliation (`C05`, `C09`, `C15`);
3. replace the case-specific evidence-map generator with the generic profile
   contract;
4. implement approved opaque IDs and many-to-many document/event proceeding
   cardinalities (`C07`, `C08`);
5. decide when compatibility script/module names containing `caseflow` migrate
   to native VARTA names;
6. implement the approved one-workspace/one-DB/many-case layout and explicit
   active-case context (`C05`, `C07`).

Approved decisions are recorded in `architecture/ADR-001`–`ADR-007`; open
archive/encryption/scale/recovery details have owner stages in
`architecture/open-questions.md`.
