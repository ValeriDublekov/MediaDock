# Backend Refactoring Review

Дата на прегледа: 2026-08-31

## Резюме

Обща оценка: **7/10**.

Рефакторингът е постигнал съществено подобрение спрямо рисковете, описани в roadmap-а. Налични са bounded RSS fetcher, централизирани match policy и OMDb resolver, fail-closed AI validation, versioned source identity, retry lifecycle, audit proposal model, CLI/workflow hardening и значително тестово покритие. Prompts 1-5 и 9 изглеждат в голяма степен изпълнени; 0A-0C и 6 са почти изпълнени.

Критичната незавършена част е връзката между audit proposals и прилагането им. Prompt 7 е частично изпълнен, Prompt 8 не е безопасен за production, а Prompt 10 не може да се счита за напълно завършен, докато този workflow не стане консистентен и recoverable. До отстраняване на P0 проблемите `apply-proposals` не трябва да се активира с production данни.

## Какво е направено успешно

- Workflow inputs и CLI exit semantics са значително по-безопасни; parse-only е отделен от външните API операции.
- Browser secret boundary е подобрен: scanner credentials не са част от нормалната frontend конфигурация.
- RSS мрежовият вход е изолиран в bounded fetcher с URL/IP/redirect/size/content проверки.
- Audit логиката вече е review-first и несигурни AI/OMDb резултати не изтриват директно catalog данни.
- Media/year решенията са централизирани и отчитат правилно season year спрямо series broadcast range.
- OMDb резултатите, quota/budget и cache identity са моделирани явно.
- Source context, v2 IDs и retry lifecycle пазят значително повече provenance.
- Gemini отговорите имат централен validator, confidence thresholds и fail-closed поведение.
- AuditProposal моделът има status transitions, evidence bounds и secret redaction.
- Parser-ът и operational metrics са видимо подобрени и са покрити с много focused тестове.

## P0: Блокиращи проблеми

### 1. Несъвместим metadata contract при proposal application

`scanner.py` създава `current_metadata` и `proposed_metadata` с вътрешни ключове `media_type` и `imdb_id`, докато `proposal_application.py` чете `mediaType` и `imdbId`. Освен това proposal-ът не записва IMDb ID от успешно разрешения OMDb candidate.

Резултатът е, че реално генерирано и одобрено предложение може да получи празен media type и липсващ IMDb ID, да изчисли грешен fallback title ID и да премести occurrence-и към непълен title. Наличните application тестове ръчно подават camelCase ключове и затова не улавят интеграционния дефект.

Засегнати файлове:

- `backend/src/movies_feed/scanner.py`
- `backend/src/movies_feed/proposal_application.py`
- `backend/tests/test_proposal_application.py`
- `docs/ai/DATA_CONTRACTS.md`

Препоръка: въведете typed `TitleMetadataSnapshot`/`ProposalTarget` или поне един serializer/deserializer, използван и при proposal creation, и при application. Добавете end-to-end тест: scanner създава proposal -> proposal се одобрява -> същият обект се прилага.

### 2. Липсва проверка за stale или непълен proposal

Преди mutation application service проверява основно дали source title и occurrence-ите съществуват. Не сравнява `current_metadata` със състоянието в момента на прилагане, не валидира текущата policy version и не изисква пълен target (`title`, валиден `mediaType`, canonical year semantics и evidence от resolver).

AI validator допуска mismatch без corrected target. Такова предложение може да бъде одобрено и приложено с празно заглавие/тип. Промяна на source title между audit и approval също не прави proposal-а stale.

Препоръка: application да валидира immutable source snapshot, policy version, occurrence membership и пълен canonical target след повторно resolver/policy потвърждение. При несъответствие proposal-ът трябва да се върне за review, без catalog mutation.

### 3. Прилагането не е атомарно и recovery моделът е непълен

Създаване/merge на target title, upsert/delete на occurrence-и, изтриване на source title и финалният proposal status са отделни repository операции. Crash между тях може да остави преместени данни и proposal в `applying`; stale lease recovery го маркира `failed`, но не доказва какво вече е записано.

Препоръка: Firestore implementation да използва transaction/batches с ясно chunking поведение, operation journal/checkpoint и idempotent resume. Source title да се изтрива едва след повторна проверка, че няма occurrence-и. Добавете fault-injection тестове след всяка write boundary.

### 4. Proposal ID се сблъсква между различни feed-ове

Audit cluster ключът е `(source_feed_id, raw_title)`, но `get_audit_proposal_id` получава само `[raw_title]`. Еднакъв raw title от два feed-а под един source title и policy version генерира еднакъв proposal ID; вторият upsert може да замени occurrence list/evidence на първия.

Препоръка: canonical cluster identity да включва поне `sourceFeedId` и normalized raw title, или сортираните occurrence IDs. Добавете regression тест с еднакъв raw title в два feed-а.

### 5. Audit rerun може да опита забранен status transition

При всеки mismatch scanner-ът създава deterministic proposal със status `pending`. Ако същото предложение вече е `approved`, `applying`, `applied` или `rejected`, repository transition validation не допуска връщане към `pending`. Това нарушава изискваната idempotency и може да прекъсне audit run.

Препоръка: при съществуващ proposal пазете terminal/operator status; обновявайте evidence само по ясно дефинирани правила. Нова policy version трябва да създава нов ID, вместо да reset-ва старото решение.

## P1: Важни корекции

### 6. Променен occurrence може да запази стара validation

`_stage_title_and_occurrence` инвалидира aggregate validation само при нов occurrence ID. При съществуващ ID `merge_occurrences` запазва старите validation полета, ако incoming стойностите са празни. Промяна на raw title/source context може така да остане маркирана като валидирана и title-ът да бъде пропуснат от audit.

