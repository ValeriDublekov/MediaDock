---
name: "MediaDock Next 06 - React Client"
description: "Изгражда самостоятелния React/Vite client под next/web и го свързва с новия ASP.NET Core API."
argument-hint: "Catalog view или interaction за приоритет"
agent: "agent"
---

# Задача

Изграждай новия frontend само под `next/web/` и го свържи с API от `next/server/`.

## Задължителни ограничения

- Съществуващият root React app се използва на GitHub Pages и е read-only.
  Никога не променяй root `src/`, `package.json`, lockfile, Vite config или
  Firebase adapters/auth.
- Не добавяй Vite aliases, workspace links, symlinks или imports към root
  директории. Ако преизползваш UI, копирай и адаптирай само избран код в
  `next/web/`.
- Новият app използва ASP.NET API; не добавяй Firebase SDK/Auth и не мигрирай
  данни.
- Не променяй текущ GitHub Pages deployment или workflows.

## Обхват

- Прегледай текущите екрани като read-only reference и избери MVP: catalog,
  search/filters/pagination, title details/occurrences, settings и scan history
  според наличните API endpoints.
- Добави typed HTTP adapter в новия frontend; компонентите да не съдържат
  директна fetch/persistence логика.
- Покрий loading, empty, error, retry и pagination states. Използвай API
  contract-ите от новия backend; не измисляй несъществуващи endpoints.
- Запази интерфейса фокусиран за личен media catalog; не добавяй marketing
  landing page или несвързана визуална система.
- Добави Vitest/React Testing Library tests за adapter, filters и основните
  UI states. Дръж package dependencies само в `next/web/package.json`.

## Проверка и стоп

Пусни `npm run build` и засегнатите frontend tests от `next/web/`. Потвърди,
че всички променени runtime файлове са под `next/` и root frontend остава
непроменен. Не продължавай към deployment.