# План за модернизация на MediaDock с .NET и React

Последна редакция: 2026-09-28

Този документ е работен план за постепенно изграждане на MediaDock като
self-hosted web app. Той описва целевата архитектура, ограниченията, фазите,
тестовете и решенията, които трябва да се запазят при бъдеща имплементация.

## 1. Цел и потвърдени решения

### Потвърдено

- Новото приложение ще използва React и .NET.
- Persistence слоят ще е релационна база данни; препоръчаният избор е PostgreSQL.
- Няма да се мигрират/import-ват съществуващи catalog данни от Firestore. Новата
  база започва празна. Старите данни не се изтриват автоматично и могат да
  останат само като историческа справка.
- Първоначалното използване ще е само в локалната мрежа.
- Google Auth не е изискване за първата версия.
- Продукцията ще се deploy-ва с Docker на личен Ubuntu сървър.
- Проектът трябва да остане малък и разбираем, но да има ясни граници и unit /
  integration tests.
- В бъдеще приложението може да обработва източници и възможности извън
  torrent RSS. Това не е причина още сега да се строи plugin framework.

### Изолация на текущата версия

Текущото приложение в root-а и GitHub Pages deployment-ът му трябва да
продължат да работят без промени, докато новото приложение не е отделно
deploy-нато и проверено на Ubuntu сървъра. Новата версия се изгражда паралелно
под `next/`; не се прави in-place rewrite или преждевременен cutover.

Всички текущи runtime файлове и съществуващи GitHub workflows са read-only.
Новият React app има собствен `package.json` и Vite конфигурация; новият .NET
код, Docker Compose и environment templates също живеят под `next/`. Старият
код може да се чете като behavior reference. Нужни компоненти и fixtures се
копират/адаптират съзнателно в `next/`, без runtime imports или project
references към старите директории.

### Архитектурна препоръка

Изградете **modular monolith** с feature folders и няколко ясни runtime
процеса. Използвайте vertical slices вътре в feature-ите, без отделен project
или assembly за всеки endpoint.

Не въвеждайте microservices, Kubernetes, Redis, message broker, CQRS framework,
MediatR или generic repository без конкретна нужда. EF Core `DbContext` е
достатъчен за PostgreSQL достъп; интерфейси са най-полезни за външните
интеграции и scheduler boundary.

## 2. Целева архитектура

```text
Browser в LAN
    |
    v
React SPA -- same-origin /api --> ASP.NET Core API ----> PostgreSQL
                                      ^                      ^
                                      |                      |
                                      +---- .NET Worker ------+
                                               |
                                      RSS / OMDb / Gemini
```

В Docker Compose целта е малък брой услуги:

- `api`: ASP.NET Core API; по избор сервира и компилираните React файлове, за да
  остане приложението на един origin и да не се въвежда CORS конфигурация.
- `worker`: отделен .NET Worker за RSS scan-овете и дългите background задачи.
- `postgres`: PostgreSQL с persistent Docker volume. Портът на базата не се
  публикува към LAN или Internet.
- Reverse proxy като Caddy/Nginx е по избор. Добавя се при реална нужда от
  routing/TLS, не като задължителен слой в първата локална версия.

Използвайте .NET 10 LTS, ASP.NET Core Web API, EF Core с Npgsql и React +
TypeScript + Vite. Новият цялостен app живее в `next/`; той има собствен
frontend, backend, tests и Compose конфигурация. Съществуващият root React app
не се променя и не се използва като runtime dependency.

### Препоръчана структура

```text
MediaDock/
  src/                         # текущ React app, остава непроменен
  package.json                 # текущ frontend, остава непроменен
  backend/                     # текущ Python app, остава reference
  .github/
    workflows/                 # текущите GitHub workflows, read-only
    prompts/                   # стъпкови Copilot prompt files
  next/                        # самостоятелното ново приложение
    README.md
    compose.yaml
    .env.example
    web/                       # собствен React/Vite app
      package.json
      src/
    server/
      MediaDock.sln
      src/
        MediaDock.Api/
        MediaDock.Application/
        MediaDock.Infrastructure/
        MediaDock.Worker/
      tests/
        MediaDock.UnitTests/
        MediaDock.IntegrationTests/
```

В `MediaDock.Application` организирайте кода по feature, например:

```text
Features/
  Catalog/
  Sources/
  Scans/
  ParseLogs/
  Metadata/
  Audit/                         # добавя се в по-късна фаза
```

