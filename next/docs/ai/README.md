# MediaDock Next AI Documentation

Start here for work under `next/`. These guides cover only the new app; use the [local operations runbook](../../README.md) for setup, Compose, and operational commands.

## Project orientation

[Project context](PROJECT_CONTEXT.md) summarizes the runtime boundary, stack, main directories, and local entrypoint.

## Choose by task

| Task | Read |
| --- | --- |
| Frontend | [Architecture](ARCHITECTURE.md) for the web/API boundary and request flow; [Testing](TESTING.md) for frontend tests and commands. |
| API | [API contracts](API_CONTRACTS.md) for routes, DTOs, validation, and errors; [Architecture](ARCHITECTURE.md) for cross-layer flows. |
| Persistence | [Data contracts](DATA_CONTRACTS.md) for entities, schema, and invariants; [Architecture](ARCHITECTURE.md) for persistence flows. |
| Worker | [Architecture](ARCHITECTURE.md) for worker startup and ingestion flow; [Implementation status](IMPLEMENTATION_STATUS.md) for shipped capabilities and limits. |
| Tests | [Testing](TESTING.md) for scoped commands, test categories, and required dependencies. |
| Operations | [Security and operations](SECURITY_AND_OPERATIONS.md) for runtime boundaries and operational constraints; the [local runbook](../../README.md) for executable setup and maintenance instructions. |

## Planned work

- [Oscar catalog plan](OSCAR_CATALOG_PLAN.md)
- [Database model review](DATABASE_MODEL_REVIEW.md)
