---
name: "MediaDock Next 07 - Worker Scheduler"
description: "Добавя one-shot .NET Worker и Ubuntu systemd timer без Quartz или припокриващи се scan-ове."
argument-hint: "Schedule time/timezone или recovery requirement"
agent: "agent"
---

# Задача

Добави безопасен one-shot RSS Worker в `next/server/MediaDock.Worker/` и
systemd timer конфигурация за Ubuntu, свързани към вече тествания ingestion
use case.

## Задължителни ограничения

- Всички runtime edits са под `next/`. Текущият root GitHub app, Python scanner,
  Firebase конфигурацията и съществуващите workflows остават read-only.
- Не променяй стария GitHub Actions schedule и не изключвай стария workflow.
- Не добавяй Quartz.NET, Redis, message broker, отделен cron container или
  друга orchestration услуга.
- Не стартирай production scan или remote deployment от този prompt.

## Обхват

- Използвай Ubuntu systemd `.service` + `.timer` с timezone `Europe/Sofia` и
  явна catch-up/misfire политика. Това е единственият schedule owner.
- Worker поддържа еднократен запуск. PostgreSQL advisory lock пази срещу
  overlap между timer-а и ръчен Worker process.
- Всеки опит създава/финализира `scan_runs` със status, counters и
  bounded/sanitized errors. Повтарящ scan остава идемпотентен.
- Поддържай безопасен еднократен Worker CLI режим за локална проверка и
  troubleshooting. Не добавяй scan trigger endpoint към неавтентикирания API.
- Worker-ът да използва application use cases и Infrastructure adapters, а не
  да дублира matching/ingestion логика.

## Проверка и стоп

Покрий Worker concurrency lock и run status с PostgreSQL integration tests; не
прави live API заявки. Пусни build и релевантния integration test.

Потвърди, че старият GitHub schedule е непроменен. Не променяй deployment
workflow и не продължавай към server deployment.