`Domain` може първоначално да е namespace/folder в `MediaDock.Application`, а не
отделен project. Изнесете го само ако реалната сложност оправдае тази граница.
API и Worker трябва да споделят application use cases, но да имат отделни
composition roots. Infrastructure имплементира persistence и външните
интеграции.

## 3. Данни и persistence

Няма Firestore-to-PostgreSQL importer, backfill, dual-write или data bridge.
Новата база създава schema-та си чрез EF Core migrations. **Schema migrations
са нужни**, въпреки че catalog данните започват начисто; те описват версията на
структурата, а не прехвърлят старите данни.

Начален relational модел:

- `titles`: нормализирано заглавие, година, movie/series тип, IMDb ID и
  нормализирани метаданни.
- `sources`: RSS feed конфигурация, име, URL, очакван source type и enabled
  флаг. Feed е първата имплементация на source.
- `occurrences`: конкретна публикация от source, връзка към title, raw title,
  външен URL, source item key, quality/rip данни и времена на наблюдение.
- `genres`, `countries` и join таблици, ако заявките и филтрите изискват
  нормализирани many-to-many стойности.
- `scan_runs`: начало/край, статус, trigger, counters и sanitized errors.
- `parse_logs`: parsing резултат, retry състояние и ограничени diagnostics.
- `metadata_cache`: OMDb резултати, lookup identity и expiration.
- настройки за exclusions и rating thresholds. RSS feed настройките са в
  `sources`, а не във Firestore документ или frontend config.
- `audit_proposals`: добавя се по-късно, когато audit flow-ът се портне.

Предпочитайте UUID/identity за вътрешни primary keys и database unique
constraints за бизнес инвариантите. Не е необходимо да се запазват Firestore
SHA-256 document ID-тата. RSS повторните сканирания обаче трябва да са
идемпотентни: използвайте уникална идентичност от `source_id` + entry GUID, а
при липса на GUID - нормализиран външен URL. IMDb ID може да е уникален,
nullable external identifier за title.

Общият occurrence contract да не изисква torrent-only поле като `torrentUrl`.
Използвайте например `externalUrl` и source identity; `quality` и `ripType`
остават незадължителни полета. Това позволява добавяне на други източници без
универсален plugin system или предварително абстрахтиране на всичко.

Firestore RSS snapshot pointer-ът не трябва да се копира механично. PostgreSQL
може да заявява run entries с relational query и стабилен sort. Ако `Latest`
трябва да пази точния ред на последния успешен scan, добавете
`scan_run_entries` с run ID, feed ID, entry position и occurrence ID; не е
нужно отделно immutable-generation хранилище по подразбиране.

## 4. Локален достъп и сигурност

Първата версия няма Google Auth и приема, че app-ът е личен инструмент в
доверена LAN. Това е умишлено опростяване, **не** е еквивалент на
автентикация: всеки клиент с достъп до LAN адреса може да чете данните и да
извиква всяко изложено API действие, включително промени по settings или
стартиране на scan.

За LAN-only deployment:

- Не конфигурирайте router port forwarding и не публикувайте app-а към public
  Internet.
- Публикувайте само app/proxy порта, вързан към LAN адреса на сървъра; при
  Docker проверете и IPv6/firewall поведението. Docker published ports може да
  заобиколят някои UFW правила, затова реално проверете достъпа от WAN.
- PostgreSQL остава само в Docker internal network; не публикувайте `5432`.
- Предпочитайте same-origin frontend/API вместо отворен CORS.
- OMDb/Gemini ключовете и connection strings остават в server environment или
  Docker secrets, никога във Vite variables или browser bundle.
- Ако има други недоверени устройства в LAN, или ограничете/изключете
  административните write endpoints, или добавете минимална app-level защита
  преди да включите тези действия.
- Не излагайте неавтентикираната версия към Internet.

Google OAuth не е синоним на router port forwarding. OAuth redirect обикновено
се изпълнява през browser; конкретната конфигурация зависи от публичния origin,
HTTPS и provider ограниченията. Той просто не е нужен за началния личен LAN
workflow.

За по-късен remote access препоръчителната първа стъпка е private tailnet/VPN,
например Tailscale Serve с tailnet ACL/grants; не използвайте публичен
Funnel за private app. Това позволява отдалечен достъп без отваряне на router
портове. Network-level tailnet достъп не дава автоматично app-level роли. Ако
се появят множество потребители, роли или public access, добавете OIDC/Google
Auth и изрична authorization policy преди това.

## 5. Scheduled RSS scan

Scan-ът трябва да е отделен от HTTP request lifecycle в `MediaDock.Worker`.
API-то остава отзивчиво, докато Worker извлича RSS, вика metadata providers и
записва резултатите.

