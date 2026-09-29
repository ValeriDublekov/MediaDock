# Implementation Status

This matrix describes the code and configuration in the standalone `next/` app only. The root app, Python backend, Firebase/Firestore, Google Auth, and GitHub Pages app are separate runtimes. `Implemented` means the capability exists in this repository; it does not claim a production deployment or a passing test run. `Not implemented` and `MVP limitation` are not delivery commitments.

## MVP Matrix

| Area | Status | Shipped scope and boundary |
| --- | --- | --- |
| Web app and local runtime | Implemented | The React client is bundled into and served by the production API image; Compose provides the API and PostgreSQL, with the host port bound to loopback ([Compose](../../compose.yaml), [local runbook](../../README.md)). |
| Catalog | Implemented | Search, supported filters, pagination, title details, and occurrence history are available in the UI and API ([catalog view](../../web/src/features/catalog/CatalogView.tsx), [API contracts](API_CONTRACTS.md)). |
| Sources and matching settings | Implemented | The UI can create/edit and enable or disable feed sources and update matching thresholds/exclusions. Feed URLs are restricted to the supported HTTPS host; these writes are unauthenticated ([sources view](../../web/src/features/sources/SourceSettingsView.tsx), [API contracts](API_CONTRACTS.md)). |
| RSS ingestion and metadata | Implemented, opt-in | A one-shot Worker ingests configured feeds, applies the current parser/matching flow, resolves metadata through OMDb with a PostgreSQL cache, and persists accepted titles, occurrences, parse logs, and scan summaries ([Worker](../../server/src/MediaDock.Worker/Program.cs), [ingestion flow](../../server/src/MediaDock.Application/Ingestion/RssIngestionService.cs), [data contracts](DATA_CONTRACTS.md)). The feed host and parser scope are not a general-purpose RSS provider interface. |
| Operations history and health | Implemented | The UI reads paginated scan-run and parse-log history. The API exposes process-liveness and database-connectivity endpoints; the history routes list results and do not start scans ([history view](../../web/src/features/history/HistoryView.tsx), [history endpoints](../../server/src/MediaDock.Api/Operations/OperationalHistoryEndpoints.cs), [API contracts](API_CONTRACTS.md)). |
| Persistence and schema | Implemented | PostgreSQL persistence, metadata caching, and checked-in EF Core migrations are present. Migrations run only through the explicit one-shot migration service, not normal API startup ([data contracts](DATA_CONTRACTS.md), [API startup](../../server/src/MediaDock.Api/Program.cs)). |
| Host scheduling and backup procedure | Implemented | A single-host systemd timer and service are provided for scheduled Worker runs. The local runbook documents operator-run SQL backup and restore; detailed commands remain in the [local runbook](../../README.md) and [systemd runbook](../../deploy/systemd/README.md). |

## MVP Limitations

| Area | Status | Limitation |
| --- | --- | --- |
| Authentication and authorization | Not implemented | All API routes, including source/settings writes, are unauthenticated. Keep the app on loopback; the repository does not provide a safe internet-facing deployment. See [security and operations](SECURITY_AND_OPERATIONS.md). |
| Feed/provider coverage | MVP limitation | The transport allows only `feed.rutracker.cc`, the ingestion parser is source-specific, and metadata lookup uses OMDb. Arbitrary feed hosts and additional metadata providers are not supported. |
| Scan control | Not implemented in the API/UI | There is no scan-start endpoint or UI action. Scans run as an explicitly invoked one-shot Worker or through the systemd timer; the API exposes history only. |
| Deployment and recovery | MVP limitation | The supplied deployment is local Compose or a single host with systemd, not a multi-user or internet-facing service. Backup/restore is operator initiated; no automated backup retention schedule or alerting service is included. |

No item in the limitations table is implicitly planned. A capability should be labelled `Planned` only when an approved plan explicitly commits to it; until implemented and verified, it is not part of the shipped MVP.