import React, { useState, useEffect } from 'react';
import { Play, Settings, CheckCircle2, AlertCircle, ExternalLink, X, Loader2, RefreshCw } from 'lucide-react';

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
  OMDB_API_KEY: 'movies_feed_omdb_api_key',
};

export const TriggerScannerModal: React.FC<TriggerScannerModalProps> = ({
  buttonClassName,
  buttonVariant = 'header',
}) => {
  const [isOpen, setIsOpen] = useState<boolean>(false);
  const [owner, setOwner] = useState<string>('');
  const [repo, setRepo] = useState<string>('movies-feed');
  const [pat, setPat] = useState<string>('');
  const [workflow, setWorkflow] = useState<string>('scanner.yml');
  const [ref, setRef] = useState<string>('main');
  const [dryRun, setDryRun] = useState<boolean>(false);
  const [forceDays, setForceDays] = useState<string>('0');
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
    setOmdbApiKey(savedOmdbApiKey);
  }, []);

  const handleSaveSettings = () => {
    localStorage.setItem(STORAGE_KEYS.OWNER, owner.trim());
    localStorage.setItem(STORAGE_KEYS.REPO, repo.trim());
    localStorage.setItem(STORAGE_KEYS.PAT, pat.trim());
    localStorage.setItem(STORAGE_KEYS.WORKFLOW, workflow.trim());
    localStorage.setItem(STORAGE_KEYS.REF, ref.trim());
    localStorage.setItem(STORAGE_KEYS.FORCE_DAYS, forceDays.trim());
    localStorage.setItem(STORAGE_KEYS.OMDB_API_KEY, omdbApiKey.trim());
  };

  const handleSaveOnly = () => {
    handleSaveSettings();
    setToastMessage({
      type: 'success',
      text: 'Настройките и OMDb API ключът са запазени успешно в браузъра!',
    });
  };

  const executeDispatch = async (
    targetOwner: string,
    targetRepo: string,
    targetPat: string,
    targetWorkflow: string,
    targetRef: string,
    isDryRun: boolean,
    targetForceDays: string
  ) => {
    setIsSubmitting(true);
    setToastMessage({ type: null, text: '' });

    try {
      const url = `https://api.github.com/repos/${targetOwner}/${targetRepo}/actions/workflows/${targetWorkflow}/dispatches`;
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          Accept: 'application/vnd.github+json',
          Authorization: `Bearer ${targetPat}`,
          'X-GitHub-Api-Version': '2022-11-28',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          ref: targetRef,
          inputs: {
            dry_run: isDryRun,
            force_days: targetForceDays,
          },
        }),
      });

      if (response.status === 204 || response.ok) {
        setToastMessage({
          type: 'success',
          text: `Сканирането е стартирано успешно в GitHub Actions!`,
          actionUrl: `https://github.com/${targetOwner}/${targetRepo}/actions`,
        });
        setIsOpen(false);
      } else if (response.status === 401 || response.status === 403) {
        setToastMessage({
          type: 'error',
          text: `Грешка при автентикация (${response.status}). Проверете дали вашият GitHub token има 'actions:write' права.`,
        });
        setIsOpen(true);
      } else if (response.status === 404) {
        setToastMessage({
          type: 'error',
          text: `Репозиторията ${targetOwner}/${targetRepo} или workflow файлът (${targetWorkflow}) не бяха намерени (404).`,
        });
        setIsOpen(true);
      } else {
        const errData = await response.json().catch(() => ({}));
        setToastMessage({
          type: 'error',
          text: `Грешка (${response.status}): ${errData.message || response.statusText}`,
        });
        setIsOpen(true);
      }
    } catch (err) {
      setToastMessage({
        type: 'error',
        text: `Мрежова грешка: ${err instanceof Error ? err.message : 'Грешка при връзка с GitHub API.'}`,
      });
      setIsOpen(true);
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleQuickTrigger = () => {
    const trimmedOwner = owner.trim();
    const trimmedRepo = repo.trim();
    const trimmedPat = pat.trim();

    // If credentials missing, open settings modal
    if (!trimmedOwner || !trimmedRepo || !trimmedPat) {
      setIsOpen(true);
      return;
    }

    // Direct 1-click execution!
    executeDispatch(
      trimmedOwner,
      trimmedRepo,
      trimmedPat,
      workflow.trim() || 'scanner.yml',
      ref.trim() || 'main',
      dryRun,
      forceDays
    );
  };

  const handleFormSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    const trimmedOwner = owner.trim();
    const trimmedRepo = repo.trim();
    const trimmedPat = pat.trim();

    if (!trimmedOwner || !trimmedRepo) {
      setToastMessage({
        type: 'error',
        text: 'Моля, въведете GitHub потребител (Owner) и име на репозитория (Repository).',
      });
      return;
    }

    if (!trimmedPat) {
      setToastMessage({
        type: 'error',
        text: 'Моля, въведете GitHub Personal Access Token (PAT) с права "actions:write".',
      });
      return;
    }

    handleSaveSettings();
    executeDispatch(
      trimmedOwner,
      trimmedRepo,
      trimmedPat,
      workflow.trim() || 'scanner.yml',
      ref.trim() || 'main',
      dryRun,
      forceDays
    );
  };

  const defaultBtnClass =
    buttonVariant === 'header'
      ? 'inline-flex items-center gap-2 min-h-[40px] px-3.5 py-2 text-sm font-semibold text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-xl hover:bg-amber-500/20 hover:border-amber-500/50 transition-all cursor-pointer shadow-sm active:scale-[0.98] disabled:opacity-50'
      : 'inline-flex items-center gap-2 min-h-[44px] px-4 py-2.5 text-sm font-semibold text-neutral-950 bg-amber-500 hover:bg-amber-400 rounded-lg transition-colors cursor-pointer shadow-sm active:scale-[0.98] disabled:opacity-50';

  return (
    <div className="relative inline-flex items-center gap-2">
      {/* 1-Click Trigger Button */}
      <button
        onClick={handleQuickTrigger}
        disabled={isSubmitting}
        type="button"
        data-testid="trigger-scanner-button"
        className={buttonClassName || defaultBtnClass}
        title="1-click стартер за RSS сканирането"
      >
        {isSubmitting ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
            <span>Стартиране...</span>
          </>
        ) : (
          <>
            <Play className="w-4 h-4 fill-current text-amber-400" />
            <span>Стартирай сканиране</span>
          </>
        )}
      </button>

      {/* Settings Gear Button */}
      <button
        onClick={() => setIsOpen(true)}
        type="button"
        data-testid="scanner-settings-button"
        className="w-10 h-10 rounded-xl border border-neutral-800 bg-neutral-900 text-neutral-400 hover:text-neutral-200 hover:border-neutral-700 flex items-center justify-center transition-colors cursor-pointer"
        title="Настройки за GitHub API / Token"
      >
        <Settings className="w-4 h-4" />
      </button>

      {/* Toast Banner Feedback */}
      {toastMessage.type && !isOpen && (
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

      {/* Settings / Configuration Modal */}
      {isOpen && (
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
                  <RefreshCw className="w-4 h-4" />
                </div>
                <div>
                  <h3 className="text-base font-bold text-neutral-100">Настройки за RSS Сканиране</h3>
                  <p className="text-xs text-neutral-400">GitHub Actions Workflow Dispatches</p>
                </div>
              </div>
              <button
                onClick={() => setIsOpen(false)}
                data-testid="close-modal-button"
                className="w-8 h-8 rounded-lg text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800 flex items-center justify-center transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Modal Body / Form */}
            <form onSubmit={handleFormSubmit} className="p-6 space-y-4 overflow-y-auto">
              <p className="text-xs text-neutral-300 leading-relaxed bg-neutral-950/80 p-3.5 rounded-xl border border-neutral-800">
                Запазените данни се съхраняват сигурно във вашия браузър (localStorage) и с тях бутонът <strong>"Стартирай сканиране"</strong> работи с <strong>1 клик</strong>.
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

                  {toastMessage.actionUrl && (
                    <a
                      href={toastMessage.actionUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1.5 self-start text-xs font-semibold text-emerald-300 hover:text-emerald-100 underline mt-1"
                    >
                      <span>Виж прогреса в GitHub Actions</span>
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  )}
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                {/* GitHub Owner */}
                <div>
                  <label className="block text-xs font-semibold text-neutral-300 mb-1">
                    GitHub Owner / Потребител <span className="text-amber-400">*</span>
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
                  GitHub Personal Access Token (PAT) <span className="text-amber-400">*</span>
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
                  <span>Необходим е token с право <strong>Actions (write)</strong>.</span>
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

              {/* Force Scan Days Selector */}
              <div>
                <label className="block text-xs font-semibold text-neutral-300 mb-1">
                  Форсирано сканиране (дни назад)
                </label>
                <select
                  value={forceDays}
                  onChange={(e) => setForceDays(e.target.value)}
                  data-testid="select-force-days"
                  className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-sm text-neutral-100 focus:outline-none focus:border-amber-500"
                >
                  <option value="0">0 (Стандартно - нови записи)</option>
                  <option value="1">1 ден назад (презаписва & парсва наново)</option>
                  <option value="2">2 дни назад (презаписва & парсва наново)</option>
                  <option value="3">3 дни назад</option>
                  <option value="7">7 дни назад</option>
                </select>
                <p className="text-[11px] text-neutral-400 mt-1">
                  Преразглежда и парсва филмите публикувани през последните N дни (ползва OMDb кеш при възможност).
                </p>
              </div>

              {/* Dry Run Checkbox */}
              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="dry_run_checkbox"
                  checked={dryRun}
                  onChange={(e) => setDryRun(e.target.checked)}
                  data-testid="checkbox-dry-run"
                  className="w-4 h-4 rounded border-neutral-700 bg-neutral-950 text-amber-500 focus:ring-amber-500 cursor-pointer"
                />
                <label htmlFor="dry_run_checkbox" className="text-xs text-neutral-300 cursor-pointer select-none">
                  Тестово парсване (<code className="text-amber-400">--dry-run</code> - без запис в базата данни)
                </label>
              </div>

              {/* Footer Actions */}
              <div className="flex flex-wrap items-center justify-end gap-3 pt-4 border-t border-neutral-800">
                <button
                  type="button"
                  onClick={() => setIsOpen(false)}
                  data-testid="cancel-trigger-button"
                  className="px-4 py-2 text-sm font-medium text-neutral-300 bg-neutral-800 border border-neutral-700 rounded-lg hover:bg-neutral-700 transition-colors cursor-pointer"
                >
                  Затвори
                </button>
                <button
                  type="button"
                  onClick={handleSaveOnly}
                  data-testid="save-only-settings-button"
                  className="px-4 py-2 text-sm font-medium text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-lg hover:bg-amber-500/20 transition-colors cursor-pointer"
                >
                  Запази настройките
                </button>
                <button
                  type="submit"
                  disabled={isSubmitting}
                  data-testid="submit-trigger-button"
                  className="inline-flex items-center gap-2 min-h-[40px] px-5 py-2 text-sm font-semibold text-neutral-950 bg-amber-500 hover:bg-amber-400 rounded-lg transition-colors cursor-pointer disabled:opacity-50"
                >
                  {isSubmitting ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin text-neutral-950" />
                      <span>Стартиране...</span>
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 fill-current" />
                      <span>Запази и Стартирай</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
