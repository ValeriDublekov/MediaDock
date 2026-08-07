# Media Hub Dashboard & Scanner

> **Migration status:** The current JSON/HTML implementation remains operational
> while a Firestore + React migration is prepared. Start with
> [AI_STUDIO_MIGRATION_GUIDE.md](AI_STUDIO_MIGRATION_GUIDE.md) and check
> [docs/ai/IMPLEMENTATION_STATUS.md](docs/ai/IMPLEMENTATION_STATUS.md) before
> changing the repository structure.

## Migration Documentation

- [LOCAL_DEVELOPMENT.md](LOCAL_DEVELOPMENT.md) - current and staged local setup,
   execution, testing, and emulator workflow.
- [DEPLOYMENT.md](DEPLOYMENT.md) - target Firebase, GitHub Actions, and GitHub Pages
   deployment runbook.
- [docs/ai/PROJECT_CONTEXT.md](docs/ai/PROJECT_CONTEXT.md) - compact entry context
   for AI implementation sessions.
- [docs/ai/ARCHITECTURE.md](docs/ai/ARCHITECTURE.md) - target components, trust
   boundaries, and dependency rules.
- [docs/ai/DATA_CONTRACTS.md](docs/ai/DATA_CONTRACTS.md) - Firestore schema,
   queries, IDs, ownership, and write boundaries.
- [docs/ai/TESTING.md](docs/ai/TESTING.md) - canonical verified test commands.

## 1. Общ Преглед (Overview)
Системата е личен медиен агрегатор, който автоматично сканира торент RSS фийдове, обогатява ги с метаданни от IMDb (чрез OMDb API) и генерира интерактивен, модерен HTML Dashboard. Системата поддържа 5-дневна история и позволява динамично филтриране в реално време без презареждане на страницата.

## 2. Организация на Файловете (File Structure)
```
MoviesFeed/
├── data/                       # Локални данни (игнорирани от Git)
│   ├── data_storage.json       # База данни с филми
│   ├── scan_history.json       # История на сканиранията
│   ├── api_cache.json          # Кеш на API заявките
│   └── scanner.log            # Лог файл (само грешки)
├── output/                    # Генерирани отчети (игнорирани от Git)
│   ├── reports/              # Архив на стари отчети
│   │   └── report_YYYY-MM-DD_HH-MM.html
│   └── daily_report.html     # Главен дашборд
├── templates/                 # HTML темплейти
│   └── dashboard_template.html
├── scripts/                   # PowerShell скриптове
│   └── run_scanner.ps1
├── movie_scanner.py           # Основен сканиращ скрипт
├── report_gen.py             # HTML генератор
├── config.json               # Конфигурация
├── README.md                 # Документация
├── CHANGELOG.md              # История на промените
└── QUICKSTART.md             # Бърз старт
```

### Основни файлове:
- `movie_scanner.py`: Основен Python скрипт. Изпълнява сканиране, API заявки и управление на базата данни.
- `report_gen.py`: Python модул за трансформиране на JSON данните в HTML. Използва темплейтна система.
- `templates/dashboard_template.html`: HTML/CSS/JS скелет на дашборда с плейсхолдъри ({{PLACEHOLDER}}).
- `config.json`: Външни настройки (API ключове, RSS линкове, филтри по подразбиране).
- `data/data_storage.json`: Локална база данни, съхраняваща одобреното съдържание за последните X дни.
- `data/scan_history.json`: Списък с вече сканирани торент ID-та за избягване на дублирани API заявки.
- `data/api_cache.json`: Кеш на OMDb API заявките за намаляване на external requests.
- `scripts/run_scanner.ps1`: PowerShell скрипт за автоматизирано стартиране и отваряне на резултата.

## 3. Функционална Спецификация (Technical Spec)

### А. Сканиране и Парсване (Back-end)
1. **RSS Агрегация**: Скриптът чете Atom/RSS фийдове.
2. **Title Parsing**: Използва Regex за извличане на:
   - Оригинално (английско) заглавие.
   - Година на издаване.
   - Видео качество (напр. 1080p, 4K) и тип рип (BDRip, WEB-DL).
3. **API Енричмънт**: Прави заявки към OMDb API за извличане на `imdbRating`, `imdbVotes`, `Genre`, `Plot`, `Awards`, `Country`, `Runtime`, `BoxOffice` и постери.
4. **Твърда Филтрация**: Преди запис в базата, скриптът автоматично отхвърля заглавия, които:
   - Са от определени държави (напр. Индия, Турция) - конфигурируемо.
   - Са от определени жанрове (напр. Horror) - конфигурируемо.

### Б. База Данни и Ретенция
- Данните се групират по дата на сканиране.
- Автоматично се изтриват записи по-стари от зададения в `days_to_keep` параметър.
- Поддържа се режим `--html`, който само прегенерира визуалния файл от съществуващата база данни без нови мрежови заявки.
- Поддържа се режим `--parse-only`, който сваля/чете RSS-а, парсва само заглавията и годините и показва проблемните записи без OMDb заявки.

### В. Интерактивен Dashboard (Front-end)
1. **Динамично Филтриране (JS)**:
   - **Рейтинг Слайдери**: Отделни плъзгачи за Филми и Сериали. Скриват/показват картичките моментално.
   - **Votes Filter**: Слайдер за минимален брой гласове в IMDb.
   - **Мулти-селекция на Типове**: Бутони за включване/изключване на Movies, TV Series, Documentaries, Short Movies.
   - **Държави**: Динамично генерирани бутони за включване/изключване на продукции по държава.
2. **UI/UX Дизайн**:
   - **Dark Mode**: Тъмен интерфейс със сини и златни акценти.
   - **Hover Overlay**: При посочване на постер се показва резюме, детайлни рейтинги (IMDb, Rotten Tomatoes, Metacritic), награди и технически данни.
   - **Search**: Търсене в реално време по заглавие, режисьор или жанр.
3. **Конфигурационен Панел**: Модален прозорец, показващ текущите системни настройки и активните RSS източници.

## 4. Конфигурация (config.json)
Файлът трябва да съдържа:
- `omdb_api_key`: Валиден ключ.
- `days_to_keep`: Число (дни).
- `filters`: Списък с изключени държави, жанрове и **стойности по подразбиране за плъзгачите в Dashboard-а**.
- `video_settings`: Списъци с тагове за качество и рип.
- `cache`: Настройки за API кеширане (`enabled`, `cache_days`).
- `archive_reports`: Включване/изключване на архивирането на стари репорти.
