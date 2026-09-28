---
name: "MediaDock Next 04 - RSS Ingestion"
description: "Имплементира безопасно RSS fetching, OMDb enrichment/cache и идемпотентен PostgreSQL ingestion flow."
argument-hint: "Feed fixture или конкретна ingestion нужда"
agent: "agent"
---

# Задача

Изгради първия backend ingestion vertical slice в `next/server/`: RSS feed към
валидирани title/occurrence записи и `scan_runs` резултат.

## Задължителни ограничения

- Root GitHub app и всички съществуващи runtime/workflow файлове са read-only.
  Промените са само под `next/`.
- Няма Firestore, data import, dual-write, Python runtime dependency или live
  requests към production.
- Не добавяй Gemini, audit proposals, автоматични repairs или UI в тази стъпка.

## Обхват

- Използвай validated feed configuration; защити server-side fetching срещу
  SSRF с HTTPS/host policy, DNS/IP validation, redirect revalidation, timeout,
  content/body limits и разумен entry limit. Не fetch-вай произволен browser URL.
- Имплементирай RSS/Atom adapter с injected HTTP transport и тестове за timeout,
  malformed response, redirect и лимити; CI тестовете не правят live network
  заявки.
- Добави OMDb client чрез `IHttpClientFactory`, timeout/error handling и
  server-side API key. Cache-вай само валидни found/confirmed-not-found
  резултати с expiry; quota/transport/auth грешките да не стават cache hits.
- Оркестрирай parse -> match policy -> metadata resolution -> PostgreSQL writes.
  Запазвай occurrence idempotency чрез database unique constraint и коректно
  маркирай succeeded/partial/failed scan run.
- Обработи отделен malformed item без да губиш останалите валидни entries; не
  представяй непълен feed като успешен пълен scan.
- Запази bounded/sanitized diagnostics; никога не записвай API keys или пълни
  secret-bearing URLs в parse logs.

## Проверка и стоп

Пусни ingestion unit tests, adapter tests с mock transport и PostgreSQL
integration tests за idempotency/transaction behavior. Не извиквай истински
RSS/OMDb/Gemini услуги.

Провери, че всички app edits са под `next/`. Не създавай daily scheduler и не
редактирай текущия scanner. Докладвай external contracts, security проверки и
тестови резултати.