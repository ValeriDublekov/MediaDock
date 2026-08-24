import React, { useState, useEffect, useMemo, useCallback } from 'react';
import { ParseLog, ParseLogRepository } from '../domain/parseLog';
import { ManualMapping, ManualMappingRepository } from '../domain/manualMapping';
import { firestoreParseLogAdapter } from '../adapters/firestoreParseLogAdapter';
import { firestoreManualMappingAdapter } from '../adapters/firestoreManualMappingAdapter';
import {
  FileText,
  Search,
  RefreshCw,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Filter,
  Film,
  Loader2,
  Clock,
  Globe,
  Tag,
  Link,
  Plus,
  Trash2,
  Check,
  ChevronDown,
  ChevronUp,
  Database,
  Layers,
  Copy,
  ExternalLink,
  ShieldAlert,
  Info,
} from 'lucide-react';

interface ParseLogViewProps {
  repository?: ParseLogRepository;
  manualMappingRepository?: ManualMappingRepository;
  currentUserUid?: string;
}

type FilterTab = 'all' | 'unfound' | 'successful' | 'omdb_found' | 'ignored' | 'failed_parse';

export const ParseLogView: React.FC<ParseLogViewProps> = ({
  repository = firestoreParseLogAdapter,
  manualMappingRepository = firestoreManualMappingAdapter,
  currentUserUid,
}) => {
  const [logs, setLogs] = useState<ParseLog[]>([]);
  const [manualMappings, setManualMappings] = useState<ManualMapping[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const [searchTerm, setSearchTerm] = useState<string>('');
  const [activeFilter, setActiveFilter] = useState<FilterTab>('all');
  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);
  const [copiedLogId, setCopiedLogId] = useState<string | null>(null);

  // Local state for IMDb input values keyed by log ID
  const [imdbInputs, setImdbInputs] = useState<Record<string, string>>({});
  const [savingMappingId, setSavingMappingId] = useState<string | null>(null);
  const [mappingError, setMappingError] = useState<string | null>(null);
  const [mappingSuccess, setMappingSuccess] = useState<string | null>(null);

  const fetchLogsAndMappings = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [logsData, mappingsData] = await Promise.all([
        repository.getRecentParseLogs(150),
        manualMappingRepository.getManualMappings().catch(() => []),
      ]);
      setLogs(logsData);
      setManualMappings(mappingsData);
    } catch (err) {
      setError(err instanceof Error ? err : new Error('Failed to fetch parse logs'));
    } finally {
      setIsLoading(false);
    }
  }, [repository, manualMappingRepository]);

  useEffect(() => {
    fetchLogsAndMappings();
  }, [fetchLogsAndMappings]);

  // Map of log ID -> ManualMapping if mapping already exists
  const activeMappingsMap = useMemo(() => {
    const map = new Map<string, ManualMapping>();
    manualMappings.forEach((m) => {
      map.set(m.id, m);
    });
    return map;
  }, [manualMappings]);

  const metrics = useMemo(() => {
    const total = logs.length;
    const parsedSuccess = logs.filter((l) => l.parsedSuccessfully).length;
    const omdbFound = logs.filter((l) => l.omdbStatus === 'found').length;
    const unfoundCount = logs.filter(
      (l) => l.omdbStatus === 'not_found' || l.ignoreReason === 'omdb_not_found'
    ).length;
    const parseErrorsCount = logs.filter(
      (l) => !l.parsedSuccessfully || l.ignoreReason === 'parse_error' || l.ignoreReason === 'entry_error' || !!l.errorMessage
    ).length;
    const ignoredCount = logs.filter((l) => l.ignored).length;
    return { total, parsedSuccess, omdbFound, unfoundCount, parseErrorsCount, ignoredCount };
  }, [logs]);

  const unfoundLogs = useMemo(() => {
    let result = logs.filter(
      (l) => l.omdbStatus === 'not_found' || l.ignoreReason === 'omdb_not_found'
    );
    if (searchTerm) {
      const lowerSearch = searchTerm.toLowerCase();
      result = result.filter(
        (log) =>
          log.rawTitle.toLowerCase().includes(lowerSearch) ||
          (log.parsedTitle && log.parsedTitle.toLowerCase().includes(lowerSearch)) ||
          (log.feedName && log.feedName.toLowerCase().includes(lowerSearch)) ||
          (log.errorMessage && log.errorMessage.toLowerCase().includes(lowerSearch))
      );
    }
    return result;
  }, [logs, searchTerm]);

  const handleSaveImdbId = async (log: ParseLog) => {
    const rawInput = imdbInputs[log.id] || '';
    const cleanedId = rawInput.trim();
    if (!cleanedId) {
      setMappingError('Моля, въведете валиден IMDb ID (напр. tt0133093)');
      return;
    }
    // Basic regex check for tt1234567 format
    if (!/^tt\d{6,10}$/i.test(cleanedId)) {
      setMappingError('Форматът трябва да бъде "tt" последван от цифри (напр. tt0133093)');
      return;
    }

    setSavingMappingId(log.id);
    setMappingError(null);
    setMappingSuccess(null);

    try {
      await manualMappingRepository.saveManualMapping({
        id: log.id,
        rawTitle: log.rawTitle,
        imdbId: cleanedId,
        parsedTitle: log.parsedTitle,
        parsedYear: log.parsedYear,
        createdBy: currentUserUid || null,
      });

      setMappingSuccess(`Запазен IMDb ID ${cleanedId} за "${log.parsedTitle || log.rawTitle}". Очаква следващо сканиране.`);
      await fetchLogsAndMappings();
    } catch (err) {
      setMappingError(err instanceof Error ? err.message : 'Грешка при запис на IMDb ID');
    } finally {
      setSavingMappingId(null);
    }
  };

  const handleDeleteMapping = async (mappingId: string) => {
    setSavingMappingId(mappingId);
    setMappingError(null);
    setMappingSuccess(null);
    try {
      await manualMappingRepository.deleteManualMapping(mappingId);
      setMappingSuccess('Мапингът бе изтрит успешно.');
      await fetchLogsAndMappings();
    } catch (err) {
      setMappingError(err instanceof Error ? err.message : 'Грешка при изтриване на мапинга');
    } finally {
      setSavingMappingId(null);
    }
  };

  const toggleExpand = (logId: string) => {
    setExpandedLogId((prev) => (prev === logId ? null : logId));
  };

  const copyTraceJson = (log: ParseLog) => {
    const fullTrace = {
      id: log.id,
      rawTitle: log.rawTitle,
      feedName: log.feedName,
      processedAt: log.processedAt.toISOString(),
      parsedSuccessfully: log.parsedSuccessfully,
      parsedTitle: log.parsedTitle,
      parsedYear: log.parsedYear,
      omdbStatus: log.omdbStatus,
      ignored: log.ignored,
      ignoreReason: log.ignoreReason,
      errorMessage: log.errorMessage,
      traceDetails: log.traceDetails || null,
    };
    navigator.clipboard.writeText(JSON.stringify(fullTrace, null, 2));
    setCopiedLogId(log.id);
    setTimeout(() => setCopiedLogId(null), 2000);
  };

  const filteredLogs = useMemo(() => {
    return logs.filter((log) => {
      // Filter tab
      if (activeFilter === 'unfound') {
        if (log.omdbStatus !== 'not_found' && log.ignoreReason !== 'omdb_not_found') {
          return false;
        }
      }
      if (activeFilter === 'successful' && (log.ignored || !log.parsedSuccessfully)) {
        return false;
      }
      if (activeFilter === 'omdb_found' && log.omdbStatus !== 'found') {
        return false;
      }
      if (activeFilter === 'ignored' && !log.ignored) {
        return false;
      }
      if (activeFilter === 'failed_parse') {
        const isFailed = !log.parsedSuccessfully || log.ignoreReason === 'parse_error' || log.ignoreReason === 'entry_error' || !!log.errorMessage;
        if (!isFailed) return false;
      }

      // Search term
      if (searchTerm.trim()) {
        const query = searchTerm.toLowerCase();
        const matchesRaw = log.rawTitle.toLowerCase().includes(query);
        const matchesParsed = log.parsedTitle ? log.parsedTitle.toLowerCase().includes(query) : false;
        const matchesFeed = log.feedName.toLowerCase().includes(query);
        const matchesReason = log.ignoreReason ? log.ignoreReason.toLowerCase().includes(query) : false;
        const matchesError = log.errorMessage ? log.errorMessage.toLowerCase().includes(query) : false;
        const matchesTrace = log.traceDetails ? JSON.stringify(log.traceDetails).toLowerCase().includes(query) : false;
        return matchesRaw || matchesParsed || matchesFeed || matchesReason || matchesError || matchesTrace;
      }

      return true;
    });
  }, [logs, activeFilter, searchTerm]);

  const formatIgnoreReason = (reason: string | null): { text: string; bg: string; border: string; color: string } => {
    if (!reason) return { text: 'N/A', bg: 'bg-neutral-800', border: 'border-neutral-700', color: 'text-neutral-400' };
    switch (reason) {
      case 'parse_error':
        return {
          text: 'Грешка при парсване (Parser Error / Exception)',
          bg: 'bg-red-950/40',
          border: 'border-red-800/60',
          color: 'text-red-300',
        };
      case 'entry_error':
        return {
          text: 'Грешка при обработка на записа (Entry Processing Error)',
          bg: 'bg-red-950/40',
          border: 'border-red-800/60',
          color: 'text-red-300',
        };
      case 'omdb_error':
        return {
          text: 'Грешка при комуникация с OMDb (OMDb API Error)',
          bg: 'bg-red-950/40',
          border: 'border-red-800/60',
          color: 'text-red-300',
        };
      case 'excluded_country_or_genre':
        return {
          text: 'Филтрирана страна/жанр (Excluded Country/Genre)',
          bg: 'bg-amber-950/40',
          border: 'border-amber-800/60',
          color: 'text-amber-300',
        };
      case 'omdb_not_found':
        return {
          text: 'Няма намерено в OMDb (OMDb Match Not Found)',
          bg: 'bg-orange-950/40',
          border: 'border-orange-800/60',
          color: 'text-orange-300',
        };
      case 'no_title':
        return {
          text: 'Неразпознато заглавие (Title Parse Failed)',
          bg: 'bg-red-950/40',
          border: 'border-red-800/60',
          color: 'text-red-300',
        };
      case 'omdb_limit_reached':
        return {
          text: 'Достигнат OMDb лимит (API Rate Limit)',
          bg: 'bg-purple-950/40',
          border: 'border-purple-800/60',
          color: 'text-purple-300',
        };
      case 'empty_title':
        return {
          text: 'Празно RSS заглавие (Empty Feed Item)',
          bg: 'bg-neutral-800',
          border: 'border-neutral-700',
          color: 'text-neutral-400',
        };
      case 'parse_only':
        return {
          text: 'Режим само парсване (Parse Only Mode)',
          bg: 'bg-blue-950/40',
          border: 'border-blue-800/60',
          color: 'text-blue-300',
        };
      case 'media_type_mismatch':
        return {
          text: 'Несъответствие в типа (филм/сериал разминаване)',
          bg: 'bg-amber-950/40',
          border: 'border-amber-800/60',
          color: 'text-amber-300',
        };
      case 'year_mismatch':
        return {
          text: 'Несъответствие в годината (> 1 г. разлика)',
          bg: 'bg-amber-950/40',
          border: 'border-amber-800/60',
          color: 'text-amber-300',
        };
      case 'ai_rejected':
        return {
          text: 'Отхвърлено от AI валидация (Нисък скор/разминаване)',
          bg: 'bg-purple-950/40',
          border: 'border-purple-800/60',
          color: 'text-purple-300',
        };
      default:
        return {
          text: reason,
          bg: 'bg-neutral-800',
          border: 'border-neutral-700',
          color: 'text-neutral-300',
        };
    }
  };

  const formatDate = (date: Date): string => {
    if (!date || isNaN(date.getTime()) || date.getTime() === 0) return 'Няма дата';
    return date.toLocaleString('bg-BG', {
      day: '2-digit',
      month: '2-digit',
      year: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  return (
    <div className="space-y-6">
      {/* View Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-neutral-900 border border-neutral-800 p-6 rounded-xl">
        <div>
          <div className="flex items-center gap-2 text-amber-400 mb-1">
            <FileText className="w-5 h-5" />
            <h2 className="text-lg font-bold text-neutral-100">Диагностика и лог от парсването (Parse & Trace Log)</h2>
          </div>
          <p className="text-sm text-neutral-400">
            История на обработените RSS заглавия от последните 7 дни. Кликнете на ред за да проследите целия процес (парсване, OMDb кеш, заявки и филтри).
          </p>
        </div>

        <button
          onClick={fetchLogsAndMappings}
          disabled={isLoading}
          data-testid="refresh-parse-logs-button"
          className="inline-flex items-center justify-center gap-2 min-h-[44px] px-4 py-2 text-sm font-medium text-neutral-200 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer disabled:opacity-50"
        >
          <RefreshCw className={`w-4 h-4 ${isLoading ? 'animate-spin text-amber-400' : ''}`} />
          {isLoading ? 'Зареждане...' : 'Обнови (Refresh)'}
        </button>
      </div>

      {/* Metric Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-neutral-900 border border-neutral-800 p-4 rounded-xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-neutral-800 text-neutral-300 flex items-center justify-center shrink-0">
            <Clock className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-neutral-400">Общо обработени (7 дни)</div>
            <div className="text-xl font-bold text-neutral-100" data-testid="metric-total">{metrics.total}</div>
          </div>
        </div>

        <div className="bg-neutral-900 border border-neutral-800 p-4 rounded-xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-emerald-950 text-emerald-400 flex items-center justify-center shrink-0">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-neutral-400">Успешно парснати</div>
            <div className="text-xl font-bold text-emerald-400" data-testid="metric-parsed">{metrics.parsedSuccess}</div>
          </div>
        </div>

        <div className="bg-neutral-900 border border-neutral-800 p-4 rounded-xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-blue-950 text-blue-400 flex items-center justify-center shrink-0">
            <Film className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-neutral-400">Намерени в OMDb</div>
            <div className="text-xl font-bold text-blue-400" data-testid="metric-omdb">{metrics.omdbFound}</div>
          </div>
        </div>

        <div
          onClick={() => setActiveFilter('unfound')}
          className="bg-neutral-900 border border-orange-900/60 p-4 rounded-xl flex items-center gap-3 cursor-pointer hover:bg-neutral-800/80 transition-colors"
        >
          <div className="w-10 h-10 rounded-lg bg-orange-950 text-orange-400 flex items-center justify-center shrink-0">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-orange-300 font-medium">Ненамерени заглавия</div>
            <div className="text-xl font-bold text-orange-400" data-testid="metric-unfound">{metrics.unfoundCount}</div>
          </div>
        </div>

        <div className="bg-neutral-900 border border-neutral-800 p-4 rounded-xl flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-amber-950 text-amber-400 flex items-center justify-center shrink-0">
            <Filter className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-neutral-400">Филтрирани / Игнорирани</div>
            <div className="text-xl font-bold text-amber-400" data-testid="metric-ignored">{metrics.ignoredCount}</div>
          </div>
        </div>
      </div>

      {/* Mapping Feedback Alerts */}
      {mappingSuccess && (
        <div className="flex items-center gap-3 p-4 bg-emerald-950/80 border border-emerald-800 rounded-xl text-sm text-emerald-200">
          <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0" />
          <span>{mappingSuccess}</span>
          <button onClick={() => setMappingSuccess(null)} className="ml-auto text-emerald-400 hover:text-emerald-200 text-xs font-semibold">
            Затвори
          </button>
        </div>
      )}
      {mappingError && (
        <div className="flex items-center gap-3 p-4 bg-red-950/80 border border-red-800 rounded-xl text-sm text-red-200">
          <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
          <span>{mappingError}</span>
          <button onClick={() => setMappingError(null)} className="ml-auto text-red-400 hover:text-red-200 text-xs font-semibold">
            Затвори
          </button>
        </div>
      )}

      {/* Filter and Search Bar */}
      <div className="bg-neutral-900 border border-neutral-800 p-4 rounded-xl space-y-4">
        <div className="flex flex-col sm:flex-row gap-3">
          {/* Search Input */}
          <div className="relative flex-1">
            <Search className="w-4 h-4 absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-400 pointer-events-none" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Търси по заглавие, IMDb ID, OMDb данни, причина за отхвърляне..."
              data-testid="parse-log-search-input"
              className="w-full pl-10 pr-4 py-2.5 bg-neutral-950 border border-neutral-800 rounded-lg text-sm text-neutral-100 placeholder-neutral-500 focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500"
            />
          </div>
        </div>

        {/* Filter Tabs */}
        <div className="flex flex-wrap gap-2 pt-1 border-t border-neutral-800/80">
          <button
            onClick={() => setActiveFilter('all')}
            data-testid="filter-tab-all"
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
              activeFilter === 'all'
                ? 'bg-amber-500 text-neutral-950 font-semibold'
                : 'bg-neutral-800 text-neutral-300 hover:bg-neutral-700'
            }`}
          >
            Всички ({logs.length})
          </button>
          <button
            onClick={() => setActiveFilter('unfound')}
            data-testid="filter-tab-unfound"
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer flex items-center gap-1.5 ${
              activeFilter === 'unfound'
                ? 'bg-orange-500 text-neutral-950 font-semibold'
                : 'bg-orange-950/40 text-orange-300 border border-orange-800/60 hover:bg-orange-900/50'
            }`}
          >
            <AlertTriangle className="w-3.5 h-3.5" />
            Ненамерени заглавия ({metrics.unfoundCount})
          </button>
          <button
            onClick={() => setActiveFilter('successful')}
            data-testid="filter-tab-successful"
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
              activeFilter === 'successful'
                ? 'bg-emerald-500 text-neutral-950 font-semibold'
                : 'bg-neutral-800 text-neutral-300 hover:bg-neutral-700'
            }`}
          >
            Добавени в каталога ({logs.filter((l) => !l.ignored && l.parsedSuccessfully).length})
          </button>
          <button
            onClick={() => setActiveFilter('omdb_found')}
            data-testid="filter-tab-omdb"
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
              activeFilter === 'omdb_found'
                ? 'bg-blue-500 text-neutral-950 font-semibold'
                : 'bg-neutral-800 text-neutral-300 hover:bg-neutral-700'
            }`}
          >
            OMDb Намерени ({metrics.omdbFound})
          </button>
          <button
            onClick={() => setActiveFilter('ignored')}
            data-testid="filter-tab-ignored"
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
              activeFilter === 'ignored'
                ? 'bg-amber-500 text-neutral-950 font-semibold'
                : 'bg-neutral-800 text-neutral-300 hover:bg-neutral-700'
            }`}
          >
            Филтрирани / Игнорирани ({metrics.ignoredCount})
          </button>
          <button
            onClick={() => setActiveFilter('failed_parse')}
            data-testid="filter-tab-failed"
            className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-colors cursor-pointer ${
              activeFilter === 'failed_parse'
                ? 'bg-red-500 text-neutral-950 font-semibold'
                : 'bg-neutral-800 text-neutral-300 hover:bg-neutral-700'
            }`}
          >
            Грешка при парсване ({metrics.parseErrorsCount})
          </button>
        </div>
      </div>

      {/* Unfound Titles Dedicated Section */}
      {unfoundLogs.length > 0 && (activeFilter === 'all' || activeFilter === 'unfound') && (
        <div className="bg-neutral-900 border border-orange-900/60 rounded-xl p-6 space-y-4" data-testid="unfound-titles-section">
          <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
            <div className="flex items-center gap-2 text-orange-400">
              <AlertTriangle className="w-5 h-5 shrink-0" />
              <h3 className="text-base font-bold text-neutral-100">
                Секция за ненамерени заглавия (Unfound Titles - Manual IMDb Mapping)
              </h3>
            </div>
            <span className="text-xs px-2.5 py-1 rounded bg-orange-950/80 text-orange-300 border border-orange-800/80 font-medium">
              {unfoundLogs.length} заглавие(я)
            </span>
          </div>

          <p className="text-xs text-neutral-400">
            Заглавията по-долу не са намерени автоматично в OMDb. Въведете техния IMDb ID (напр. <code className="text-amber-300 font-mono">tt0133093</code>), за да се запишат в Firestore таблицата <code className="text-amber-300 font-mono">manualMappings</code>. При следващото сканиране скенерът ще ги потърси директно по ID и ще ги добави в каталога.
          </p>

          <div className="space-y-3">
            {unfoundLogs.map((log) => {
              const existingMapping = activeMappingsMap.get(log.id);
              const isSavingThis = savingMappingId === log.id;
              const currentInputValue = imdbInputs[log.id] !== undefined ? imdbInputs[log.id] : (existingMapping?.imdbId || '');

              return (
                <div
                  key={`unfound-${log.id}`}
                  className="p-4 bg-neutral-950 border border-neutral-800 rounded-lg flex flex-col md:flex-row md:items-center justify-between gap-4 hover:border-neutral-700 transition-colors"
                  data-testid={`unfound-card-${log.id}`}
                >
                  <div className="space-y-1 max-w-xl">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-semibold text-neutral-100">
                        {log.parsedTitle ? `${log.parsedTitle} ${log.parsedYear ? `(${log.parsedYear})` : ''}` : log.rawTitle}
                      </span>
                      <span className="text-[11px] px-2 py-0.5 rounded bg-neutral-800 text-neutral-400 border border-neutral-700">
                        {log.feedName}
                      </span>
                    </div>
                    <div className="text-xs text-neutral-400 font-mono break-all">
                      {log.rawTitle}
                    </div>
                  </div>

                  {/* Manual Mapping Input or Status */}
                  <div className="flex items-center gap-2 shrink-0">
                    {existingMapping ? (
                      <div className="flex items-center gap-2 bg-emerald-950/50 border border-emerald-800/60 p-2 rounded-lg">
                        <Check className="w-4 h-4 text-emerald-400 shrink-0" />
                        <div className="text-xs">
                          <span className="text-neutral-300 font-medium">IMDb ID: </span>
                          <span className="font-mono text-emerald-300 font-bold">{existingMapping.imdbId}</span>
                          <span className="text-[11px] text-neutral-400 block">(Чака сканиране)</span>
                        </div>
                        <button
                          onClick={() => handleDeleteMapping(existingMapping.id)}
                          disabled={isSavingThis}
                          title="Премахни мапинга"
                          data-testid={`delete-mapping-button-${log.id}`}
                          className="p-1.5 text-neutral-400 hover:text-red-400 rounded hover:bg-neutral-800 transition-colors cursor-pointer ml-2"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2 w-full md:w-auto">
                        <div className="relative">
                          <Link className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-neutral-500 pointer-events-none" />
                          <input
                            type="text"
                            value={currentInputValue}
                            onChange={(e) => setImdbInputs((prev) => ({ ...prev, [log.id]: e.target.value }))}
                            placeholder="tt0133093"
                            data-testid={`imdb-input-${log.id}`}
                            className="w-32 md:w-36 pl-8 pr-3 py-1.5 bg-neutral-900 border border-neutral-700 rounded text-xs text-neutral-100 font-mono placeholder-neutral-500 focus:outline-none focus:border-amber-500"
                          />
                        </div>
                        <button
                          onClick={() => handleSaveImdbId(log)}
                          disabled={isSavingThis || !currentInputValue.trim()}
                          data-testid={`save-mapping-button-${log.id}`}
                          className="inline-flex items-center gap-1.5 min-h-[34px] px-3 py-1.5 text-xs font-semibold text-neutral-950 bg-amber-500 hover:bg-amber-400 rounded transition-colors cursor-pointer disabled:opacity-50"
                        >
                          {isSavingThis ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Plus className="w-3.5 h-3.5" />
                          )}
                          Запази IMDb ID
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Loading State */}
      {isLoading && (
        <div className="flex flex-col items-center justify-center py-16 bg-neutral-900 border border-neutral-800 rounded-xl">
          <Loader2 className="w-8 h-8 text-amber-400 animate-spin mb-3" />
          <p className="text-sm text-neutral-400">Зареждане на лога от парсването...</p>
        </div>
      )}

      {/* Error State */}
      {error && !isLoading && (
        <div className="flex items-center gap-3 p-4 bg-red-950/60 border border-red-800 rounded-xl text-sm text-red-200">
          <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
          <span>Грешка при зареждане: {error.message}</span>
          <button
            onClick={fetchLogsAndMappings}
            className="ml-auto min-h-[36px] px-3 py-1.5 text-xs font-medium bg-red-900/50 border border-red-700 rounded-lg hover:bg-red-800 transition-colors cursor-pointer"
          >
            Опитай отново
          </button>
        </div>
      )}

      {/* Empty Logs State */}
      {!isLoading && !error && logs.length === 0 && (
        <div
          data-testid="parse-logs-empty"
          className="flex flex-col items-center justify-center py-16 text-center px-4 bg-neutral-900 border border-neutral-800 rounded-xl"
        >
          <FileText className="w-12 h-12 text-neutral-600 mb-3" />
          <h3 className="text-base font-semibold text-neutral-200 mb-1">Няма намерени записи в лога</h3>
          <p className="text-sm text-neutral-400 max-w-md">
            Все още няма регистрирани парснати RSS заглавия от последните 7 дни.
          </p>
        </div>
      )}

      {/* Empty Search Result State */}
      {!isLoading && !error && logs.length > 0 && filteredLogs.length === 0 && (
        <div
          data-testid="parse-logs-filtered-empty"
          className="flex flex-col items-center justify-center py-12 text-center px-4 bg-neutral-900 border border-neutral-800 rounded-xl"
        >
          <Search className="w-10 h-10 text-neutral-600 mb-3" />
          <h3 className="text-base font-semibold text-neutral-200 mb-1">Няма резултати за избрания филтър</h3>
          <p className="text-sm text-neutral-400">Опитайте с друг критерий за търсене или нулирайте филтрите.</p>
        </div>
      )}

      {/* Logs Table / List */}
      {!isLoading && !error && filteredLogs.length > 0 && (
        <div className="bg-neutral-900 border border-neutral-800 rounded-xl overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm" data-testid="parse-logs-table">
              <thead className="bg-neutral-950/80 border-b border-neutral-800 text-xs text-neutral-400 font-semibold uppercase tracking-wider">
                <tr>
                  <th className="w-10 px-3 py-3.5 text-center"></th>
                  <th className="px-4 py-3.5">Дата & Време</th>
                  <th className="px-4 py-3.5">RSS Канал & Име</th>
                  <th className="px-4 py-3.5">Резултат от Парсване</th>
                  <th className="px-4 py-3.5">OMDb Данни</th>
                  <th className="px-4 py-3.5">Статус / Причина</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-800/60">
                {filteredLogs.map((log) => {
                  const reasonInfo = formatIgnoreReason(log.ignoreReason);
                  const isExpanded = expandedLogId === log.id;
                  const trace = log.traceDetails;

                  return (
                    <React.Fragment key={log.id}>
                      <tr
                        onClick={() => toggleExpand(log.id)}
                        className={`hover:bg-neutral-800/50 transition-colors cursor-pointer ${
                          isExpanded ? 'bg-neutral-800/30' : ''
                        }`}
                        data-testid={`log-row-${log.id}`}
                      >
                        {/* Expand toggle */}
                        <td className="px-3 py-3.5 text-center">
                          <button
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleExpand(log.id);
                            }}
                            className="p-1 rounded text-neutral-400 hover:text-amber-400 hover:bg-neutral-800 transition-colors"
                            data-testid={`expand-button-${log.id}`}
                            title={isExpanded ? 'Свий детайли' : 'Виж диагностика'}
                          >
                            {isExpanded ? <ChevronUp className="w-4 h-4 text-amber-400" /> : <ChevronDown className="w-4 h-4" />}
                          </button>
                        </td>

                        {/* Date & Time */}
                        <td className="px-4 py-3.5 text-xs text-neutral-400 whitespace-nowrap font-mono">
                          {formatDate(log.processedAt)}
                        </td>

                        {/* RSS Title & Feed */}
                        <td className="px-4 py-3.5 max-w-xs md:max-w-md">
                          <div className="flex items-center gap-1.5 mb-1">
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-neutral-800 text-neutral-300 border border-neutral-700">
                              <Tag className="w-3 h-3 text-amber-400" />
                              {log.feedName || 'RSS'}
                            </span>
                          </div>
                          <div className="text-xs text-neutral-200 font-medium break-words" title={log.rawTitle}>
                            {log.rawTitle}
                          </div>
                        </td>

                        {/* Parsed Result */}
                        <td className="px-4 py-3.5">
                          {log.parsedSuccessfully ? (
                            <div>
                              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-emerald-950/60 text-emerald-300 border border-emerald-800/60 mb-1">
                                <CheckCircle2 className="w-3.5 h-3.5" />
                                Парснато
                              </div>
                              <div className="text-xs font-semibold text-neutral-100">
                                {log.parsedTitle} {log.parsedYear ? `(${log.parsedYear})` : ''}
                              </div>
                            </div>
                          ) : (
                            <div>
                              <div className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-950/60 text-red-300 border border-red-800/60">
                                <XCircle className="w-3.5 h-3.5" />
                                {log.ignoreReason === 'parse_error' ? 'Грешка при парсване' : 'Неразпознато'}
                              </div>
                            </div>
                          )}
                          {log.errorMessage && (
                            <div
                              data-testid={`log-error-${log.id}`}
                              className="mt-1.5 flex items-start gap-1.5 p-2 rounded bg-red-950/60 border border-red-800/70 text-[11px] text-red-200 font-mono break-all"
                            >
                              <AlertTriangle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
                              <span>{log.errorMessage}</span>
                            </div>
                          )}
                        </td>

                        {/* OMDb Status */}
                        <td className="px-4 py-3.5 whitespace-nowrap">
                          {log.omdbStatus === 'found' && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-blue-950/60 text-blue-300 border border-blue-800/60">
                              <Globe className="w-3.5 h-3.5" />
                              Намерено
                            </span>
                          )}
                          {log.omdbStatus === 'not_found' && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-orange-950/60 text-orange-300 border border-orange-800/60">
                              <AlertTriangle className="w-3.5 h-3.5" />
                              Няма съвпадение
                            </span>
                          )}
                          {log.omdbStatus === 'skipped' && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-neutral-800 text-neutral-400 border border-neutral-700">
                              Пропуснато
                            </span>
                          )}
                          {log.omdbStatus === 'error' && (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium bg-red-950/60 text-red-300 border border-red-800/60">
                              Грешка API
                            </span>
                          )}
                          {log.omdbStatus === 'not_parsed' && (
                            <span className="text-xs text-neutral-500">-</span>
                          )}
                        </td>

                        {/* Final Status & Ignore Reason */}
                        <td className="px-4 py-3.5">
                          {!log.ignored ? (
                            <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-semibold bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                              <CheckCircle2 className="w-3.5 h-3.5" />
                              Добавено в каталога
                            </span>
                          ) : (
                            <div className="space-y-1">
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-semibold bg-amber-950/60 text-amber-300 border border-amber-800/60">
                                <Filter className="w-3.5 h-3.5" />
                                Игнорирано
                              </span>
                              <div className={`text-[11px] px-2 py-1 rounded border ${reasonInfo.bg} ${reasonInfo.border} ${reasonInfo.color}`}>
                                {reasonInfo.text}
                              </div>
                            </div>
                          )}
                        </td>
                      </tr>

                      {/* Expandable Diagnostic Trace Breakdown */}
                      {isExpanded && (
                        <tr className="bg-neutral-950/90 border-b border-neutral-800">
                          <td colSpan={6} className="p-4 md:p-6 space-y-4" data-testid={`diagnostic-drawer-${log.id}`}>
                            <div className="flex items-center justify-between border-b border-neutral-800 pb-3">
                              <div className="flex items-center gap-2 text-amber-400 font-semibold text-sm">
                                <Layers className="w-4 h-4" />
                                <span>Диагностичен отчет за обработката (Trace Pipeline)</span>
                              </div>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  copyTraceJson(log);
                                }}
                                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-neutral-800 hover:bg-neutral-700 text-neutral-200 border border-neutral-700 transition-colors cursor-pointer"
                                title="Копирай пълния JSON лог"
                              >
                                {copiedLogId === log.id ? (
                                  <>
                                    <Check className="w-3.5 h-3.5 text-emerald-400" />
                                    <span className="text-emerald-400">Копирано!</span>
                                  </>
                                ) : (
                                  <>
                                    <Copy className="w-3.5 h-3.5" />
                                    <span>Копирай JSON</span>
                                  </>
                                )}
                              </button>
                            </div>

                            {/* 4-Step Pipeline Cards */}
                            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                              {/* Step 1: RSS Parser */}
                              <div className="p-3.5 bg-neutral-900/80 border border-neutral-800 rounded-lg space-y-2">
                                <div className="flex items-center gap-2 text-xs font-semibold text-neutral-300">
                                  <FileText className="w-4 h-4 text-amber-400 shrink-0" />
                                  <span>1. Парсване на заглавие</span>
                                </div>
                                <div className="space-y-1 text-xs text-neutral-400">
                                  <div>
                                    <span className="text-neutral-500">Заглавие: </span>
                                    <span className="text-neutral-200 font-medium">{log.parsedTitle || '—'}</span>
                                  </div>
                                  <div>
                                    <span className="text-neutral-500">Година: </span>
                                    <span className="text-neutral-200 font-medium">{log.parsedYear ?? '—'}</span>
                                  </div>
                                  <div>
                                    <span className="text-neutral-500">Качество / Rip: </span>
                                    <span className="text-neutral-200 font-mono">
                                      {trace?.parsedQuality || '—'} / {trace?.parsedRipType || '—'}
                                    </span>
                                  </div>
                                  <div>
                                    <span className="text-neutral-500">Тип: </span>
                                    <span className="text-neutral-200">
                                      {trace?.parsedIsSeries ? 'Сериал (series)' : 'Филм (movie)'}
                                    </span>
                                  </div>
                                </div>
                              </div>

                              {/* Step 2: Cache Layer */}
                              <div className="p-3.5 bg-neutral-900/80 border border-neutral-800 rounded-lg space-y-2">
                                <div className="flex items-center gap-2 text-xs font-semibold text-neutral-300">
                                  <Database className="w-4 h-4 text-blue-400 shrink-0" />
                                  <span>2. Проверка в кеша</span>
                                </div>
                                <div className="space-y-1 text-xs text-neutral-400">
                                  <div>
                                    <span className="text-neutral-500">Кеш статус: </span>
                                    {trace?.cacheHit ? (
                                      <span className="text-emerald-400 font-medium">Хит ({trace.cacheStatus || 'found'})</span>
                                    ) : (
                                      <span className="text-neutral-400">Липсва в кеша / Нова заявка</span>
                                    )}
                                  </div>
                                  {trace?.cacheFetchedAt && (
                                    <div>
                                      <span className="text-neutral-500">Записан на: </span>
                                      <span className="text-neutral-300 font-mono">{trace.cacheFetchedAt}</span>
                                    </div>
                                  )}
                                  {trace?.cacheKey && (
                                    <div className="truncate" title={trace.cacheKey}>
                                      <span className="text-neutral-500">Ключ: </span>
                                      <span className="text-neutral-300 font-mono text-[11px]">{trace.cacheKey}</span>
                                    </div>
                                  )}
                                </div>
                              </div>

                              {/* Step 3: OMDb Match */}
                              <div className="p-3.5 bg-neutral-900/80 border border-neutral-800 rounded-lg space-y-2">
                                <div className="flex items-center gap-2 text-xs font-semibold text-neutral-300">
                                  <Globe className="w-4 h-4 text-purple-400 shrink-0" />
                                  <span>3. OMDb Резултат</span>
                                </div>
                                <div className="space-y-1 text-xs text-neutral-400">
                                  <div>
                                    <span className="text-neutral-500">Статус: </span>
                                    {log.omdbStatus === 'found' ? (
                                      <span className="text-emerald-400 font-medium">Намерен запис</span>
                                    ) : log.omdbStatus === 'not_found' ? (
                                      <span className="text-orange-400 font-medium">Няма съвпадение</span>
                                    ) : (
                                      <span className="text-neutral-300">{log.omdbStatus}</span>
                                    )}
                                  </div>
                                  {trace?.omdbImdbId && (
                                    <div className="flex items-center gap-1.5">
                                      <span className="text-neutral-500">IMDb ID: </span>
                                      <a
                                        href={`https://www.imdb.com/title/${trace.omdbImdbId}`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="text-amber-400 hover:underline font-mono inline-flex items-center gap-1"
                                      >
                                        {trace.omdbImdbId}
                                        <ExternalLink className="w-3 h-3" />
                                      </a>
                                    </div>
                                  )}
                                  {trace?.omdbFoundTitle && (
                                    <div>
                                      <span className="text-neutral-500">OMDb заглавие: </span>
                                      <span className="text-neutral-200 font-medium">
                                        {trace.omdbFoundTitle} ({trace.omdbFoundYear})
                                      </span>
                                    </div>
                                  )}
                                  {trace?.omdbRating && (
                                    <div>
                                      <span className="text-neutral-500">Рейтинг: </span>
                                      <span className="text-amber-300 font-bold">★ {trace.omdbRating}</span>
                                    </div>
                                  )}
                                </div>
                              </div>

                              {/* Step 4: Decision & Filters */}
                              <div className="p-3.5 bg-neutral-900/80 border border-neutral-800 rounded-lg space-y-2">
                                <div className="flex items-center gap-2 text-xs font-semibold text-neutral-300">
                                  <ShieldAlert className="w-4 h-4 text-emerald-400 shrink-0" />
                                  <span>4. Решение & Филтри</span>
                                </div>
                                <div className="space-y-1 text-xs text-neutral-400">
                                  <div>
                                    <span className="text-neutral-500">Резултат: </span>
                                    {!log.ignored ? (
                                      <span className="text-emerald-400 font-semibold">Добавено в каталога</span>
                                    ) : (
                                      <span className="text-amber-400 font-semibold">Игнорирано</span>
                                    )}
                                  </div>
                                  {log.errorMessage ? (
                                    <div className="text-red-300 font-mono text-[11px] break-words">
                                      {log.errorMessage}
                                    </div>
                                  ) : trace?.decisionDetails ? (
                                    <div className="text-neutral-300 text-[11px] break-words">
                                      {trace.decisionDetails}
                                    </div>
                                  ) : null}
                                </div>
                              </div>
                            </div>

                            {/* Additional Metadata tags if available */}
                            {(trace?.omdbGenres?.length || trace?.omdbCountries?.length) && (
                              <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-neutral-800/80 text-xs">
                                {trace.omdbGenres && trace.omdbGenres.length > 0 && (
                                  <div className="flex items-center gap-1.5">
                                    <span className="text-neutral-500">Жанрове:</span>
                                    {trace.omdbGenres.map((g, idx) => (
                                      <span key={idx} className="px-2 py-0.5 rounded bg-neutral-800 text-neutral-300 border border-neutral-700 text-[11px]">
                                        {g}
                                      </span>
                                    ))}
                                  </div>
                                )}
                                {trace.omdbCountries && trace.omdbCountries.length > 0 && (
                                  <div className="flex items-center gap-1.5 ml-4">
                                    <span className="text-neutral-500">Държави:</span>
                                    {trace.omdbCountries.map((c, idx) => (
                                      <span key={idx} className="px-2 py-0.5 rounded bg-neutral-800 text-neutral-300 border border-neutral-700 text-[11px]">
                                        {c}
                                      </span>
                                    ))}
                                  </div>
                                )}
                              </div>
                            )}
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
};

