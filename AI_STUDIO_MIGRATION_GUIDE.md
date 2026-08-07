# Google AI Studio Migration Guide

Този документ разделя миграцията на MoviesFeed на малки задачи, подходящи за
ограничения дневен контекст на Google AI Studio. Целта е работещ MVP, а не
перфектна архитектура от първия опит.

## Project Identity

Препоръчано работно име: **MediaDock**.

Името не ограничава продукта до movies feed и остава подходящо за бъдещи
`watchlist`, `download queue`, watched status и други лични media workflows.
Използвай следните временни identifiers, освен ако не са заети:

- Product name: `MediaDock`
- Repository name: `mediadock`
- Python package: `media_dock`
- Frontend display name: `MediaDock`
- Firebase project ID: избери уникална производна, без лични данни

Провери наличност на repository/domain/project ID и евентуални конфликти с
търговски марки преди публично представяне. Смяната на display name не трябва да
променя Firestore contracts.

## Target MVP

- Python scanner чете RSS feeds веднъж дневно чрез GitHub Actions.
- Scanner-ът обогатява новите заглавия чрез OMDb и записва в Cloud Firestore.
- OMDb резултатите се кешират във Firestore.
- React + Vite + TypeScript показва каталог в GitHub Pages.
- Google Sign-In и email allowlist ограничават достъпа.
- Каталогът пази история без автоматично изтриване и се зарежда с pagination.
- Frontend-ът използва repository boundary, готов за бъдещи контролирани writes.
- Текущият проект остава в `legacy/` като sanitized reference.

GitHub Pages изпълнява само статичния frontend. Python scanner-ът не може да
работи там и затова се стартира от GitHub Actions.

## Decisions

| Area | Decision |
| --- | --- |
| Database | Cloud Firestore |
| Authentication | Google Sign-In with explicit email allowlist |
| Scanner runtime | Scheduled GitHub Actions workflow plus `workflow_dispatch` |
| Frontend hosting | GitHub Pages project site |
| History | No automatic title retention cleanup |
| MVP search | Client-side search over loaded pages |
| Catalog writes | Firebase Admin SDK only |
| Future client writes | Owner-scoped collections behind validated rules |
| Technical docs | Compact English files under `docs/ai/` |
| Guide language | Bulgarian; commands and identifiers remain English |

## Security Preflight

Изпълни това преди качване или преместване на legacy файловете.

1. Ротирай OMDb ключа, който в момента присъства в track-вания `config.json`.
2. Замени secret стойностите с environment variables.
3. Добави `.env.example` само с имена и празни/example стойности.
4. Съхранявай `OMDB_API_KEY` и Firebase Admin credentials в GitHub Secrets.
5. Не поставяй service-account JSON във frontend, Git history или AI prompt.
6. Firebase web configuration не е secret, но не дава права без коректни rules.
7. Не изпращай `data/` към AI Studio: съдържанието не е нужно за повечето задачи.

Ако secret вече е commit-нат, премахването от последния файл не е достатъчно.
Ротирай го независимо дали ще чистиш Git history.

## Intended Repository Layout

```text
MoviesFeed/
|-- legacy/                       # Sanitized current implementation
|-- backend/
|   |-- src/movies_feed/
|   `-- tests/
|-- frontend/
|   |-- src/
|   `-- tests/
|-- firebase/
|   |-- firestore.rules
|   `-- firestore.indexes.json
|-- docs/ai/
|   |-- PROJECT_CONTEXT.md
|   |-- ARCHITECTURE.md
|   |-- DATA_CONTRACTS.md
|   |-- IMPLEMENTATION_STATUS.md
|   `-- TESTING.md
|-- .github/workflows/
|-- README.md
|-- LOCAL_DEVELOPMENT.md
|-- DEPLOYMENT.md
`-- AI_STUDIO_MIGRATION_GUIDE.md
```

`legacy/rutracker_parser.py` и parser fixtures са източник за директно
преизползване. `movie_scanner.py`, `report_gen.py` и HTML template-ът са
поведенческа референция. Локалният JSON storage и HTML generation не трябва да
се пренасят като архитектура в новото приложение.

## Efficient AI Studio Workflow

За всеки prompt:

1. Започни в нов chat, ако предишният е натрупал несвързан контекст.
2. Качи веднъж sanitized project файла/папките от **Safe Initial Upload**.
3. Остави модела сам да намери минималните related files, като използва
   **Context** като search hint, а не като ръчен upload checklist.
4. Поискай промени само във файловете от **Edit scope**.
5. Прегледай diff-а и изпълни **Verification** локално.
6. Не продължавай, ако **Stop condition** не е изпълнено.
7. Направи малък commit/checkpoint преди следващия prompt.
8. Актуализирай AI docs само ако договор, команда или milestone се е променил.

Не добавяй нови файлове към AI Studio, освен ако моделът посочи конкретен липсващ
файл, който блокира текущата задача. Никога не добавяй генерирани build/data файлове.

### Recommended System Prompt

Задай следния system prompt веднъж за проекта. Той определя постоянните правила;
не го повтаряй във всеки task prompt.

```text
You are the implementation agent for MediaDock, an incremental migration of an existing Python RSS/OMDb media scanner and generated HTML dashboard to a Python backend, Cloud Firestore, Firebase Authentication, and a React + Vite + TypeScript frontend deployed on GitHub Pages.

