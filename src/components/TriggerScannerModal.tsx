import React, { useState, useEffect } from 'react';
import { Play, Settings, CheckCircle2, AlertCircle, ExternalLink, X, Loader2, RefreshCw, Rss, Search, Sparkles, LayoutList } from 'lucide-react';

interface TriggerScannerModalProps {
  buttonClassName?: string;
  buttonVariant?: 'primary' | 'secondary' | 'header';
}

const STORAGE_KEYS = {
  OWNER: 'movies_feed_gh_owner',
  REPO: 'movies_feed_gh_repo',
  PAT: 'movies_feed_gh_pat',
  WORKFLOW: 'movies_feed_gh_workflow',
  REF: 'movies_feed_gh_ref',
  FORCE_DAYS: 'movies_feed_gh_force_days',
  AUDIT_DAYS: 'movies_feed_gh_audit_days',
  OMDB_API_KEY: 'movies_feed_omdb_api_key',
};

export const TriggerScannerModal: React.FC<TriggerScannerModalProps> = ({
  buttonClassName,
  buttonVariant = 'header',
}) => {
  const [isSettingsOpen, setIsSettingsOpen] = useState<boolean>(false);
  const [isActionsOpen, setIsActionsOpen] = useState<boolean>(false);
  const [owner, setOwner] = useState<string>('');
  const [repo, setRepo] = useState<string>('movies-feed');
  const [pat, setPat] = useState<string>('');
  const [workflow, setWorkflow] = useState<string>('scanner.yml');
  const [ref, setRef] = useState<string>('main');
  const [dryRun, setDryRun] = useState<boolean>(false);
  const [forceDays, setForceDays] = useState<string>('0');
  const [auditDays, setAuditDays] = useState<string>('0');
  const [omdbApiKey, setOmdbApiKey] = useState<string>('');

  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<{
    type: 'success' | 'error' | null;
    text: string;
    actionUrl?: string;
  }>({ type: null, text: '' });

  // Load initial credentials from localStorage or VITE_ environment variables
  useEffect(() => {
    const savedOwner =
      localStorage.getItem(STORAGE_KEYS.OWNER) ||
      import.meta.env.VITE_GITHUB_OWNER ||
      '';
    const savedRepo =
      localStorage.getItem(STORAGE_KEYS.REPO) ||
      import.meta.env.VITE_GITHUB_REPO ||
      'movies-feed';
    const savedPat =
      localStorage.getItem(STORAGE_KEYS.PAT) ||
      import.meta.env.VITE_GITHUB_PAT ||
      '';
    const savedWorkflow =
      localStorage.getItem(STORAGE_KEYS.WORKFLOW) || 'scanner.yml';
    const savedRef = localStorage.getItem(STORAGE_KEYS.REF) || 'main';
    const savedForceDays =
      localStorage.getItem(STORAGE_KEYS.FORCE_DAYS) || '0';
    const savedAuditDays =
      localStorage.getItem(STORAGE_KEYS.AUDIT_DAYS) || '0';
    const savedOmdbApiKey =
      localStorage.getItem(STORAGE_KEYS.OMDB_API_KEY) ||
      import.meta.env.VITE_OMDB_API_KEY ||
      import.meta.env.OMDB_API_KEY ||
      '';

    setOwner(savedOwner);
    setRepo(savedRepo);
    setPat(savedPat);
    setWorkflow(savedWorkflow);
    setRef(savedRef);
    setForceDays(savedForceDays);
    setAuditDays(savedAuditDays);
    setOmdbApiKey(savedOmdbApiKey);
  }, []);

  const handleSaveSettings = () => {
    localStorage.setItem(STORAGE_KEYS.OWNER, owner.trim());
    localStorage.setItem(STORAGE_KEYS.REPO, repo.trim());
    localStorage.setItem(STORAGE_KEYS.PAT, pat.trim());
    localStorage.setItem(STORAGE_KEYS.WORKFLOW, workflow.trim());
    localStorage.setItem(STORAGE_KEYS.REF, ref.trim());
    localStorage.setItem(STORAGE_KEYS.FORCE_DAYS, forceDays.trim());
    localStorage.setItem(STORAGE_KEYS.AUDIT_DAYS, auditDays.trim());
    localStorage.setItem(STORAGE_KEYS.OMDB_API_KEY, omdbApiKey.trim());
  };

  const handleSaveOnly = () => {
    handleSaveSettings();
    setToastMessage({
      type: 'success',
      text: 'Настройките са запазени успешно в браузъра!',
    });
    setIsSettingsOpen(false);
  };

  const executeDispatch = async (
    targetMode: string
  ) => {
    const trimmedOwner = owner.trim();
    const trimmedRepo = repo.trim();
    const trimmedPat = pat.trim();

    if (!trimmedOwner || !trimmedRepo || !trimmedPat) {
      setIsActionsOpen(false);
      setIsSettingsOpen(true);
      setToastMessage({
        type: 'error',
        text: 'Моля, въведете GitHub Owner, Repo и Token преди да стартирате действие.',
      });
      return;
    }

    setIsSubmitting(true);
    setToastMessage({ type: null, text: '' });
    setIsActionsOpen(false); // Close actions menu while submitting

    try {
      const url = `https://api.github.com/repos/${trimmedOwner}/${trimmedRepo}/actions/workflows/${workflow.trim() || 'scanner.yml'}/dispatches`;
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          Accept: 'application/vnd.github+json',
          Authorization: `Bearer ${trimmedPat}`,
          'X-GitHub-Api-Version': '2022-11-28',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ref: ref.trim() || 'main',
          inputs: {
            dry_run: dryRun,
            force_days: forceDays,
            audit_days: auditDays,
            mode: targetMode,
          },
        }),
      });

      if (response.status === 204 || response.ok) {
        setToastMessage({
          type: 'success',
          text: `Действието (${targetMode}) е стартирано успешно в GitHub Actions!`,
          actionUrl: `https://github.com/${trimmedOwner}/${trimmedRepo}/actions`,
        });
      } else if (response.status === 401 || response.status === 403) {
        setToastMessage({
          type: 'error',
          text: `Грешка при автентикация (${response.status}). Проверете дали вашият GitHub token има 'actions:write' права.`,
        });
        setIsSettingsOpen(true);
      } else if (response.status === 404) {
        setToastMessage({
          type: 'error',
          text: `Репозиторията ${trimmedOwner}/${trimmedRepo} или workflow файлът (${workflow}) не бяха намерени (404).`,
        });
        setIsSettingsOpen(true);
      } else {
        const errData = await response.json().catch(() => ({}));
        setToastMessage({
          type: 'error',
          text: `Грешка (${response.status}): ${errData.message || response.statusText}`,
        });
        setIsSettingsOpen(true);
      }
    } catch (err) {
      setToastMessage({
        type: 'error',
        text: `Мрежова грешка: ${err instanceof Error ? err.message : 'Грешка при връзка с GitHub API.'}`,
      });
      setIsSettingsOpen(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  const defaultBtnClass =
    buttonVariant === 'header'
      ? 'inline-flex items-center gap-2 min-h-[40px] px-3.5 py-2 text-sm font-semibold text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-xl hover:bg-amber-500/20 hover:border-amber-500/50 transition-all cursor-pointer shadow-sm active:scale-[0.98] disabled:opacity-50'
      : 'inline-flex items-center gap-2 min-h-[44px] px-4 py-2.5 text-sm font-semibold text-neutral-950 bg-amber-500 hover:bg-amber-400 rounded-lg transition-colors cursor-pointer shadow-sm active:scale-[0.98] disabled:opacity-50';

  return (
    <div className="relative inline-flex items-center gap-2">
      {/* 1-Click Trigger Button -> Now opens Actions Menu */}
      <button
        onClick={() => setIsActionsOpen(true)}
        disabled={isSubmitting}
        type="button"
        data-testid="trigger-scanner-button"
        className={buttonClassName || defaultBtnClass}
        title="Избор на действия за сканиране"
      >
        {isSubmitting ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
            <span>Стартиране...</span>
          </>
        ) : (
          <>
            <Play className="w-4 h-4 fill-current text-amber-400" />
            <span>Действия</span>
          </>
        )}
      </button>

      {/* Settings Gear Button */}
      <button
        onClick={() => setIsSettingsOpen(true)}
        type="button"
        data-testid="scanner-settings-button"
        className="w-10 h-10 rounded-xl border border-neutral-800 bg-neutral-900 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700 flex items-center justify-center transition-colors cursor-pointer"
        title="Настройки за сканиране и GitHub API"
      >
        <Settings className="w-4 h-4" />
      </button>

      {/* Toast Banner Feedback */}
      {toastMessage.type && !isSettingsOpen && !isActionsOpen && (
        <div
          data-testid="scanner-status-message"
          className={`absolute top-12 left-0 z-40 min-w-[280px] sm:min-w-[340px] p-3 rounded-xl text-xs border shadow-xl flex items-center justify-between gap-2.5 animate-in fade-in duration-200 ${
            toastMessage.type === 'success'
              ? 'bg-emerald-950 border-emerald-800 text-emerald-200'
              : 'bg-red-950 border-red-800 text-red-200'
          }`}
        >
          <div className="flex items-center gap-2">
            {toastMessage.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-red-400 shrink-0" />
            )}
            <span>{toastMessage.text}</span>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            {toastMessage.actionUrl && (
              <a
                href={toastMessage.actionUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="p-1 rounded bg-emerald-900/60 hover:bg-emerald-800 text-emerald-200 transition-colors inline-flex items-center gap-1 font-medium"
                title="Отвори GitHub Actions"
              >
                <span>GitHub</span>
                <ExternalLink className="w-3 h-3" />
              </a>
            )}
            <button
              onClick={() => setToastMessage({ type: null, text: '' })}
              className="p-1 text-neutral-400 hover:text-neutral-200 transition-colors cursor-pointer"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Actions Modal */}
      {isActionsOpen && (
        <div
          data-testid="scanner-actions-modal-backdrop"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200"
        >
          <div
            data-testid="scanner-actions-modal"
            className="w-full max-w-md bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-800 bg-neutral-950/60">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                  <LayoutList className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-neutral-100">Действия</h3>
                  <p className="text-xs text-neutral-400">Изберете процес за изпълнение</p>
                </div>
              </div>
              <button
                onClick={() => setIsActionsOpen(false)}
                data-testid="close-actions-modal-button"
                className="w-8 h-8 rounded-lg text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 flex items-center justify-center transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Actions List */}
            <div className="p-4 space-y-3 overflow-y-auto">
              <button
                type="button"
                data-testid="action-btn-rss"
                onClick={() => executeDispatch('rss')}
                className="w-full text-left p-4 rounded-xl border border-neutral-800 bg-neutral-950/50 hover:bg-neutral-800 hover:border-amber-500/50 transition-all cursor-pointer group flex gap-4 items-start"
              >
                <div className="p-2.5 bg-blue-500/10 text-blue-400 rounded-lg group-hover:scale-110 transition-transform">
                  <Rss className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-neutral-200 group-hover:text-amber-400 transition-colors">Сканиране на RSS емисии</h4>
                  <p className="text-xs text-neutral-400 mt-1">Извлича нови филми и сериали от конфигурираните RSS източници.</p>
                </div>
              </button>

              <button
                type="button"
                data-testid="action-btn-recheck-existing"
                onClick={() => executeDispatch('recheck-existing')}
                className="w-full text-left p-4 rounded-xl border border-neutral-800 bg-neutral-950/50 hover:bg-neutral-800 hover:border-amber-500/50 transition-all cursor-pointer group flex gap-4 items-start"
              >
                <div className="p-2.5 bg-emerald-500/10 text-emerald-400 rounded-lg group-hover:scale-110 transition-transform">
                  <Search className="w-5 h-5" />
                </div>
                <div>
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-bold text-neutral-200 group-hover:text-amber-400 transition-colors">AI Одит на съществуващи записи</h4>
                    <span className="text-[11px] font-semibold text-emerald-400 bg-emerald-950 px-2 py-0.5 rounded border border-emerald-800">
                      {auditDays === '0' || !auditDays ? 'неограничено' : `${auditDays} дни`}
                    </span>
                  </div>
                  <p className="text-xs text-neutral-400 mt-1">
                    Проверява вече записаните филми за грешни съвпадения и ги коригира ({auditDays === '0' || !auditDays ? 'неограничено назад' : `за последните ${auditDays} дни`}).
                  </p>
                </div>
              </button>

              <button
                type="button"
                data-testid="action-btn-reparse-unfound"
                onClick={() => executeDispatch('reparse-unfound')}
                className="w-full text-left p-4 rounded-xl border border-neutral-800 bg-neutral-950/50 hover:bg-neutral-800 hover:border-amber-500/50 transition-all cursor-pointer group flex gap-4 items-start"
              >
                <div className="p-2.5 bg-purple-500/10 text-purple-400 rounded-lg group-hover:scale-110 transition-transform">
                  <Sparkles className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-neutral-200 group-hover:text-amber-400 transition-colors">AI Повторно разпознаване</h4>
                  <p className="text-xs text-neutral-400 mt-1">Извършва повторен опит за разпознаване на нерешените торенти от логовете.</p>
                </div>
              </button>

              <button
                type="button"
                data-testid="action-btn-all"
                onClick={() => executeDispatch('all')}
                className="w-full text-left p-4 rounded-xl border border-neutral-800 bg-neutral-950/50 hover:bg-neutral-800 hover:border-amber-500/50 transition-all cursor-pointer group flex gap-4 items-start"
              >
                <div className="p-2.5 bg-amber-500/10 text-amber-400 rounded-lg group-hover:scale-110 transition-transform">
                  <RefreshCw className="w-5 h-5" />
                </div>
                <div>
                  <h4 className="text-sm font-bold text-neutral-200 group-hover:text-amber-400 transition-colors">Пълен цикъл</h4>
                  <p className="text-xs text-neutral-400 mt-1">Изпълнява последователно RSS сканиране, AI Одит и AI разпознаване.</p>
                </div>
              </button>
            </div>
            
            <div className="px-6 py-4 border-t border-neutral-800 bg-neutral-950/60 flex flex-wrap justify-between items-center gap-3">
               <div className="flex items-center gap-4">
                 <div className="flex items-center gap-2">
                   <input
                      type="checkbox"
                      id="actions_dry_run_checkbox"
                      checked={dryRun}
                      onChange={(e) => setDryRun(e.target.checked)}
                      className="w-4 h-4 rounded border-neutral-700 bg-neutral-950 text-amber-500 focus:ring-amber-500 cursor-pointer"
                    />
                    <label htmlFor="actions_dry_run_checkbox" className="text-xs text-neutral-300 cursor-pointer select-none">
                      Тестово (<code className="text-amber-400">--dry-run</code>)
                    </label>
                 </div>
                 <div className="flex items-center gap-1.5 border-l border-neutral-800 pl-3">
                   <label htmlFor="actions_audit_days_select" className="text-xs text-neutral-400 select-none">
                     Одит дни:
                   </label>
                   <select
                     id="actions_audit_days_select"
                     value={auditDays}
                     onChange={(e) => {
                       const val = e.target.value;
                       setAuditDays(val);
                       localStorage.setItem(STORAGE_KEYS.AUDIT_DAYS, val);
                     }}
                     className="px-2 py-1 bg-neutral-950 border border-neutral-800 rounded text-xs text-amber-400 focus:outline-none cursor-pointer"
                   >
                     <option value="0">0 (Неограничено)</option>
                     <option value="1">1 ден</option>
                     <option value="2">2 дни</option>
                     <option value="3">3 дни</option>
                     <option value="7">7 дни</option>
                     <option value="14">14 дни</option>
                     <option value="30">30 дни</option>
                   </select>
                 </div>
               </div>
               <button
                 type="button"
                 onClick={() => setIsActionsOpen(false)}
                 className="px-4 py-2 text-sm font-medium text-neutral-300 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors cursor-pointer"
               >
                 Затвори
               </button>
            </div>
          </div>
        </div>
      )}

      {/* Settings / Configuration Modal */}
      {isSettingsOpen && (
        <div
          data-testid="scanner-modal-backdrop"
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-in fade-in duration-200"
        >
          <div
            data-testid="scanner-modal"
            className="w-full max-w-lg bg-neutral-900 border border-neutral-800 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]"
          >
            {/* Modal Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-neutral-800 bg-neutral-950/60">
              <div className="flex items-center gap-2.5">
                <div className="w-8 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                  <Settings className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-neutral-100">Настройки за Сканиране</h3>
                  <p className="text-xs text-neutral-400">GitHub Actions Configuration</p>
                </div>
              </div>
              <button
                onClick={() => setIsSettingsOpen(false)}
                data-testid="close-modal-button"
                className="w-8 h-8 rounded-lg text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 flex items-center justify-center transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body / Form */}
            <form onSubmit={(e) => { e.preventDefault(); handleSaveOnly(); }} className="p-6 space-y-4 overflow-y-auto">
              <p className="text-xs text-neutral-300 leading-relaxed bg-neutral-950/80 p-3.5 rounded-xl border border-neutral-800">
                Запазените данни се съхраняват сигурно във вашия браузър (localStorage).
                Алтернативно, можете да ги въведете в <code className="text-amber-400">.env</code> файла (<code className="text-amber-400">VITE_GITHUB_PAT</code>).
              </p>

              {/* Status Alert in Modal */}
              {toastMessage.type && (
                <div
                  data-testid="scanner-status-message-modal"
                  className={`p-4 rounded-xl text-sm border flex flex-col gap-2 ${
                    toastMessage.type === 'success'
                      ? 'bg-emerald-950/60 border-emerald-800 text-emerald-200'
                      : 'bg-red-950/60 border-red-800 text-red-200'
                  }`}
                >
                  <div className="flex items-start gap-2.5">
                    {toastMessage.type === 'success' ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
                    ) : (
                      <AlertCircle className="w-5 h-5 text-red-400 shrink-0 mt-0.5" />
                    )}
                    <span className="leading-snug">{toastMessage.text}</span>
                  </div>
                </div>
              )}

              {/* SECTION: Scan Configuration */}
              <div className="p-3.5 bg-neutral-900/80 border border-neutral-800 rounded-xl space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-amber-400">
                  Основни Настройки
                </h4>

                {/* Force Scan Days Selector */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-xs font-semibold text-neutral-300">
                      Форсирано сканиране на RSS (дни назад)
                    </label>
                  </div>
                  <select
                    value={forceDays}
                    onChange={(e) => setForceDays(e.target.value)}
                    data-testid="select-force-days"
                    className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-sm text-neutral-100 focus:outline-none focus:border-amber-500"
                  >
                    <option value="0">0 (Стандартно — само нови публикувани торенти)</option>
                    <option value="1">1 ден назад (прераглежда & парсва наново)</option>
                    <option value="2">2 дни назад (прераглежда & парсва наново)</option>
                    <option value="3">3 дни назад</option>
                    <option value="7">7 дни назад</option>
                  </select>
                  <p className="text-[11px] text-neutral-400 mt-1">
                    Приложимо само при изпълнение на RSS сканиране или Пълен цикъл.
                  </p>
                </div>

                {/* Audit Days Selector */}
                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block text-xs font-semibold text-neutral-300">
                      Одит на съществуващи записи (дни назад)
                    </label>
                  </div>
                  <select
                    value={auditDays}
                    onChange={(e) => setAuditDays(e.target.value)}
                    data-testid="select-audit-days"
                    className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-sm text-neutral-100 focus:outline-none focus:border-amber-500"
                  >
                    <option value="0">0 (Неограничено — проверка на всички записи)</option>
                    <option value="1">1 ден назад (проверка за последния 1 ден)</option>
                    <option value="2">2 дни назад</option>
                    <option value="3">3 дни назад</option>
                    <option value="7">7 дни назад</option>
                    <option value="14">14 дни назад</option>
                    <option value="30">30 дни назад</option>
                  </select>
                  <p className="text-[11px] text-neutral-400 mt-1">
                    Приложимо при "AI Одит на съществуващи записи" и "Пълен цикъл". При 0 се проверяват всички.
                  </p>
                </div>

                {/* Dry Run Checkbox */}
                <div className="flex items-center gap-2 pt-1 border-t border-neutral-800/60">
                  <input
                    type="checkbox"
                    id="dry_run_checkbox"
                    checked={dryRun}
                    onChange={(e) => setDryRun(e.target.checked)}
                    data-testid="checkbox-dry-run"
                    className="w-4 h-4 rounded border-neutral-700 bg-neutral-950 text-amber-500 focus:ring-amber-500 cursor-pointer"
                  />
                  <label htmlFor="dry_run_checkbox" className="text-xs text-neutral-300 cursor-pointer select-none">
                    По подразбиране използвай тестово изпълнение (<code className="text-amber-400">--dry-run</code>)
                  </label>
                </div>
              </div>

              {/* SECTION: Credentials & GitHub Settings */}
              <div className="p-3.5 bg-neutral-900/40 border border-neutral-800/80 rounded-xl space-y-3">
                <h4 className="text-xs font-bold uppercase tracking-wider text-neutral-400">
                  GitHub Actions Данни & Ключове
                </h4>

                <div className="grid grid-cols-2 gap-3">
                  {/* GitHub Owner */}
                  <div>
                    <label className="block text-xs font-semibold text-neutral-300 mb-1">
                      GitHub Owner <span className="text-amber-400">*</span>
                    </label>
                    <input
                      type="text"
                      value={owner}
                      onChange={(e) => setOwner(e.target.value)}
                      placeholder="напр. vdublikov"
                      required
                      data-testid="input-github-owner"
                      className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-sm text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
                    />
                  </div>

                  {/* GitHub Repo */}
                  <div>
                    <label className="block text-xs font-semibold text-neutral-300 mb-1">
                      Репозитория (Repo) <span className="text-amber-400">*</span>
                    </label>
                    <input
                      type="text"
                      value={repo}
                      onChange={(e) => setRepo(e.target.value)}
                      placeholder="movies-feed"
                      required
                      data-testid="input-github-repo"
                      className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-sm text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
                    />
                  </div>
                </div>

                {/* GitHub Token */}
                <div>
                  <label className="block text-xs font-semibold text-neutral-300 mb-1">
                    GitHub PAT <span className="text-amber-400">*</span>
                  </label>
                  <input
                    type="password"
                    value={pat}
                    onChange={(e) => setPat(e.target.value)}
                    placeholder="ghp_xxxxxxxxxxxx или github_pat_xxxx"
                    required
                    data-testid="input-github-pat"
                    className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-sm text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500 font-mono"
                  />
                  <p className="text-[11px] text-neutral-400 mt-1 flex items-center gap-1">
                    <span>Token с право <strong>Actions (write)</strong>.</span>
                    <a
                      href="https://github.com/settings/tokens?type=beta"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-amber-400 hover:underline inline-flex items-center gap-0.5"
                    >
                      Генерирай PAT <ExternalLink className="w-3 h-3" />
                    </a>
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-3 pt-1 border-t border-neutral-800/80">
                  {/* Workflow File */}
                  <div>
                    <label className="block text-xs font-semibold text-neutral-400 mb-1">
                      Workflow файл
                    </label>
                    <input
                      type="text"
                      value={workflow}
                      onChange={(e) => setWorkflow(e.target.value)}
                      placeholder="scanner.yml"
                      data-testid="input-github-workflow"
                      className="w-full px-3 py-1.5 bg-neutral-950 border border-neutral-800 rounded-lg text-xs text-neutral-300 font-mono focus:outline-none focus:border-amber-500"
                    />
                  </div>

                  {/* Branch / Ref */}
                  <div>
                    <label className="block text-xs font-semibold text-neutral-400 mb-1">
                      Клон (Branch / Ref)
                    </label>
                    <input
                      type="text"
                      value={ref}
                      onChange={(e) => setRef(e.target.value)}
                      placeholder="main"
                      data-testid="input-github-ref"
                      className="w-full px-3 py-1.5 bg-neutral-950 border border-neutral-800 rounded-lg text-xs text-neutral-300 font-mono focus:outline-none focus:border-amber-500"
                    />
                  </div>
                </div>

                {/* OMDb API Key */}
                <div>
                  <label className="block text-xs font-semibold text-neutral-300 mb-1">
                    OMDb API Key (за ръчен рефреш)
                  </label>
                  <input
                    type="password"
                    value={omdbApiKey}
                    onChange={(e) => setOmdbApiKey(e.target.value)}
                    placeholder="напр. xxxxxxxx"
                    data-testid="input-omdb-api-key"
                    className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-sm text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500 font-mono"
                  />
                </div>
              </div>

              {/* Footer Actions */}
              <div className="flex flex-wrap items-center justify-end gap-3 pt-4 border-t border-neutral-800">
                <button
                  type="button"
                  onClick={() => setIsSettingsOpen(false)}
                  data-testid="cancel-settings-button"
                  className="px-4 py-2 text-sm font-medium text-neutral-300 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors cursor-pointer"
                >
                  Отказ
                </button>
                <button
                  type="submit"
                  data-testid="save-settings-button"
                  className="inline-flex items-center gap-2 min-h-[40px] px-5 py-2 text-sm font-semibold text-neutral-950 bg-amber-500 hover:bg-amber-400 rounded-lg transition-colors cursor-pointer"
                >
                  Запази настройките
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

