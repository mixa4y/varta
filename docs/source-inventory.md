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

## Known consolidation gaps

The first baseline preserves working internals before deeper refactoring.
The following items require a deliberate review in later steps:

1. reconcile the draft CMSD repository with the XLSX-based CaseFlow pipeline;
2. decide whether `.caseflow` remains a compatibility name or migrates to
   `.varta`;
3. replace the case-specific evidence-map generator with the generic profile
   contract;
4. align document/event case and proceeding cardinalities with the approved
   domain model;
5. decide when compatibility script/module names containing `caseflow` migrate
   to native VARTA names;
6. choose the authoritative workspace layout for one or multiple cases.
