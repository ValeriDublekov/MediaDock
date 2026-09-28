---
name: "MediaDock Next 08 - Docker Deployment"
description: "Подготвя самостоятелен LAN-only Docker Compose deployment и backup/restore процедура за Ubuntu."
argument-hint: "Ubuntu/Docker constraint или deployment target detail"
agent: "agent"
---

# Задача

Подготви production Compose configuration и операционни инструкции за новото
приложение под `next/`. Целта е отделен LAN deployment на Ubuntu, докато
съществуващият app продължава да работи в GitHub.

## Задължителни ограничения

- Не променяй root React/Python/Firebase files, GitHub Pages configuration или
  съществуващи `.github/workflows/*`.
- Не изключвай, не пренасочвай и не прави cutover от текущото GitHub Pages app.
- Не изпълнявай remote deployment, firewall/router промени или destructive
  команда без изрично потвърждение. Подготви файлове и runbook.
- Новата PostgreSQL база е празна; няма data import. Реални secrets не се
  записват във файлове или prompt output.

## Обхват

- Настрой `next/compose.yaml` за API/web, Worker и PostgreSQL с health checks,
  restart policies, named volume и internal Docker network.
- Публикувай само app порта и го bind-ни към изрично зададения LAN IP; default
  конфигурацията трябва да е fail-safe, ако bind address липсва. Не публикувай
  PostgreSQL порт. Опиши Docker/UFW/IPv6 проверките и липсата на router port
  forwarding.
- Добави `.env.example` и `.gitignore` под `next/`; secrets да се подадат
  извън git чрез server environment/Docker secrets. Няма OMDb/Gemini keys в
  React build variables.
- Документирай image build, migrations като контролирана стъпка, start/stop,
  health verification, log inspection, `pg_dump` backup и restore test.
- Ако добавяш CI, създай отделен workflow с точни `next/**` path filters;
  никога не редактирай съществуващ workflow.
- Не променяй DNS, domain, Firebase setup или GitHub Pages target. Новото
  приложение се проверява отделно на сървъра; cutover остава бъдещо изрично
  решение.

## Проверка и стоп

Пусни `docker compose config` и наличните production builds/tests. Направи
read-only проверка на git diff paths: съществуващите root runtime/workflow
файлове трябва да са непроменени. Ако текущият root build може да се изпълни
без secrets, използвай го като regression check; ако не, посочи ограничението.

Не се свързвай към Ubuntu сървъра и не стартирай production deployment без
изрично потвърждение. Завърши с deployment и rollback checklist; не прави
cutover и не изключвай GitHub Pages.