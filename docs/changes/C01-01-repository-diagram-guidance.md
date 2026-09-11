# VARTA C01-01 — ізоляція repository diagram guidance

```yaml
change_id: VARTA-C01-01
title: Відокремити GitHub Copilot і Mermaid instructions від roadmap/controller
status: TECH_PASS
objective: >-
  Надати двом pre-existing .github files однозначного logical owner і не
  домішувати їх до runtime, документації або Windows launcher roadmap controller.
scope:
  - .github/copilot-instructions.md
  - .github/instructions/mermaid.instructions.md
  - цей change record
  - exact manifest C01-01
out_of_scope:
  - roadmap/controller runtime
  - product runtime або case data
  - інсталяція чи live-перевірка Mermaid extension
source_of_truth: AGENTS.md та exact manifest C01-01
affected_contracts:
  - repository-scoped AI assistant guidance
privacy_impact: >-
  Файли є текстовими інструкціями й не містять матеріалів справи, credentials,
  generated maps або runtime state. Згадані cloud-команди не виконувалися.
originals_impact: none
decision_dependencies: []
migration: none
rollback: >-
  Майбутній Git checkpoint може відкотити тільки цей окремий patch; C01 не
  видаляє й не переписує початкові файли.
tests:
  - exact file inventory та SHA-256
  - staged/untracked privacy scan
  - Markdown/frontmatter inspection
acceptance:
  - обидва .github files належать рівно одному manifest
  - patch не має runtime dependency на roadmap controller
  - checkpoint не використовує broad git add
evidence:
  - pre-C01 controller snapshot містив .github як окремий untracked scope
  - обидва файли є UTF-8 text
  - final privacy scan не знайшов secrets, case identifiers або forbidden paths
  - final manifest/status bijection охоплює всі 18 paths рівно один раз
known_limits:
  - Git не доводить автора або первинне походження untracked files
  - live Mermaid/VS Code extension workflow не є gate package C01
```

## Ownership-рішення

Logical owner — `developer-experience / repository guidance`, а не
`roadmap/controller`. `copilot-instructions.md` лише маршрутизує diagram tasks
до другого файла; `mermaid.instructions.md` описує окремий VS Code workflow.
Ці два файли тому утворюють один самодостатній patch.

Факт існування cloud/login/sync команд у довідковому тексті не означає, що C01
їх запускав або дозволяв зовнішню публікацію. Під час C01 мережевих чи remote
write дій для цього patch не виконано.

## Exact scope

| Path | Role | Inventory SHA-256 | Staging mode |
|---|---|---|---|
| `.github/copilot-instructions.md` | repository router | `4aad5558deb455f6b8bc38baf19219935cfc9dcb5c4fa14ab86bd681dc024f91` | whole file |
| `.github/instructions/mermaid.instructions.md` | Mermaid workflow guidance | `6a91984bb661cef3f6e10c9922c821d2c3726e7509e3206a6f0ddeb7a7be253a` | whole file |
| `docs/changes/C01-01-repository-diagram-guidance.md` | change record | refreshed at final gate | whole file |
| `docs/changes/manifests/C01-01-repository-diagram-guidance.json` | exact manifest | self-listed; no recursive self-hash | whole file |

Жодний із цих шляхів не входить до C01-02. Exact staging виконується тільки
явним pathspec із manifest після окремої команди GitHub checkpoint.

## Verification record

| Check | Result |
|---|---|
| Initial status ownership | `2` files isolated from `12` roadmap/controller files |
| Binary/prohibited-extension check | text-only; prohibited repository extensions absent |
| Secret/case-data scan | passed; zero findings у двох `.github` files |
| Manifest/status bijection | passed; `18` status paths = `18` unique owned paths |
| Git writes | none; index remains empty |

## Known boundary

Цей patch можна перевіряти або відкладати незалежно від roadmap/controller.
Його не слід об'єднувати з C01-02 лише через спільний початковий статус
`untracked`.
