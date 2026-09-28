# MediaDock Next - Execution Plan

Това е единственият executable plan за новото приложение. За архитектурен
контекст използвай [migration plan](DOTNET_REACT_MIGRATION_PLAN.md); не го
подавай самостоятелно на plan runner-а.

## Стартиране

В нова Copilot Chat сесия избери `plan-runner-orchestrator` и изпрати:

```text
Run plan docs/MEDIADOCK_NEXT_EXECUTION_PLAN.md only Step 1
```

При `STATUS: PASS`, продължи в същата или нова сесия с:

```text
Run plan docs/MEDIADOCK_NEXT_EXECUTION_PLAN.md resume
```

За непрекъснат run на всички стъпки може да се използва `Run plan
docs/MEDIADOCK_NEXT_EXECUTION_PLAN.md`. Не започвай `resume`, ако Step 1 е
`BLOCKED`; първо разреши посочения prerequisite. Избери модела във VS Code
model picker-а; планът не фиксира непроверен model ID или цена. VS Code
approval prompts за инструменти не могат да бъдат премахнати от плана.

## Общи правила

- Целта е локално работещ MVP под `next/`, не production deploy. Не се
  свързвай към Ubuntu, не променяй router/firewall, не изключвай GitHub Pages и
  не прави cutover.
- Всички application промени са под `next/**`. Root `src/`, `package.json`,
  lockfile, Vite config, `backend/`, `legacy/`, Firebase/Firestore файловете и
  съществуващите `.github/workflows/**` са read-only. Няма import на данни,
  dual-write или runtime зависимости към стария app.
- Новата база е празен PostgreSQL. EF migrations създават schema; не прехвърлят
  данни. Новият app е самостоятелен React + TypeScript + Vite и .NET 10 modular
  monolith под `next/web/` и `next/server/`.
- Не добавяй Google Auth, Firebase, Gemini, microservices, Kubernetes, Redis,
  message broker, MediatR или generic repository в MVP. LAN-only достъпът не е
  authentication; app-ът не трябва да бъде изложен публично без отделно
  решение за authentication и authorization.
- Следвай feature folders и малки, отговорностно ясни файлове. Избягвай
  god-files и дублиране, но не налагай произволен лимит на редове. Предпочитай
  EF Core/Npgsql и feature-specific persistence queries.
- Запази важните parsing/matching правила, idempotent RSS ingestion,
  PostgreSQL constraints, bounded SSRF-защитено fetching, OMDb cache и
  sanitization. Не прави live RSS/OMDb заявки в tests.
- На всяка стъпка изпълни само посочената тясна проверка. Един финален smoke и
  един root frontend regression build са в Step 9. Не изпълнявай broad test
  suites, Markdown/whitespace validation или несвързани команди. Локални npm,
  NuGet restore и Docker са разрешени, ако са налични; не инсталирай системен
  софтуер, не използвай sudo и не искай/показвай secrets.
- Не изтривай файлове/volumes. Не изпълнявай `docker compose down -v`, reset,
  checkout или друга destructive команда. При неясна среда или user-owned
  промяна спри със `BLOCKED`, вместо да я презаписваш.

## Step 1 - Изолиран scaffold

**Dependencies:** няма.

**Scope:** само нови файлове под `next/**`. Ако `next/` вече съдържа файлове,
прочети ги локално и не презаписвай непозната работа.

**Work:** провери `dotnet --version`, `node --version` и `docker compose
version`. При липсващ SDK/runtime спри и посочи prerequisite; не инсталирай
системен софтуер. Създай `next/web/` с React + TypeScript + Vite; `next/server/`
с `MediaDock.sln` и Api, Application, Infrastructure, Worker, UnitTests и
IntegrationTests projects; `next/compose.yaml` с PostgreSQL, health check,
named volume и host port само на `127.0.0.1`; `next/.env.example`, `.gitignore`
и кратък `next/README.md`. Добави минимален liveness endpoint и Vite `/api`
proxy. Не създавай domain logic, migrations, application containers или
scheduler.

**Acceptance:** root app/workflows са непроменени; .NET solution build-ва;
React production build и Compose config минават.

**Validation:**

```powershell
dotnet build next/server/MediaDock.sln
npm --prefix next/web run build
docker compose -f next/compose.yaml config
```

**Stop:** не започвай Step 2. Докладвай липсващи prerequisites или резултата
от проверките.

## Step 2 - Релационен модел

**Dependencies:** Step 1.

**Scope:** `next/server/` persistence code и tests; използвай само
`docs/ai/DATA_CONTRACTS.md` като ограничен behavior reference за нужните
Title/Occurrence полета.

