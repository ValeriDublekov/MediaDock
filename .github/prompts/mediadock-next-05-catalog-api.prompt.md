---
name: "MediaDock Next 05 - Catalog API"
description: "Добавя валидиран ASP.NET Core API за catalog, sources/settings и scan history с integration tests."
argument-hint: "Endpoint или catalog workflow за приоритет"
agent: "agent"
---

# Задача

Добави HTTP API slice в `next/server/`, който позволява на новия React app да
чете catalog-а и управлява източниците/настройките от PostgreSQL.

## Задължителни ограничения

- Текущият GitHub Pages app е активен и read-only. Не редактирай root frontend,
  Python/Firebase код, `package.json`, конфигурация или съществуващи workflows.
- Всички implementation changes остават под `next/`; няма Firebase/Auth SDK,
  importer или cross-folder project reference.
- Google Auth е извън MVP. Не твърди, че LAN достъпът е application
  authentication; не добавяй public exposure.

## Обхват

- Следвай `dotnet-webapi` conventions: HTTP semantics, request validation,
  OpenAPI metadata, consistent `ProblemDetails` и global error handling.
- Добави само MVP endpoints, например catalog page/details/occurrences,
  source/settings read-write и scan-run history. Ползвай pagination с
  детерминистичен ordering и EF Core async queries.
- Валидацията за source URL трябва да съответства на bounded fetch policy; не
  позволявай endpoint-ът да превърне app-а в произволен SSRF proxy.
- Не стартирай дълъг RSS scan директно в HTTP request. Manual scan trigger
  остава Worker CLI за MVP, освен ако вече съществува безопасна persisted
  trigger граница.
- Запазвай API DTO-ите отделни от persistence entities; не въвеждай
  MediatR/generic repository само за endpoints.
- Използвай same-origin deployment model; CORS не се отваря широко.

## Проверка и стоп

Добави API tests с `WebApplicationFactory` за status codes, validation,
pagination и error responses, плюс integration tests срещу PostgreSQL там,
където query/constraint поведението е важно. Пусни build и засегнатите tests.

Преди да приключиш, потвърди, че не си променил root app или съществуващ
workflow. Не започвай React client-а в този prompt.