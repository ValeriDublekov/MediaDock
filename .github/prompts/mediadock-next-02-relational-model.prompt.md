---
name: "MediaDock Next 02 - Relational Model"
description: "Добавя началния PostgreSQL модел, EF Core migrations и интеграционни тестове само в next/."
argument-hint: "Незадължително уточнение за първия schema slice"
agent: "agent"
---

# Задача

След успешен bootstrap изпълни само persistence частта на MVP според
[migration plan](../../docs/DOTNET_REACT_MIGRATION_PLAN.md).

## Задължителни ограничения

- Текущият root app обслужва GitHub Pages и е read-only. Не променяй root
  `src/`, npm/Vite файлове, `backend/`, `legacy/`, Firebase/Firestore файлове или
  съществуващи GitHub workflows.
- Всички промени са под `next/`. Root Python кодът и документите са само
  behavior reference.
- Новата PostgreSQL база започва празна: не добавяй importer, backfill,
  dual-write или Firestore client.
- Не пренасяй Firestore document IDs, snapshots, indexes или repository
  abstraction механично.

## Обхват

- Прегледай scaffold и дефинирай само schema, нужни за MVP: titles, sources,
  occurrences и scan runs. Добави parse logs, metadata cache и конфигурация само
  ако ingestion slice-ът непосредствено ги изисква; не имплементирай proposals.
- Използвай EF Core/Npgsql. Сложи domain/use case типове в Application, а
  `DbContext`, mapping и migrations в Infrastructure.
- Използвай вътрешни UUID/identity ключове и relational constraints. Добави
  уникална source item identity за идемпотентни occurrences; не разчитай само на
  предварителна проверка в application code.
- Не използвай generic repository или mock `DbSet`. Добави PostgreSQL
  integration tests чрез Testcontainers за миграция, constraints и
  idempotency.
- Увери се, че EF migrations създават празна база; schema migration не трябва
  да внася стари catalog данни.

## Проверка и стоп

Пусни unit/build checks за засегнатите projects и PostgreSQL integration tests
за новия schema slice. Ако Docker/Testcontainers не са достъпни, отбележи
integration tests като непроверени, вместо да ги заменяш с SQLite или mocks.

Провери, че променените application файлове са само под `next/`. Не продължавай
към parser или RSS ingestion. Докладвай schema decisions, migration и тестови
резултати.