Work only from the files available in the uploaded project. For each task, locate the smallest relevant set of files yourself. Treat the task's Context field as a search hint, not as a complete or mandatory attachment list. Start with docs/ai/PROJECT_CONTEXT.md, then read at most the one or two specialized docs and nearby implementation files needed for the current task. Do not scan or summarize every uploaded file unless the task explicitly requires a repository-wide audit.

Follow AI_STUDIO_MIGRATION_GUIDE.md and the contracts in docs/ai/. If instructions conflict, use this precedence: current user task; DATA_CONTRACTS.md for stored data/query/security contracts; ARCHITECTURE.md for boundaries; PROJECT_CONTEXT.md for product behavior; then legacy code as behavioral reference. Report any unresolved conflict before editing.

Execute exactly one task ID at a time. Respect Allowed edit scope, Verification, and Stop condition. Do not continue to the next task, add speculative features, perform broad refactors, or redesign unrelated UI. Prefer the smallest change consistent with existing project patterns.

Before editing, state briefly: the files you selected, one falsifiable implementation hypothesis, and the focused check that can disprove it. After editing, run the narrowest available verification first. If you cannot run a command in this environment, say so exactly and provide the command for local execution; never claim an unrun check passed.

Security rules are mandatory. Never request, reveal, reproduce, or store real API keys, tokens, Firebase Admin/service-account credentials, private catalog exports, or authentication data. Firebase web configuration may be public, but authorization must rely on Authentication and Firestore rules. Browser writes to server-managed catalog, cache, scan-run, and allowlist data remain denied. Do not invent a writable user schema before DATA_CONTRACTS.md defines a concrete feature and tests.

Keep backend domain/application logic independent from CLI, HTTP, and Firebase initialization. Keep React components independent from direct Firestore query APIs by using typed repository interfaces. Preserve deterministic IDs, idempotent writes, cursor pagination, parser fixture behavior, and the documented GitHub Pages base-path constraints.

Update docs/ai files only when their owned contract, verified command, or current milestone changes. Preserve their line budgets, replace stale facts instead of appending history, and never turn them into a work diary.

At the end of each task return only: changed files and purpose; verification commands actually run and results; blockers or residual risks; and whether the Stop condition is satisfied. Then stop and wait for the next task.
```

Ако AI Studio има отделни полета за system instructions и project knowledge,
постави горния текст в system instructions, а качените файлове в project knowledge.
Не поставяй task-specific P00-P15 инструкции в system prompt.

### First Message Before Uploading Files

AI Studio изисква начален prompt преди upload. Изпрати само следния текст и
изчакай моделът да потвърди, че е готов за файловете:

```text
Initialize the MediaDock project described by the system instructions. I will now upload the sanitized existing implementation and compact project documentation. Do not generate or edit code yet. Acknowledge the project and wait for my P00 task after the upload is complete.
```

Ако моделът започне да генерира приложение веднага, прекъсни го и повтори
последните две изречения. Не приемай генериран код преди upload-а като основа.

### Safe Initial Upload

В момента нямаш `legacy/` папка. Това е очаквано: при P00 AI Studio трябва да
създаде `legacy/` и да постави в нея качените файлове на старото приложение.
Не създавай папката ръчно само заради upload-а.

Преди upload ръчно премахни реалния OMDb key от `config.json`. Замени стойността
с празен string или placeholder като `REPLACE_WITH_OMDB_API_KEY`. Не разчитай AI
Studio да премахне ключ, след като вече си го изпратил. Реалният ключ трябва и да
бъде ротиран, защото е присъствал в track-ван файл.

#### Качи тези цели папки

Можеш да ги attach-неш като цели папки, като запазиш вътрешната им структура:

```text
docs/
`-- ai/
   |-- PROJECT_CONTEXT.md
   |-- ARCHITECTURE.md
   |-- DATA_CONTRACTS.md
   |-- IMPLEMENTATION_STATUS.md
   `-- TESTING.md