**Work:** добави EF Core/Npgsql `DbContext`, mapping и първата migration.
Моделирай MVP таблиците `titles`, `sources`, `occurrences`, `scan_runs`,
`parse_logs`, `settings` и `metadata_cache`; избягвай Firestore snapshot
структури. Използвай стабилен source item key и database unique constraint за
occurrence idempotency. Дръж вътрешните IDs релационни; не пренасяй Firestore
hash IDs. Не добавяй generic repository.

**Acceptance:** migration създава schema в празен PostgreSQL; integration test
проверява migration, unique constraint и повторно записване на един occurrence.

**Validation:**

```powershell
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --filter "Category=Persistence"
```

Използвай Testcontainers/PostgreSQL; не заменяй с SQLite или mocks.

**Stop:** при липсващ Docker/Testcontainers върни `BLOCKED`; не започвай Step 3.

## Step 3 - Parser и match policy

**Dependencies:** Step 1; изпълнява се след Step 2 за един линеен run.

**Scope:** pure C# code и `MediaDock.UnitTests`; прочети само
`backend/src/movies_feed/rutracker_parser.py`, `match_policy.py`,
`backend/tests/test_rutracker_parser.py`, `backend/tests/test_match_policy.py`
и нужната част от `docs/ai/DATA_CONTRACTS.md`.

**Work:** пренеси title/year extraction, normalization, movie/series feed
compatibility, movie year tolerance, series broadcast-range policy и
country/genre exclusions. Използвай typed accepted/rejected/ambiguous result и
stable reason codes. Копирай само минималните нужни synthetic/public fixtures
в `next/`; не добавяй Python runtime reference.

**Acceptance:** parser/policy са pure и покриват гранични, malformed и
ambiguous inputs с малки unit tests.

**Validation:**

```powershell
dotnet test next/server/tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj --filter "Category=Parsing|Category=Matching"
```

**Stop:** не започвай RSS fetching или API.

## Step 4 - Защитено RSS fetching

**Dependencies:** Step 1.

**Scope:** `MediaDock.Infrastructure` RSS transport и unit tests; прочети само
`backend/src/movies_feed/feed_fetcher.py`,
`backend/tests/test_feed_fetcher.py` и релевантните contract notes в
`docs/ai/DATA_CONTRACTS.md`.

**Work:** добави RSS/Atom transport през injected `HttpClient` с HTTPS/host
policy за текущите feed-ове, DNS/IP защита срещу private/loopback адреси,
redirect revalidation, timeout и response/body/entry limits. Валидирай URL-а
сървърно; не превръщай API-то в произволен fetch proxy. Не добавяй live-network
tests или source plugin framework.

**Acceptance:** tests покриват невалидна схема/host, redirect, private IP,
timeout, прекалено голям response и malformed RSS/Atom.

**Validation:**

```powershell
dotnet test next/server/tests/MediaDock.UnitTests/MediaDock.UnitTests.csproj --filter "Category=RssTransport"
```

Използвай fake HTTP/DNS boundary.

**Stop:** не прави OMDb заявки и не записвай catalog данни.

## Step 5 - Metadata и ingestion

**Dependencies:** Steps 2, 3 и 4.

**Scope:** `MediaDock.Application`, нужния Infrastructure adapter и
`MediaDock.IntegrationTests`; прочети само `metadata_resolver.py`,
`omdb_client.py`, `rss_ingestion.py`, `repository.py` и съответните tests.

**Work:** добави OMDb typed client със server-side `OMDB_API_KEY`, title+year
lookup и title-only fallback, bounded timeout/error handling и Postgres cache
с expiry. Не cache-вай quota/transport/auth failures. Оркестрирай parse -> match
-> metadata -> idempotent PostgreSQL upsert; записвай `scan_runs` статуси и
bounded sanitized `parse_logs`. Malformed entry не трябва да спира останалите
валидни items. Не добавяй Gemini/reparse/audit.

**Acceptance:** mock HTTP + PostgreSQL integration tests доказват успешен scan,
повторно изпълнение без duplicates, confirmed-negative cache и partial result
при entry/provider failure. Нито един test не използва истински API key.

**Validation:**

```powershell
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --filter "Category=Ingestion"
```

**Stop:** не добавяй HTTP endpoints или background schedule.

## Step 6 - Catalog API

**Dependencies:** Steps 2 и 5.

**Scope:** `MediaDock.Api` endpoints/DTOs и API integration tests.

