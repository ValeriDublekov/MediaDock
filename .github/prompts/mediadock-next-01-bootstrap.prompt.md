---
name: "MediaDock Next 01 - Bootstrap"
description: "Създава изолирания React, .NET и PostgreSQL skeleton под next/ без промени по текущия GitHub app."
argument-hint: "Допълнително ограничение за bootstrap етапа"
agent: "agent"
---

# Задача

Изпълни само Фаза 1 от [migration plan](../../docs/DOTNET_REACT_MIGRATION_PLAN.md):
създай самостоятелен scaffold за новия app под `next/`.

## Задължителни ограничения

- Текущият root app продължава да е production app за GitHub Pages. Считай
  `src/`, `package.json`, `package-lock.json`, `vite.config.ts`, `backend/`,
  `legacy/`, Firebase/Firestore конфигурацията и всички съществуващи
  `.github/workflows/*` за read-only.
- Всички runtime код, конфигурация, tests, Docker Compose и application docs за
  новата версия трябва да се създават само под `next/`.
- Не добавяй imports, project references или symlink-ове към стария app. Нужни
  fixtures могат да се копират по-късно в `next/`.
- Не мигрирай данни и не добавяй Firebase зависимости или secrets.
- Не променяй съществуващ GitHub Pages deployment и не прави cutover.

## Обхват

- Провери наличността на .NET 10 SDK, Node/npm и Docker. Ако prerequisite липсва,
  не инсталирай системен софтуер; докладвай какво трябва да бъде инсталирано.
- Създай `next/README.md`, собствен `.gitignore`, `next/web/` с React + TypeScript
  + Vite и `next/server/` със solution и отделни `Api`, `Application`,
  `Infrastructure`, `Worker`, unit test и integration test projects.
- Създай `next/compose.yaml` с PostgreSQL, health check и persistent volume.
  Database port-ът, ако е публикуван за local developer tooling, трябва да е
  вързан само към `127.0.0.1`; production web/API port-ът не се настройва тук.
- Добави `.env.example` без реални credentials. EF Core migrations и бизнес
  логика не са обхват на този етап.
- Документирай командите за local build/test/run в `next/README.md`.

## Проверка и стоп

Пусни само проверки за създадения scaffold: `dotnet build`, създадените test
projects, `npm run build` от `next/web/` и `docker compose config` за новия
Compose файл. Ако SDK/Docker липсва, не симулирай успешна проверка.

Преди да приключиш, провери променените пътища: всички application edits трябва
да са под `next/`. Не редактирай следващата фаза. В отговора посочи файловете,
проверките и всеки prerequisite/blocker.