tests/
|-- test_rutracker_parser.py
`-- fixtures/
   |-- movies_feed.atom
   `-- series_feed.atom

templates/
`-- dashboard_template.html

scripts/
|-- run_scanner.ps1
`-- run_scanner.sh
```

Ако AI Studio не поддържа folder upload в използвания интерфейс, избери всички
файлове от съответната папка наведнъж. Провери след upload, че Atom fixtures са
останали логически под `tests/fixtures/`, а template-ът под `templates/`.

#### Качи тези root файлове поотделно

```text
AI_STUDIO_MIGRATION_GUIDE.md
README.md
LOCAL_DEVELOPMENT.md
DEPLOYMENT.md
.gitignore
config.json                 # Само след премахване на реалния OMDb key
requirements.txt
movie_scanner.py
rutracker_parser.py
report_gen.py
```

Това е пълният initial upload за P00. `QUICKSTART.md`, `NAS_QUICKSTART.md`,
`CHANGELOG.md` и `SUMMARY.md` не са необходими за P00; качи ги по-късно само ако
искаш AI Studio да запази или обедини тяхна документация.

#### Не качвай тези папки и файлове

```text
data/                       # Реален каталог, cache и scan history
output/                     # Генерирани HTML reports
.git/
.env
.env.*                      # С изключение на бъдещия безопасен .env.example
*.log
*service-account*.json
firebase-admin*.json
venv/
.venv/
__pycache__/
node_modules/
dist/
```

Не качвай real API keys, Firebase Admin credentials, auth tokens, emulator exports,
screenshots или други големи файлове, освен ако конкретна по-късна задача не ги
изисква.

#### Какво трябва да се получи след P00

AI Studio трябва да върне структура, в която старите runtime файлове са под
`legacy/`, приблизително така:

```text
legacy/
|-- movie_scanner.py
|-- rutracker_parser.py
|-- report_gen.py
|-- requirements.txt
|-- config.json             # Без secret; чете OMDB_API_KEY от environment
|-- scripts/
|-- templates/
`-- tests/
```

Root documentation (`AI_STUDIO_MIGRATION_GUIDE.md`, `README.md`,
`LOCAL_DEVELOPMENT.md`, `DEPLOYMENT.md`) и `docs/ai/` остават извън `legacy/`.

### What to Send for Each Task

След initial upload не е нужно ръчно да attach-ваш related files за всяка задача.
Моделът трябва сам да ги намери сред качените файлове. Полето **Context** остава
hint за модела и за твоя проверка дали нужният файл изобщо е бил качен.

Не изпращай само текста в **Prompt**. **Edit scope**, **Verification** и
**Stop condition** ограничават модела и трябва също да присъстват в съобщението.

Използвай този кратък execution envelope:

```text
Task: <PROMPT_ID_AND_TITLE>

Context search hints:
- <copy Context; locate these or their current equivalents in the uploaded project>

Allowed edit scope:
- <copy Edit scope>

Implementation instructions:
<copy only the text inside the Prompt code block>

Verification:
<copy Verification>

Stop condition:
<copy Stop condition>

Return: changed-file summary, commands/checks actually run, their results, and blockers. Do not continue with the next task.
```

Не е нужно да копираш обяснителния текст на целия guide или да изброяваш точните
качени имена. Копирай **Context** като search hint в envelope-а. Ако AI Studio
каже, че конкретен необходим файл липсва, тогава добави само него. Ако не може да
изпълни команда, трябва да я посочи точно; изпълни я локално преди следващия prompt
и върни само релевантния error output при неуспех.

### Context Loading Matrix

| Task | Always include | Add only when relevant |
| --- | --- | --- |
| Parser/backend | `PROJECT_CONTEXT.md` | parser source, fixture, `TESTING.md` |
| Firestore model | `PROJECT_CONTEXT.md` | `DATA_CONTRACTS.md`, `ARCHITECTURE.md` |
| Security rules | `DATA_CONTRACTS.md` | `ARCHITECTURE.md`, rules/tests |
| Frontend | `PROJECT_CONTEXT.md` | `DATA_CONTRACTS.md`, relevant components |
| CI/deployment | `PROJECT_CONTEXT.md` | `TESTING.md`, `DEPLOYMENT.md`, workflow |
| Resume work | Relevant docs above | `IMPLEMENTATION_STATUS.md` |

Таблицата инструктира модела какво да прочете от вече качения project knowledge.
Тя не е списък с файлове, които трябва ръчно да добавяш при всяко съобщение.