**Work:** добави health/readiness, catalog pagination/search/filters, title
details/occurrences, sources/settings read-write, parse logs и scan history.
Ползвай validated DTOs, stable ordering, async EF queries, OpenAPI metadata и
consistent `ProblemDetails`. Settings/source writes са LAN-trusted MVP, не
автентикирани admin операции; документирай това. Не изпълнявай дълъг scan в
HTTP request и не добавяй `POST scan` endpoint.

**Acceptance:** endpoint tests покриват validation, pagination, empty catalog,
errors и PostgreSQL-backed queries.

**Validation:**

```powershell
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --filter "Category=Api"
```

**Stop:** не променяй root frontend и не започвай UI.

## Step 7 - Самостоятелен React client

**Dependencies:** Step 6.

**Scope:** само `next/web/**`; съществуващите root компоненти са read-only
reference. При нужда прегледай `src/domain/catalog.ts`,
`src/domain/settings.ts`, `src/domain/parseLog.ts` и конкретните catalog/settings
views.

**Work:** добави typed HTTP adapter и MVP catalog, search/filter/pagination,
title details, source/settings редакция и scan/parse history views към новия
API. Покрий loading/empty/error/retry states. Кодът е самостоятелен; няма
Firebase SDK/Auth, root imports, aliases, symlinks или workspace dependency.

**Acceptance:** UI работи с новия API contract, няма secret в browser, а
component/adapter tests покриват pagination, filters и основните error states.

**Validation:**

```powershell
npm --prefix next/web run test
npm --prefix next/web run build
```

**Stop:** не редактирай root `src/`, `package.json` или Vite config.

## Step 8 - Еднократен Worker и schedule

**Dependencies:** Steps 2 и 5.

**Scope:** `MediaDock.Worker`, PostgreSQL concurrency test и нови файлове под
`next/deploy/systemd/`.

**Work:** добави безопасен one-shot Worker command за RSS scan, cancellation,
ненулев exit code при failed/partial run и PostgreSQL advisory lock срещу
припокриване на scheduled/manual runs. За един Ubuntu host използвай host-side
systemd `.service` + `.timer` с `Europe/Sofia` и явна catch-up (`Persistent`)
политика, която изпълнява пропуснатия дневен scan най-много веднъж. Timer-ът
стартира Docker Compose Worker container; не добавяй Quartz, cron container или
втори schedule owner. Не стартирай systemd и не deploy-вай.

**Acceptance:** Worker използва същия ingestion use case; DB lock блокира
едновременен втори scan; systemd unit templates и инструкции са под `next/`.

**Validation:**

```powershell
dotnet test next/server/tests/MediaDock.IntegrationTests/MediaDock.IntegrationTests.csproj --filter "Category=Worker"
```

**Stop:** не се свързвай към Ubuntu и не променяй host services.

## Step 9 - Локален Docker smoke

**Dependencies:** Steps 1-8.

**Scope:** `next/**`; финалният root build е единствената read-only проверка
извън `next/`.

**Work:** завърши Compose конфигурация за PostgreSQL, API/static React app и
one-shot Worker. Новият app се публикува само локално на `127.0.0.1`; Postgres
не е публично достъпен. Подай secrets само през ignored `.env`/host environment;
не създавай истински secrets. Добави изричен one-shot migration command.
Документирай migrations, start/stop, health/log checks и `pg_dump`/restore.

Стартирай локалния stack без volume deletion; изпълни migration command и
провери `/health/ready`, празен `/api/catalog` и зареждането на React SPA. Не
стартирай scan към реални RSS/OMDb. Остави stack-а работещ след успешен smoke и
докладвай URL/командата за спиране. Пусни root frontend build веднъж като
регресионна проверка; не редактирай protected root paths или GitHub workflows.

**Acceptance:** Docker app работи срещу празна PostgreSQL база; health/API/UI са
достъпни локално; root frontend build минава; няма cutover, импорт или remote
deployment.

**Validation:**

```powershell
docker compose -f next/compose.yaml config
docker compose -f next/compose.yaml up --build -d db
docker compose -f next/compose.yaml run --rm migrate
docker compose -f next/compose.yaml up --build -d api
Invoke-WebRequest http://127.0.0.1:8080/health/ready
Invoke-RestMethod http://127.0.0.1:8080/api/catalog
Invoke-WebRequest http://127.0.0.1:8080/
npm run build
```

След това направи read-only review на changed paths; не скривай или връщай
user-owned промени.

**Stop:** не изпълнявай `docker compose down -v`, Ubuntu deployment,
router/firewall промени или GitHub Pages cutover. Финалният отчет посочва
завършените стъпки, точните проверки, локалния URL и всеки blocker.