За един Ubuntu host и една ежедневна задача използвайте host-side `systemd`
timer, който стартира еднократен .NET Worker container. Това избягва scheduler
service и отделно job store. Задайте timezone `Europe/Sofia` и явна
catch-up/misfire политика чрез timer `Persistent`.

- Worker приема безопасен one-shot CLI режим; timer-ът е единственият daily
  schedule owner.
- PostgreSQL advisory lock пази срещу припокриване между timer и ръчен запуск.
- Всеки опит записва `scan_runs` статус и bounded, sanitized error summary.
- Ръчният запуск се прави през Docker Compose Worker command, не през дълъг
  HTTP request.

Не добавяйте Quartz.NET, отделна queue или cron container за началния single-host
MVP. Преоценете persistent in-app scheduler само ако се появят множество worker
инстанции, сложни графици или управление на задачи през UI.

## 6. План по фази

### Фаза 0: MVP граници

Потвърдете първия функционален обхват: RSS feeds, title parsing, OMDb
enrichment/cache, catalog с търсене/филтри/pagination, feed/settings управление,
scan history и parse logs. Оставете Gemini retry, existing-title audit,
proposal approval/application, Google Auth и допълнителни source типове за
следваща фаза.

Текущото приложение продължава да се deploy-ва и работи от root-а чрез
съществуващите GitHub workflows. Python кодът и документите са **behavior
reference**, не целева архитектура или persistence contract. Новият app няма
импорт на данни, dual-write или runtime зависимости към старата версия.

### Фаза 1: Foundation

- Създайте самостоятелен React/Vite app под `next/web/` и .NET 10 solution под
  `next/server/`.
- Добавете `next/compose.yaml` с PostgreSQL health check и persistent volume.
- Добавете EF Core/Npgsql, първа schema migration, liveness/readiness endpoints
  и конфигурация/secrets за local development.
- Не променяйте root `package.json`, Vite конфигурацията или съществуващите
  GitHub workflows. Ако е нужен отделен CI за новия app, добавете нов workflow
  с path filters, без редакция на текущите workflows.
- Потвърдете, че празна база може да се създаде от нулата само чрез migrations.

### Фаза 2: Първи end-to-end vertical slice

Имплементирайте backend vertical slice за един RSS feed: bounded fetch -> parser
-> match policy -> OMDb lookup/cache -> idempotent PostgreSQL write. Добавете
малък catalog API/UI slice едва след като ingestion use case и persistence
тестовете са стабилни.

Пренесете и тествайте съществуващите важни правила: movie/series feed
compatibility, movie year tolerance, series broadcast-range policy, exclusions,
title normalization и безопасна обработка на malformed feed entries.

RSS fetcher-ът трябва да запази защитите срещу SSRF: HTTPS/host policy, DNS/IP
проверки, redirect revalidation, timeout, content/body limits и entry limit.
Не допускайте произволни URL-и от browser да се fetch-ват от сървъра без
validation.

### Фаза 3: Catalog API и новият React app

- Изградете typed HTTP API adapter само в `next/web/`; не заменяйте и не
  променяйте Firestore adapter-а на текущото root приложение.
- Добавете paginated catalog query, title details, occurrences и search/filter
  параметри.
- Добавете feeds/settings CRUD и parse logs/scan history според MVP обхвата.
- Запазете loading/empty/error states; новата база започва празна до първия
  успешен scan.
- Преизползвайте UI/domain код само чрез съзнателно копиране и адаптация в
  `next/web/`. Не добавяйте import path, alias или package dependency към root
  `src/`.
- Новият frontend няма Firebase runtime dependency. Firebase остава част от
  текущото GitHub приложение, докато собственикът изрично не одобри cutover.

### Фаза 4: Production Worker и ежедневен scan

- Добавете one-shot Worker и Ubuntu systemd timer с timezone,
  catch-up/misfire поведение и PostgreSQL overlap защита.
- Включете manual Worker запуск за troubleshooting.
- Уверете се, че повторен scan не създава duplicate title/occurrence записи.
- Настройте structured logs, bounded diagnostics и статуси на scan-овете.

### Фаза 5: Deploy и backup

- Build-вайте versioned Docker images в CI и стартирайте app-а чрез Docker
  Compose на Ubuntu от `next/`, независимо от GitHub Pages deployment-а.
- Дръжте PostgreSQL в internal Docker network и пазете данните в volume.
- Изпълнявайте schema migrations като контролирана deploy стъпка, не като
  произволен side effect на всяка API инстанция.
