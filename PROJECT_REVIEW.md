# MediaDock: технически и security преглед

Дата на прегледа: 2026-08-24

## Обхват и метод

Прегледани са parser/scanner пътят, OMDb и Gemini интеграциите, Firestore repositories и rules, React клиентът, GitHub Actions workflow-ите, deployment документацията и наличните тестове.

Изпълнени проверки:

- `python -m unittest discover -s backend/tests -v`: 56 теста, 1 failure и 1 import error.
- Целеви parser probes за заглавия с `/`, скоби, латински локализирани имена и невалидни години.
- `npm audit --omit=dev --json`: 1 high severity транзитивна уязвимост (`nanoid` 3.3.17, GHSA-2v37-7h3g-55p8).

## Резюме

Основната архитектура е подходяща за малък личен проект: статичен React клиент в GitHub Pages, Firebase Auth/Firestore за данни и отделен Python scanner в GitHub Actions. Има добри решения като default-deny Firestore rules, deterministic IDs, repository interfaces, CI, ограничени workflow permissions, concurrency и timeout.

Преди проектът да се счита за сигурен обаче трябва да се отстранят два свързани проблема с висок приоритет:

1. GitHub Actions command injection през `force_days`.
2. Недоверени RSS URL-и от Firestore се отварят без server-side валидация от привилегирования scanner.

Съхраняването на GitHub PAT и OMDb ключ в браузъра допълнително увеличава ефекта при XSS или компрометирана dependency. Parser-ът работи за текущите fixtures, но е базиран на крехки евристики и има потвърдени грешки при реалистични заглавия.

## Находки по приоритет

### P0: Shell injection в scanner workflow