Препоръка: дефинирайте fingerprint на полетата, влияещи на match решението. При промяна изчиствайте occurrence validation и `Title.ai_validated`, независимо че ID е същият.

### 7. `audit_days` не се прилага на ниво occurrence cluster

Филтърът използва aggregate timestamps на `Title`, преди да зареди occurrence-ите. Изискването е observation recency на конкретните occurrence clusters. Един нов occurrence може да включи стари clusters, а неточен title timestamp може да изключи допустим cluster.

Препоръка: заредете/странирайте candidate occurrence-и по `lastSeenAt` и после формирайте clusters. Добавете тест с нов и стар cluster под един title.

### 8. Има втори, по-слаб AI validation path

`ai_validator.py` изисква confidence за audit response, но `_is_valid_recheck_result` в `scanner.py` приема липсващ confidence. Текущият `AiMatcher` вероятно минава през строгия validator, но alternate/injected implementation може да заобиколи contract-а.

Препоръка: scanner-ът да приема само typed validated result и да премахне дублираната permissive проверка. Тестовите doubles също трябва да връщат пълния contract.

### 9. Firestore settings rules валидират само контейнерите

`validSettings` ограничава броя feed-ове и exclusion стойности, но не проверява nested feed schema и дължината/типа на всеки елемент. Admin може да запише невалидна или прекомерна nested конфигурация, която backend после да отхвърли.

Препоръка: ако Firestore Rules позволяват достатъчно ясна схема, валидирайте всеки поддържан feed slot/field; иначе преместете settings writes зад server-side control plane и забранете директните browser writes.

## P2: Maintenance и supply-chain подобрения

### 10. Action pinning е непоследователен

Част от GitHub Actions са pinned към commit SHA, но `actions/setup-node@v4`, `actions/setup-java@v4` и frontend `actions/checkout@v4` остават mutable tags. Static workflow test покрива само част от workflow-ите.

Препоръка: pin-нете всички third-party actions към reviewed SHA и разширете static теста към всички активни workflow файлове.

### 11. Документацията си противоречи

`docs/ai/IMPLEMENTATION_STATUS.md` едновременно:

- маркира Prompt 6-8 и 10 подетапи като изпълнени;
- твърди, че production launch още изисква AI/proposal/application stages;
- сочи несъществуващ Prompt 11;
- описва Prompt 6 като оставащ риск, въпреки че по-горе е отбелязан като завършен.

`docs/BACKEND_PARSING_PIPELINES.md` също съдържа частично остарели risk записи. Това прави roadmap-а ненадежден като operational source of truth.

Препоръка: заменете статуса с матрица `done / partial / blocked / deferred`, добавете критерии за production readiness и премахнете Prompt 11, освен ако действително не бъде дефиниран.

### 12. Dependency reproducibility може да се затегне

Backend CI използва lock файл, но `backend/pyproject.toml` продължава да задава широки lower bounds. Frontend `package.json` използва caret ranges, макар `package-lock.json` да фиксира CI инсталацията. Това е приемливо при дисциплинирано обновяване на lock файловете, но трябва да бъде документирано и автоматизирано с dependency review/update policy.

## Оценка по roadmap етапи

| Етап | Оценка | Коментар |
| --- | --- | --- |
| 0A | Почти завършен | Основното workflow/CLI hardening е налично; action pinning не е пълно. |
| 0B | Почти завършен | Secret boundary и роли са добри; nested settings validation е непълна. |
| 0C | Завършен | Bounded fetcher и focused тестове са налични. |
| 1 | Завършен | Audit е non-destructive и несигурните случаи са review-only. |
| 2 | Завършен | Shared media/year policy е въведен. |
| 3 | Завършен | Shared resolver, budget, typed outcomes и cache semantics са налични. |
| 4 | Завършен | Source context и v2 identity са реализирани; validation invalidation има остатъчен дефект. |
| 5 | В голяма степен завършен | Retry lifecycle и provenance са реализирани. |
| 6 | Почти завършен | Централният validator е добър; scanner пази дублиран по-слаб validator. |
| 7 | Частично завършен | Моделът/repository са налични, но ID/status/recency/invalidation семантиките имат дефекти. |
| 8 | Не е production-ready | Contract mismatch, stale checks и atomic recovery са блокиращи. |
| 9 | Завършен | Parser/fetch integration и диагностиката са подобрени. |
| 10 | Частично завършен | Metrics/operations са развити, но end-to-end proposal workflow остава ненадежден. |

## Препоръчан ред за работа

1. Деактивирайте production `apply-proposals`, докато P0 тестовете не са зелени.
2. Уеднаквете proposal metadata contract и добавете scanner-to-application end-to-end test.
3. Добавете stale/source/policy/target validation преди mutation.
4. Поправете proposal identity и status-preserving idempotent upsert.
5. Реализирайте transaction/checkpoint recovery и fault-injection тестове.
6. Поправете occurrence validation invalidation и cluster-level `audit_days`.
7. Премахнете дублирания AI validator и затегнете Firestore settings rules.
8. Актуализирайте implementation status едва след пълния CI и emulator suite.

## Валидация и ограничения

Прегледани са roadmap-ът, backend implementation, repository/model contracts, workflow-ите, Firestore rules и съответните тестове. Направена е статична проверка на критичните code paths.

Локалните executable проверки не можаха да бъдат изпълнени в тази среда:

- `python` е само Windows Store execution alias и няма инсталиран Python runtime;
- `npm` и `npx` не са налични в `PATH`;
- поради това backend unittest suite, frontend Vitest/typecheck/build и Firestore emulator tests не са стартирани локално.

Това не обезсилва описаните contract дефекти, които се виждат директно в producer/consumer кода, но означава, че текущият green CI статус трябва да бъде проверен отделно преди release.