## Documentation Budgets

| File | Purpose | Target maximum |
| --- | --- | --- |
| `PROJECT_CONTEXT.md` | Stable project entry context | 120 lines |
| `ARCHITECTURE.md` | Components and boundaries | 160 lines |
| `DATA_CONTRACTS.md` | Firestore and query contracts | 220 lines |
| `IMPLEMENTATION_STATUS.md` | Cross-session handoff | 100 lines |
| `TESTING.md` | Canonical command index | 120 lines |

Когато файл надвиши бюджета, замени остарялото съдържание вместо да добавяш
дневник. Не записвай големи code snippets, commit history или rationale, което
може да бъде намерено в кода и Git.

## Firestore Boundary

Преди имплементацията стабилизирай следния модел:

- `titles/{titleId}`: нормализирани OMDb metadata и numeric query fields.
- `titles/{titleId}/occurrences/{occurrenceId}`: torrent/feed появявания.
- `omdbCache/{cacheKey}`: OMDb payload, lookup key и cache timestamps.
- `scanRuns/{runId}`: run status, counters, start/end timestamps и error summary.
- `allowlist/{uid}`: минимален access document за разрешен потребител.
- `users/{uid}/...`: резервиран owner-scoped namespace за бъдещи client writes.

Използвай `imdbID` за `titleId`, когато е налично. Fallback ID трябва да бъде
детерминистичен hash от normalized title, year и type. Occurrence ID трябва да е
детерминистичен от feed entry ID или torrent URL. Всички дати за заявки са
Firestore timestamps; ratings и votes имат отделни numeric полета.

Catalog, cache и scan-run writes са server-only. MVP клиентът чете каталога, но
не го редактира. Бъдещи user writes се добавят само в owner-scoped namespace,
с field validation и emulator rules tests. Не използвай правило от типа
`allow write: if request.auth != null`.

## Prompt Sequence

Изпълнявай prompts последователно. Замени стойностите в `<...>` преди изпращане.

### P00 - Sanitize and Create the Skeleton

**Context:** root file list, `.gitignore`, `config.json`, this guide.

**Edit scope:** root configuration, `legacy/`, empty target directories.

**Prompt:**

```text
We are starting the MoviesFeed migration. Perform only the repository bootstrap.

1. Place the uploaded current Python/HTML implementation under legacy/. Do not claim that an upload preserves Git history.
2. Do not move AI_STUDIO_MIGRATION_GUIDE.md or the new root operational docs.
3. Confirm the uploaded configuration contains no OMDb secret value, then load the future value from an environment variable.
4. Add a root .env.example without real values and extend .gitignore for env files, service-account files, emulator state, Python, Node and Vite outputs.
5. Create backend/, frontend/, firebase/, docs/ai/ and .github/workflows/ placeholders only when Git needs them.
6. Do not scaffold Python or React yet and do not alter legacy behavior beyond secret loading/path fixes required by the move.

Show the resulting tree and run the existing parser tests from their new location. Stop if a real secret remains in tracked files or parser tests fail.
```

**Verification:** search tracked files for the old key; run the legacy parser test.

**Stop condition:** sanitized tree exists and legacy parser tests pass.

### P01 - Reconcile Seed Documentation

**Context:** all `docs/ai/*.md`, root tree, this guide.

**Edit scope:** `docs/ai/*.md` only.

**Prompt:**

```text
Compare the compact seed documentation with the actual repository after bootstrap.
Correct factual mismatches only. Preserve each file's stated purpose and line budget.
Do not add implementation history, long code examples, speculative features or duplicated commands.
Update IMPLEMENTATION_STATUS.md with the current milestone and exactly one next prompt ID.
Report each corrected mismatch and line counts for all docs/ai files.
```

**Verification:** inspect diff and count lines.

**Stop condition:** docs match the tree and remain within budgets.

### P02 - Scaffold the Python Backend

**Context:** `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `TESTING.md`, legacy parser and tests.

**Edit scope:** `backend/`, affected AI status/testing docs.

**Prompt:**

```text
Create the minimal installable Python backend using the repository's selected tooling.
Copy the title parser and fixture tests from legacy without changing parser behavior.
Use a src layout and make tests runnable through one canonical command.
Do not add Firebase, OMDb, RSS network calls or scanner orchestration yet.
Update TESTING.md only with the verified command and IMPLEMENTATION_STATUS.md only with milestone progress.
Run the parser tests and stop on any parity regression.
```

**Verification:** backend parser test command from `TESTING.md`.

**Stop condition:** copied fixture tests pass without network access.

### P03 - Add Typed Configuration and RSS Models

**Context:** `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, backend parser/config references.