**Доказателство:** [`.github/workflows/scanner.yml`](.github/workflows/scanner.yml#L14-L19) приема `force_days` като свободен string, а [редове 76-77](.github/workflows/scanner.yml#L76-L77) интерполират `${{ github.event.inputs.force_days }}` директно в Bash source. Job-ът има достъп до `FIREBASE_SERVICE_ACCOUNT`, `OMDB_API_KEY` и `GEMINI_API_KEY`.

**Риск:** потребител или откраднат PAT с право да dispatch-ва workflow може да подаде shell метасимволи и да изпълни произволна команда в job-а. Това може да доведе до кражба на всички scanner secrets и пълен Admin достъп до Firestore.

**Корекция:** подай input-а през `env`, валидирай го с `^[0-9]+$` и извикай Python с Bash array, без конструиране на команда в string. Ограничи стойността до разумен диапазон, например `0..30`. За предпочитане използвай `choice` input с фиксирани стойности. Добави security regression тест или статична проверка за workflow expressions в `run:` блокове.

### P0: Недоверени RSS адреси достигат мрежата на GitHub runner-а

**Доказателство:** всеки allowlisted потребител може да пише целия `titles/settings_config` документ според [`firestore.rules`](firestore.rules#L20-L23). [`cli.py`](backend/src/movies_feed/cli.py#L63-L70) зарежда `rssFeeds` от този документ, след което [`scanner.py`](backend/src/movies_feed/scanner.py#L291) подава URL/стойността директно на `feedparser.parse`.

Frontend `type="url"` не е security boundary; документът може да бъде записан директно чрез Firebase SDK/REST. `feedparser.parse` приема URL, локален път или сурово съдържание.

**Риск:** SSRF към вътрешни адреси, опити за четене на локален файл, неочаквани протоколи, прекомерно големи отговори и блокиране на job-а. Комбинирано с parse logs и външните AI/OMDb заявки това разширява възможностите за изтичане или злоупотреба с ресурси.

**Корекция:** въведи server-side `validate_feed_url()` преди fetch: само `https`, точен allowlist на host-ове (например `feed.rutracker.cc`), забрана на credentials/redirect към друг host, DNS/IP проверка срещу loopback/private/link-local ranges, timeout, максимален размер и максимален брой entries. Изтегляй чрез контролиран HTTP client, после подавай bytes към parser-а. Firestore rules трябва също да валидират формата и допустимите полета, но това е втори слой, не заместител на backend проверката.

### P1: GitHub PAT и API ключове се пазят и могат да се build-нат в клиента

**Доказателство:** [`SettingsView.tsx`](src/components/SettingsView.tsx#L47-L50) чете ключове от `localStorage` или `VITE_*`, а [редове 74-77](src/components/SettingsView.tsx#L74-L77) записват OMDb ключа и GitHub PAT в `localStorage`. [`TriggerScannerModal.tsx`](src/components/TriggerScannerModal.tsx#L76-L82) прави същото. [`vite.config.ts`](vite.config.ts#L9) излага и `OMDB_API_KEY` като клиентски env prefix.

Текстът в UI, че `localStorage` е „сигурно“, е подвеждащ. Данните са достъпни за всеки JavaScript, изпълнен в origin-а; всяка `VITE_*` стойност е публична в bundle-а.

**Риск:** XSS, злонамерена dependency или достъп до браузър профила може да открадне PAT. Това е особено тежко заради P0.

**Корекция:** премахни PAT и scanner orchestration от статичния клиент. Използвай GitHub UI/CLI за ръчен dispatch или малък server-side endpoint/Cloud Function, който проверява Firebase ID token и извиква GitHub с краткоживееща GitHub App credential. Не позволявай `VITE_GITHUB_PAT`, `VITE_OMDB_API_KEY` или `OMDB_API_KEY` в client build. За ръчен OMDb refresh използвай server-side proxy с rate limiting.

### P1: AI audit-ът е fail-open и извършва разрушителни промени

**Доказателство:** [`scanner.py`](backend/src/movies_feed/scanner.py#L510) третира липсващо `is_valid_match` като `True` и маркира записа като AI validated. При допълнителната проверка липсващ/непълен AI резултат също допуска кандидата на [редове 559 и 757](backend/src/movies_feed/scanner.py#L559). При отрицателен резултат кодът изтрива title и occurrences на [редове 599-619](backend/src/movies_feed/scanner.py#L599-L619).

**Риск:** частичен или невалиден модел response може да валидира грешни данни; false negative може да изтрие коректни записи. Операциите не са атомарни и при прекъсване могат да останат orphan occurrences или непълна миграция.

**Корекция:** fail closed при липсващи полета; валидирай response schema и ID coverage; изисквай confidence threshold; записвай предложенията в review queue вместо директно изтриване; използвай soft-delete/quarantine и audit trail. За одобрена миграция използвай Firestore transaction/batch или възстановима state machine.

### P1: Ролята в allowlist не ограничава административните операции

**Доказателство:** deployment документацията предлага `role: reader`, но `isAllowlisted()` в [`firestore.rules`](firestore.rules#L7-L18) не проверява role. Всеки активен allowlisted потребител може да променя scanner settings и да чете/пише всички manual mappings на [ред 44](firestore.rules#L44).

**Риск:** компрометиран read-only акаунт може да пренасочи RSS входа, да промени филтрите или да подава произволни IMDb mappings. `createdBy` също се приема от клиента и не се обвързва с `request.auth`.

**Корекция:** въведи `isAdmin()`/custom claims или проверка на server-owned role; остави reader-ите само с read права. За `settings_config` и `manualMappings` приложи `keys().hasOnly(...)`, type/length ограничения и `createdBy == request.auth.uid` или server timestamp според модела.

### P1: Parser-ът поврежда валидни заглавия

Потвърдени случаи:

| Вход | Текущ резултат | Проблем |
| --- | --- | --- |
| `Face/Off / ... (1997)` | `Face` | [`split("/")`](backend/src/movies_feed/rutracker_parser.py#L120) разделя slash в самото заглавие. |
| `Title (Director Cut)` | `Title` | [`extract_title_section`](backend/src/movies_feed/rutracker_parser.py#L114-L116) премахва всяка крайна скоба, не само metadata. |
| `Movie / Se7en [1995]` | `Movie` | Избира първия Latin-like кандидат вместо вероятното оригинално заглавие. |
| `Movie Series / ... (2024)` | series | [`looks_like_series`](backend/src/movies_feed/rutracker_parser.py#L163-L167) търси substring без word boundaries. |
| `123 / ... (2024)` | `123` | [`is_latin_candidate`](backend/src/movies_feed/rutracker_parser.py#L33-L40) приема само цифри за Latin title. |
| `Film / Film [3024]` | year `3024` | [`extract_year`](backend/src/movies_feed/rutracker_parser.py#L105-L111) няма допустим диапазон. |

`extract_title_section` отрязва всичко след първата `[` и `cleanup_title_part` използва общи regex евристики. Това прави parser-а зависим от един конкретен формат на feed-а.

**Корекция:** моделирай граматиката на познатите RuTracker формати на етапи: отделяне само на разпознати metadata блокове от края, защитено разделяне на локализирано/оригинално заглавие и отделни правила за movie/series markers. Валидирай годината в разумен диапазон. Връщай parse confidence/reason и не прави OMDb lookup при ниска увереност. Запази текущите fixtures и добави table-driven corpus от реални и adversarial случаи.

### P1: Fetch/parse pipeline няма ясни resource limits и не проверява feed грешки

**Доказателство:** [`scanner.py`](backend/src/movies_feed/scanner.py#L291) използва `feedparser.parse` директно, не проверява HTTP status, `bozo`, content type или redirect chain и материализира всички entries. Същият parser се изпълнява два пъти за всеки запис: веднъж при cache prefetch и веднъж при обработката.

**Риск:** мълчаливо частично парсване, дълги блокирания, memory/Firestore/API amplification от огромен feed и двойна CPU работа. Един `OmdbLimitReachedError` прекъсва само текущия feed, след което следващ feed отново опитва заявки.

**Корекция:** отдели `FeedFetcher` от `TitleParser`; наложи timeout/size/entry limits; провери status/bozo; parse-ни всеки entry веднъж и предай резултата към prefetch/process фазите. При глобален quota error прекрати OMDb фазата за целия run.

### P2: Всички нерешени записи се изпращат към AI като movie

**Доказателство:** [`scanner.py`](backend/src/movies_feed/scanner.py#L688-L690) задава `"feed_type": "movie"` при `reparse_unfound_entries`, независимо от оригиналния feed.

**Риск:** series entries получават грешен prior и могат да бъдат съпоставени или отхвърлени неправилно.

**Корекция:** пази `feed_type` в `ParseLog` или го възстановявай от стабилна feed конфигурация; не го извеждай от display name.

### P2: Dependency и supply-chain контролът е непълен

**Доказателство:** production audit откри `nanoid` 3.3.17 през `postcss`; поправка е налична. Python dependencies в [`backend/pyproject.toml`](backend/pyproject.toml) са само с долни граници и няма lock/hash файл. GitHub Actions са pin-нати към mutable major tags (`@v4`, `@v5`), а не към commit SHA.

**Риск:** известна DoS уязвимост в dependency graph-а и непресъздаваеми/по-слабо защитени CI builds. Практическата експлоатируемост на конкретния `nanoid` advisory изглежда ниска за текущия код, защото не се вижда директно използване на custom generators, но пакетът трябва да се обнови.

**Корекция:** обнови lockfile-а така, че `nanoid >= 3.3.18`; премести build-only packages в `devDependencies`; добави Dependabot/Renovate и audit job. За Python използвай lock с hashes и pin-вай CI install-а към него. Pin-вай Actions по SHA с коментар за версията.

### P2: Текущата тестова база не е зелена и parser coverage е тясно

**Резултат:** backend suite-ът изпълни 56 теста с 54 успешни, 1 failure и 1 error.

- [`test_ai_matcher.py`](backend/tests/test_ai_matcher.py#L140-L160) очаква retry след HTTP 429, но [`ai_matcher.py`](backend/src/movies_feed/ai_matcher.py#L125-L132) веднага изключва AI за run-а. Тест и имплементация описват различна политика.
- `test_firestore_repository` не се import-на в текущата среда поради липсващ `google.cloud.firestore`. CI инсталира package dependencies, но локалната canonical команда не гарантира bootstrap на средата.
- [`test_rutracker_parser.py`](backend/tests/test_rutracker_parser.py) покрива само два happy-path fixture feed-а и един content-type случай; липсват malformed, Unicode, limits и реалистични delimiter edge cases.

**Корекция:** реши и документирай 429 политиката, направи setup командата възпроизводима и добави parser regression corpus. Добави тестове за URL validation, oversized feeds, redirects, `bozo`, AI partial responses и неатомарни repair failures.

### P3: Документацията е частично разминаваща се с кода

- [`DEPLOYMENT.md`](DEPLOYMENT.md#L124-L127) изисква browser network/bundle да не излага OMDb credential, но UI умишлено поддържа client OMDb key.
- [`README.md`](README.md#L24-L37) посочва root `config.json`, докато CLI default-ът е `legacy/config.json`.
- Архитектурните docs посочват prompt templates под `backend/src/movies_feed/prompts/`, но текущите Gemini prompts са inline в [`ai_matcher.py`](backend/src/movies_feed/ai_matcher.py).

**Корекция:** след security решенията актуализирай документацията спрямо един каноничен deployment модел.

## Архитектурна оценка

### Добри решения

- Ясно разделение между domain models, repository interfaces и Firestore adapters.
- Deterministic title/occurrence/cache IDs подпомагат idempotent runs.
- Firestore rules са default-deny и catalog writes от browser са забранени.
- GitHub workflows използват `contents: read`, concurrency guard и scanner timeout.
- Frontend като статичен GitHub Pages artifact е подходящ за read-oriented персонален каталог.
- Има отделни CI jobs за backend, frontend и Firestore rules.

### Препоръчана целева структура

1. **Static frontend:** Firebase Auth + read-only catalog/user preferences; без дългоживеещи third-party secrets.
2. **Administrative control plane:** GitHub UI/CLI или малък authenticated server endpoint; само admin role може да променя feeds/mappings и да стартира scan.
3. **Scanner:** `FeedFetcher -> FeedValidator -> TitleParser -> MetadataMatcher -> Persistence`, с typed резултати и ясни лимити.
4. **AI repair:** proposal/review queue, не директно разрушително действие.
5. **Configuration:** отделна `scannerSettings/config` колекция с schema/version, admin-only rules и backend validation, вместо специален документ в `titles`.

## Препоръчан ред за работа

1. Поправи workflow command injection и ротирай PAT/secrets при съмнение за предишно излагане.
2. Премахни PAT/API keys от клиента и `VITE_*` contract-а.
3. Добави backend RSS URL validation и fetch limits; ограничи settings writes до admin.
4. Направи AI repair fail-closed, възстановим и недеструктивен по подразбиране.
5. Рефакторирай parser-а със regression corpus и parse confidence.
6. Изчисти failing tests, dependency advisory и reproducible dependency locking.
7. Синхронизирай README/deployment/architecture документацията.

## Заключение

Deployment моделът GitHub Pages + Firebase + GitHub Actions е разумен за този мащаб, но browser-ът в момента има твърде голяма оперативна роля, а scanner-ът се доверява прекомерно на конфигурация и AI output. След затваряне на P0/P1 проблемите архитектурата може да остане сравнително проста, без да се налага миграция към постоянен application server.
