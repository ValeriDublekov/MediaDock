---
name: "MediaDock Next 03 - Parsing and Match Policy"
description: "Портва parser и детерминистичните title matching правила към C# с unit tests, без Firestore зависимости."
argument-hint: "Feed fixture или parser edge case за приоритет"
agent: "agent"
---

# Задача

Имплементирай parser, normalization и детерминистичната match policy за първия
RSS вертикален slice. Използвай съществуващия Python код, документация и tests
само за очакваното поведение.

## Задължителни ограничения

- Root app-ът и GitHub Pages deployment-ът остават непроменени. Не редактирай
  root `src/`, npm/Vite конфигурация, Python/Firebase файлове или съществуващи
  `.github/workflows/*`.
- Кодът и новите tests са под `next/`. Няма runtime imports към Python или root
  React/domain код.
- Не пренасяй Firestore ID генерация, persistence код или API calls.
- Не добавяй Gemini, retry lifecycle или audit proposals в тази стъпка.

## Обхват

- Прочети само релевантните Python parser/match policy symbols, contract docs и
  tests/fixtures като read-only behavior reference.
- Ако fixture е нужна за C# tests, копирай минималната synthetic/public fixture
  в `next/server/` и запиши източника ѝ.
- Покрий title/year извличането, movie/series feed compatibility,
  movie-year tolerance, series broadcast-range правила, exclusions и
  malformed/ambiguous inputs с чисти unit tests.
- Използвай типизирани резултати за accepted/rejected/ambiguous decisions и
  стабилни reason codes. Не прави HTTP или database операции в pure policy.
- Не променяй вече приети parsing правила без отделен тест и ясно обяснение.

## Проверка и стоп

Пусни засегнатите xUnit tests и build на релевантните .NET projects. Провери,
че добавените fixtures и код са под `next/`. Не започвай RSS fetching или OMDb
интеграцията. В отговора изброи пренесените поведения и оставащите разлики.