**Edit scope:** backend config/RSS modules and focused tests.

**Prompt:**

```text
Add typed backend configuration loaded from environment variables plus a non-secret feed configuration file.
Add domain models for feed definitions, parsed feed entries and parsed titles.
Add an RSS adapter around feedparser with injectable input/network behavior.
Preserve parse-only behavior and feed type hints from legacy.
Do not call OMDb or Firestore. Add tests using existing Atom fixtures and malformed feed cases.
Run only the focused backend tests first, then the backend suite.
```

**Verification:** focused RSS tests, then complete backend tests.

**Stop condition:** fixture parsing is deterministic and needs no live network.

### P04 - Add the OMDb Client

**Context:** `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, legacy `get_movie_info`, backend models.

**Edit scope:** backend OMDb client/models/tests.

**Prompt:**

```text
Implement an OMDb client with an injected HTTP transport and typed normalized result.
Preserve title+year lookup followed by title-only fallback and explicit daily-limit handling.
Use HTTPS, timeouts and structured errors. Do not implement Firestore caching yet.
Never log or return the API key. Unit tests must mock all HTTP responses, including success, fallback, no match, timeout and limit reached.
```

**Verification:** OMDb unit tests with no outbound requests.

**Stop condition:** all response paths are tested and no key appears in logs/fixtures.

### P05A - Define Repository Contracts and Fakes

**Context:** `ARCHITECTURE.md`, `DATA_CONTRACTS.md`, backend domain models, `TESTING.md`.

**Edit scope:** backend repository interfaces, ID helpers, in-memory fakes, unit tests, relevant data/testing docs.

**Prompt:**

```text
Implement domain repository interfaces, deterministic ID helpers, and in-memory fakes for titles, occurrences, OMDb cache, and scan runs exactly as DATA_CONTRACTS.md defines.
Add unit tests for IDs, merge semantics, cache freshness, and duplicate upserts.
Do not import Firebase, add scanner orchestration, or edit frontend code.
If a contract defect is proven by a test, update DATA_CONTRACTS.md in the same change and keep it within budget.
```

**Verification:** focused repository/ID unit tests, then the backend unit suite.

**Stop condition:** in-memory repeated upserts are idempotent and Firebase is not imported.

### P05B - Add Firestore Admin Adapters

**Context:** `ARCHITECTURE.md`, `DATA_CONTRACTS.md`, P05A repository interfaces/fakes, `TESTING.md`.

**Edit scope:** backend Firestore adapters, Emulator integration tests, relevant data/testing docs.

**Prompt:**

```text
Implement Firebase Admin Firestore adapters for the repository interfaces completed in P05A.
Use deterministic IDs, server timestamps where appropriate, and idempotent merge/upsert semantics.
Add Firestore Emulator integration tests for persistence, duplicate upserts, timestamp behavior, and cache expiry.
Do not change repository interfaces without a failing contract test. Do not add scanner orchestration, security rules, or frontend code.
```

**Verification:** focused Emulator integration tests, then the backend suite.

**Stop condition:** repeating an Emulator upsert creates no duplicate title or occurrence.

### P06 - Implement Scanner Orchestration and CLI

**Context:** `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, backend adapters and legacy scanner.

**Edit scope:** backend application service/CLI/tests and status/testing docs.

**Prompt:**

```text
Compose RSS parsing, title parsing, OMDb cache/client, filtering and Firestore repositories in a scanner application service.
Keep business logic independent from CLI and Firebase initialization.
Support normal scan, --dry-run and --parse-only. Record a scan run summary.
Treat repeated runs as idempotent and do not abort the whole run for one malformed item.
Do not generate HTML and do not add scheduling.
Add tests for cached lookup, filtering, duplicate entries, OMDb limit and partial failures.
```

**Verification:** backend test suite and one fixture-based dry run.

**Stop condition:** a repeated fixture scan has stable document IDs and expected counters.

### P07 - Add Optional Legacy Data Import

**Context:** `DATA_CONTRACTS.md`, a redacted sample of legacy storage, repositories.

**Edit scope:** one backend import command and tests.

**Prompt:**

```text
Add an optional one-time command that imports legacy data_storage.json into the current repository interfaces.
Map OMDb fields to the current normalized schema and create deterministic occurrences.
Support --dry-run, summary counters and safe reruns. Never require the real data file in tests or commit it.
Use a minimal synthetic fixture. Do not weaken schema contracts to preserve unused legacy fields.
```

**Verification:** import tests and two consecutive dry/test imports.