- Добавете редовен `pg_dump` извън единствения Docker volume и периодично
  проверявайте restore-а. Volume сам по себе си не е backup.
- Използвайте pinned image tags, health checks и предвидим rollback към предишен
  image tag.
- Не променяйте hostname, GitHub Pages workflow, production Firebase setup или
  старото приложение като част от този deploy. Първо доказвате, че и двете
  версии работят независимо.

### Фаза 6: По-късни възможности

Добавяйте само след стабилен MVP: Gemini-assisted parse/reparse, retry
lifecycle, existing-title audit, review-only/repair proposals с stale detection,
remote tailnet access, OIDC/Google Auth при нужда от потребители/роли и нови
източници извън torrent RSS.

При proposal application PostgreSQL transaction-ът трябва атомично да
валидира текущите fingerprints, да прехвърли само посочените occurrences и да
запише финалния proposal status. Не пренасяйте Firestore lease/transaction
механиката механично, но запазете stale protection и all-or-nothing поведение.

## 7. Тестова стратегия

- **Unit tests (xUnit):** parsing, normalization, deterministic source key,
  match policy, exclusions, retry/status transitions и scheduler policy.
- **Integration tests:** EF Core queries, constraints, transactions,
  idempotency и proposal application срещу истински PostgreSQL чрез
  Testcontainers.
- **API tests:** `WebApplicationFactory` за HTTP status codes, validation,
  pagination и error responses.
- **External adapter tests:** RSS/OMDb/Gemini responses през mocked HTTP
  handlers или WireMock.Net; без live API calls в CI.
- **Frontend tests:** Vitest + React Testing Library за API adapter, filters,
  pagination и loading/empty/error states.
- **End-to-end smoke:** по-късно Playwright срещу Docker Compose, включително
  LAN routing и една контролирана scan операция.

Не mock-вайте EF Core `DbSet` за persistence integration tests. Unit тестовете
покриват pure business rules; integration тестовете проверяват реалното
поведение на PostgreSQL.

## 8. Критерии за първи usable release

- `docker compose up` стартира API, Worker и празна PostgreSQL база без
  Firebase credentials.
- EF Core migrations създават schema-та; няма legacy catalog import.
- App-ът е достъпен от LAN, но не и отвън; PostgreSQL не е изложен.
- Feed може да се конфигурира, scan да се изпълни и нови записи да се видят в
  React catalog.
- Повторен scan е идемпотентен; run status и грешките се виждат в app/logs.
- Daily job се изпълнява в зададената timezone и не може да се overlap-не.
- Съществуват unit и PostgreSQL integration tests за ключовите правила и
  persistence инварианти.
- OMDb/Gemini ключове и database credentials никога не попадат в frontend.
- Backup-ът може да се възстанови по документирана процедура.
- Съществуващият root app се build-ва и GitHub Pages deployment-ът му остава
  непроменен; новият app е достъпен отделно на сървъра.
- Не е извършван cutover, изтриване или изключване на текущия GitHub app.

## 9. Guardrails за бъдеща имплементация

- Движете се по една вертикална feature slice и валидирайте я с тесни tests.
- Не правете big-bang rewrite и не променяйте текущия root UI/runtime при
  port-ване.
- За implementation edits третирайте root `src/`, `package.json`, `vite.config`,
  `backend/`, `legacy/`, Firebase/Firestore конфигурацията и съществуващите
  `.github/workflows/*` като read-only. Всички нови runtime файлове са под
  `next/`.
- Ако задача изглежда изисква промяна на защитен root файл, спрете и обяснете
  защо; не правете промяната без изрично одобрение.
- Не добавяйте importer или dual-write: данните започват начисто.
- Не копирайте Firestore query/index/rules механики, когато SQL transaction,
  constraints и relational query решават същия проблем по-просто.
- Не премахвайте и не пренасочвайте старите Python/Firebase/GitHub Pages flow-ове.
  Cutover или архивиране е отделно решение след успешен deploy и приемателна
  проверка на новия app.
- Не правете публичен deployment без authentication/authorization и HTTPS.

## 10. Изходни документи в текущия проект

- [Текуща архитектура](ai/ARCHITECTURE.md) - имплементираните trust boundaries,
  scanner flows и бизнес политики.
- [Текущи Firestore договори](ai/DATA_CONTRACTS.md) - behavior reference за
  title, occurrence, cache, logs и proposal модели; това не е PostgreSQL schema.
- [Текущи тестове](ai/TESTING.md) - текущи команди и safety правила; командите
  ще се заменят/допълнят при създаване на .NET solution.