**Stop condition:** second import produces no duplicates.

### P08 - Add Firestore Rules and Emulator Tests

**Context:** `ARCHITECTURE.md`, `DATA_CONTRACTS.md`, repository queries.

**Edit scope:** `firebase/`, rules test package, affected testing/data docs.

**Prompt:**

```text
Create Firestore rules and emulator rule tests for the documented access model.
Test: unauthenticated denial; authenticated non-allowlisted denial; allowlisted catalog read; and all catalog/cache/scan client writes denied.
Keep the reserved users/{uid} namespace denied until a concrete watchlist or download-queue schema is added to DATA_CONTRACTS.md with owner-access and field-validation tests. Document the extension point, but do not invent a placeholder writable schema.
Do not enable a product write feature and do not use blanket authenticated writes.
Create only indexes required by currently implemented queries.
Run rules tests against the emulator.
```

**Verification:** Firebase rules test command from `TESTING.md`.

**Stop condition:** the permission matrix is executable and fully passing.

### P09A - Scaffold React and Firebase Auth

**Context:** `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `TESTING.md`.

**Edit scope:** frontend scaffold, Firebase initialization, auth UI/tests, affected testing/status docs.

**Prompt:**

```text
Create a Vite React TypeScript frontend using versions supported by the current environment and record the selected versions.
Initialize Firebase from VITE_ public configuration and implement Google Sign-In, auth loading, access-denied, and sign-out states.
Add focused auth tests with Firebase mocked at the adapter boundary.
Do not implement catalog queries, catalog UI, client writes, or direct Firestore access yet.
```

**Verification:** focused auth tests, typecheck, and production build.

**Stop condition:** auth states pass tests and the build contains no Admin credentials.

### P09B - Add the Frontend Repository Boundary

**Context:** `PROJECT_CONTEXT.md`, `ARCHITECTURE.md`, `DATA_CONTRACTS.md`, P09A frontend types/config.

**Edit scope:** frontend repository interfaces/adapters/tests and affected testing/status docs.

**Prompt:**

```text
Define typed catalog repository interfaces and a Firestore read adapter.
Components must not import Firestore query APIs directly.
Leave an explicit interface extension point for future owner-scoped user-data write repositories, but add no write UI, writable schema, or placeholder write calls.
Add focused repository tests with Firebase mocked at the adapter boundary.
Do not build catalog presentation or pagination yet.
```

**Verification:** focused repository tests, typecheck, and production build.

**Stop condition:** the repository boundary is tested and no component imports Firestore query APIs.

### P10 - Implement Catalog Query and Pagination

**Context:** `DATA_CONTRACTS.md`, repository interface, implemented indexes/rules.

**Edit scope:** frontend catalog data layer/hooks/components and tests.

**Prompt:**

```text
Implement newest-first catalog loading and cursor-based Load more pagination through the repository interface.
Use numeric query fields and stable tie-breaking exactly as DATA_CONTRACTS.md specifies.
Handle loading, empty, error, retry and end-of-results states without changing the visual design yet.
Do not fetch the full collection and do not implement full-text search.
Add tests for first page, next cursor, duplicate suppression, retry and final page.
```

**Verification:** focused frontend tests, typecheck and build.

**Stop condition:** pagination is stable and uses no offset/full-collection query.

### P11A - Rebuild Catalog Presentation

**Context:** relevant legacy template/report sections, frontend models and `PROJECT_CONTEXT.md`.

**Edit scope:** frontend catalog presentation components/styles/tests only.

**Prompt:**

```text
Rebuild catalog presentation as React components: semantic responsive poster grid, title metadata, ratings, quality/type indicators, and safe torrent/IMDb links.
Use the legacy template only as behavior and visual reference.
Add loading placeholders, image fallback, keyboard/touch accessibility, and focused component tests.
Do not add search, filters, sorting, a broad redesign, or settings that expose secrets/private feed URLs.
```

**Verification:** focused component tests, typecheck, build, and desktop/mobile review.

**Stop condition:** catalog presentation and external-link behavior pass tests on desktop and mobile layouts.

### P11B - Add Search, Filters and Sorting

**Context:** `PROJECT_CONTEXT.md`, frontend catalog models/presentation, legacy filter behavior.

**Edit scope:** frontend filter/sort state, controls, pure logic, and focused tests.

**Prompt:**

```text
Add pure, unit-tested search, filter, and sort logic for already loaded catalog items.
Support type, country, quality, separate movie/series rating thresholds, minimum votes, and sorting.
Make it explicit in the UI that search covers loaded items, preserve accessible keyboard/touch controls, and add an empty-filtered-result state.
Do not change Firestore queries, fetch the full catalog, add full-text infrastructure, or broadly redesign P11A components.
```

**Verification:** focused logic/component tests, typecheck, build, and desktop/mobile review.

**Stop condition:** functional parity passes for loaded pages without changing pagination/query behavior.

### P12 - Add Continuous Integration

**Context:** `TESTING.md`, package manifests and current test commands.

**Edit scope:** CI workflow files and minimal command documentation.

**Prompt:**

```text
Add pull-request CI for backend tests and frontend test/typecheck/build.
Use dependency caching, pinned major action versions and least permissions.
Run Firestore Emulator tests in the appropriate job without production credentials.
Do not add deployment or scheduled scans yet.
Keep workflow commands identical to TESTING.md and update that file only if a verified command changes.
```

**Verification:** validate workflow syntax and run all referenced commands locally.

**Stop condition:** CI contains no production secret requirement for tests.

### P13 - Add Daily Scanner Workflow

**Context:** backend CLI docs, `ARCHITECTURE.md`, draft `DEPLOYMENT.md`.

**Edit scope:** one scanner workflow and deployment documentation.

**Prompt:**

```text
Add a daily GitHub Actions scanner workflow with schedule and workflow_dispatch.
Use concurrency to prevent overlapping writes, minimal permissions, explicit timeout and the backend's canonical command.
Read OMDB_API_KEY and Firebase Admin credentials only from GitHub Secrets. Prefer a base64 or workload-identity approach documented consistently; never write credentials into tracked files or logs.
Include a manual dry-run input when practical and document first-run verification and rerun behavior.
Do not deploy the frontend in this workflow.
```

**Verification:** inspect permissions/secret references and manually dispatch a dry run.

**Stop condition:** dry run succeeds without production writes or secret output.

### P14 - Deploy the Frontend to GitHub Pages

**Context:** frontend config, `DEPLOYMENT.md`, repository name `<REPOSITORY_NAME>`.

**Edit scope:** Vite routing/base config, Pages workflow and deployment docs.

**Prompt:**

```text
Add GitHub Pages deployment for the Vite frontend as a project site.
Set the base path from the repository name, build with the public Firebase VITE_ variables, upload the Pages artifact and use official Pages actions with least permissions.
Ensure client routing and refresh behavior work with the chosen routing strategy.
Document Firebase Authorized Domains, repository Pages settings, required variables and post-deploy checks.
Do not put Firebase Admin credentials or OMDb keys into the frontend job.
```

**Verification:** local production build, artifact path inspection and deployed smoke test.

**Stop condition:** login and catalog loading work at the project-site URL after refresh.

### P15 - Final Integration and Documentation Audit

**Context:** all compact AI docs, root runbooks, workflows and acceptance checklist below.

**Edit scope:** defects found by checks and documentation corrections only.

**Prompt:**

```text
Audit the MVP against the documented contracts. Do not perform broad refactors.
Verify parser parity, idempotent scanning, OMDb cache reuse, permission matrix, auth allowlist, pagination, filters, links, scheduled/manual scan, Pages refresh behavior and secret separation.
Reconcile README.md, LOCAL_DEVELOPMENT.md, DEPLOYMENT.md and docs/ai without duplicating sources of truth.
Compress AI docs that exceed their budgets and set IMPLEMENTATION_STATUS.md to the next real task or MVP complete.
List residual risks separately from required fixes.
```

**Verification:** all canonical test/build commands plus manual deployment checklist.

**Stop condition:** all MVP acceptance criteria pass or remaining blockers are explicit.

## Recovery Prompts

Използвай само съответния prompt и приложи най-малката корекция.

### Test or Parser Regression

```text
Diagnose this failing test using the failing output, the touched implementation and its nearest passing test. Identify one falsifiable root-cause hypothesis, make the smallest correction and rerun the focused test before the full suite. Do not rewrite the parser or update expected values unless the documented contract changed.
```

### Firestore Permission Denied

```text
Classify the failing operation by path, auth state, allowlist state, operation and document shape. Compare it with DATA_CONTRACTS.md and the nearest emulator rule test. Add a failing regression test first, then minimally fix either the query/path or rule. Never broaden access globally.
```

### Missing Firestore Index

```text
Use the exact failing query and emulator/Firestore error to derive the smallest composite index. Confirm the query matches DATA_CONTRACTS.md before editing firestore.indexes.json. Do not add speculative indexes.
```

### GitHub Actions Secret Failure

```text
Inspect only secret names, workflow expressions and sanitized error output. Do not print secret values. Determine whether the failure is missing configuration, encoding, permissions or credential parsing. Apply the smallest workflow/configuration fix and update DEPLOYMENT.md if the operator step changed.
```

### GitHub Pages Blank Screen

```text
Inspect the deployed asset URLs, Vite base, artifact root, browser console and routing behavior. State one root-cause hypothesis and verify it with a local production preview before editing. Do not change Firebase rules unless a network request specifically returns a permission error.
```

### Stale AI Context

```text
Compare the named AI context file only with the implementation files that own its facts. Replace stale facts, remove diary content and keep within its line budget. Do not rewrite unrelated documentation.
```

## Quota-Friendly Sessions

| Session | Prompts | Local checks that use no AI quota |
| --- | --- | --- |
| 1 | P00-P01 | secret scan, tree review, legacy parser tests |
| 2 | P02-P03 | parser and RSS fixture tests |
| 3 | P04, P05A-P05B | mocked OMDb tests, repository and emulator tests |
| 4 | P06-P07 | scanner unit tests and fixture dry runs |
| 5 | P08 | Firebase Emulator rule tests |
| 6 | P09A-P10 | Vitest, typecheck, local production build |
| 7 | P11A-P11B | filter/component tests, browser review |
| 8 | P12-P14 | local CI commands, workflow review, Pages smoke test |
| 9 | P15 | full verification and documentation audit |

Спри сесията след успешен checkpoint. Не използвай оставащия лимит за случайни
refactors или визуални промени извън текущия prompt.

## Milestones

- **M0:** sanitized `legacy/`, safe configuration and accurate seed docs.
- **M1:** parser parity and deterministic fixture-based RSS parsing.
- **M2:** emulator-backed idempotent persistence and OMDb cache.
- **M3:** authenticated, paginated catalog with tested write-ready boundaries.
- **M4:** daily scanner and GitHub Pages deployment.
- **M5:** runbooks, context validation and secret audit complete.

## MVP Non-Goals

- Actual client write feature or admin editor.
- Favorites, notes, watched status or user preferences UI.
- Cloud Functions, Cloud Run or Cloud Scheduler.
- Algolia, Typesense or another full-text search service.
- Push notifications.
- Major visual redesign.
- Automatic deletion of old catalog titles.

## Post-MVP Expansion Order

Когато MVP е стабилен, добавяй write функции една по една:

1. Дефинирай `watchlist` contract в `DATA_CONTRACTS.md`, включително ownership,
   allowed fields, limits, timestamps and deterministic item ID.
2. Добави failing Emulator rules tests за owner CRUD, foreign-user denial и
   invalid fields, след което имплементирай минималните rules.
3. Добави typed frontend write repository и unit tests.
4. Едва тогава добави watchlist UI и optimistic/error states.
5. Повтори същия цикъл отделно за `downloadQueue`; не използвай обща безформена
   user-data колекция.

## Acceptance Checklist

- [ ] No real secret is tracked or included in AI context.
- [ ] Legacy parser fixture behavior is preserved.
- [ ] Repeated scans do not create duplicate titles or occurrences.
- [ ] Valid OMDb cache entries avoid external requests.
- [ ] Scanner failures are summarized without losing the entire run.
- [ ] Unauthenticated and non-allowlisted catalog reads fail.
- [ ] Allowlisted users can read but cannot write catalog documents.
- [ ] Reserved user namespace remains denied until a concrete feature contract exists.
- [ ] Catalog uses cursor pagination and stable ordering.
- [ ] Search and filters work over loaded pages.
- [ ] Backend, rules and frontend tests pass.
- [ ] Daily workflow supports safe manual execution.
- [ ] GitHub Pages login, load and refresh work at the project path.
- [ ] Local and deployment runbooks reproduce the verified process.
- [ ] AI context docs match implementation and remain within budgets.

## Progress Log

Keep this table compact. Git is the detailed history.

| Prompt | Status | Commit | Verification |
| --- | --- | --- | --- |
| P00 | Not started | - | - |
| P01 | Not started | - | - |
| P02 | Not started | - | - |
| P03 | Not started | - | - |
| P04 | Not started | - | - |
| P05A | Not started | - | - |
| P05B | Not started | - | - |
| P06 | Not started | - | - |
| P07 | Not started | - | - |
| P08 | Not started | - | - |
| P09A | Not started | - | - |
| P09B | Not started | - | - |
| P10 | Not started | - | - |
| P11A | Not started | - | - |
| P11B | Not started | - | - |
| P12 | Not started | - | - |
| P13 | Not started | - | - |
| P14 | Not started | - | - |
| P15 | Not started | - | - |
