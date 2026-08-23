/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useState, useEffect } from 'react';
import { GlobalSettings, DEFAULT_SETTINGS, RssFeedConfig } from '../domain/settings';
import { firestoreSettingsAdapter } from '../adapters/firestoreSettingsAdapter';
import {
  Save,
  RotateCcw,
  Plus,
  Trash2,
  Check,
  AlertTriangle,
  Loader2,
  Globe,
  Tag,
  Film,
  Rss,
  Info,
  Key,
  Github
} from 'lucide-react';

export const SettingsView: React.FC = () => {
  const [settings, setSettings] = useState<GlobalSettings | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isSaving, setIsSaving] = useState<boolean>(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  // Client / Scanner credentials stored in localStorage
  const [omdbApiKey, setOmdbApiKey] = useState('');
  const [ghOwner, setGhOwner] = useState('');
  const [ghRepo, setGhRepo] = useState('movies-feed');
  const [ghPat, setGhPat] = useState('');

  // Input states for adding items
  const [newFeedName, setNewFeedName] = useState('');
  const [newFeedUrl, setNewFeedUrl] = useState('');
  const [newFeedType, setNewFeedType] = useState<'movie' | 'series'>('movie');
  const [newGenre, setNewGenre] = useState('');
  const [newCountry, setNewCountry] = useState('');

  useEffect(() => {
    // Load local storage keys
    const savedOmdb = localStorage.getItem('movies_feed_omdb_api_key') || import.meta.env.VITE_OMDB_API_KEY || import.meta.env.OMDB_API_KEY || '';
    const savedOwner = localStorage.getItem('movies_feed_gh_owner') || import.meta.env.VITE_GITHUB_OWNER || '';
    const savedRepo = localStorage.getItem('movies_feed_gh_repo') || import.meta.env.VITE_GITHUB_REPO || 'movies-feed';
    const savedPat = localStorage.getItem('movies_feed_gh_pat') || import.meta.env.VITE_GITHUB_PAT || '';

    setOmdbApiKey(savedOmdb);
    setGhOwner(savedOwner);
    setGhRepo(savedRepo);
    setGhPat(savedPat);

    async function loadSettings() {
      setIsLoading(true);
      try {
        const data = await firestoreSettingsAdapter.getSettings();
        setSettings(data);
      } catch (err) {
        console.error('Error loading settings:', err);
        setSettings(DEFAULT_SETTINGS);
      } finally {
        setIsLoading(false);
      }
    }
    loadSettings();
  }, []);

  const handleSave = async () => {
    // Save client localStorage settings
    localStorage.setItem('movies_feed_omdb_api_key', omdbApiKey.trim());
    localStorage.setItem('movies_feed_gh_owner', ghOwner.trim());
    localStorage.setItem('movies_feed_gh_repo', ghRepo.trim());
    localStorage.setItem('movies_feed_gh_pat', ghPat.trim());

    if (!settings) return;
    setIsSaving(true);
    setMessage(null);
    try {
      await firestoreSettingsAdapter.saveSettings(settings);
      setMessage({ type: 'success', text: 'Настройките и API ключовете бяха запазени успешно!' });
      setTimeout(() => setMessage(null), 5000);
    } catch (err) {
      console.error('Error saving settings:', err);
      setMessage({ type: 'error', text: 'Грешка при запис на настройките в Firestore. Моля опитайте отново.' });
    } finally {
      setIsSaving(false);
    }
  };

  const handleResetDefaults = () => {
    if (window.confirm('Сигурни ли сте, че искате да върнете фабричните настройки?')) {
      setSettings({ ...DEFAULT_SETTINGS });
      setMessage({ type: 'success', text: 'Настройките са нулирани до фабричните стойности. Не забравяйте да натиснете "Запази Настройките".' });
    }
  };

  const handleAddFeed = (e: React.FormEvent) => {
    e.preventDefault();
    if (!settings) return;
    const name = newFeedName.trim();
    const url = newFeedUrl.trim();
    if (!name || !url) return;

    if (settings.rssFeeds[name]) {
      alert('Вече съществува RSS фийд с това име.');
      return;
    }

    const updatedFeeds = {
      ...settings.rssFeeds,
      [name]: { url, type: newFeedType } as RssFeedConfig
    };

    setSettings({ ...settings, rssFeeds: updatedFeeds });
    setNewFeedName('');
    setNewFeedUrl('');
  };

  const handleRemoveFeed = (name: string) => {
    if (!settings) return;
    const updatedFeeds = { ...settings.rssFeeds };
    delete updatedFeeds[name];
    setSettings({ ...settings, rssFeeds: updatedFeeds });
  };

  const handleAddGenre = (e: React.FormEvent) => {
    e.preventDefault();
    if (!settings) return;
    const genre = newGenre.trim();
    if (!genre) return;

    if (settings.excludedGenres.some(g => g.toLowerCase() === genre.toLowerCase())) {
      setNewGenre('');
      return;
    }

    setSettings({
      ...settings,
      excludedGenres: [...settings.excludedGenres, genre]
    });
    setNewGenre('');
  };

  const handleRemoveGenre = (genre: string) => {
    if (!settings) return;
    setSettings({
      ...settings,
      excludedGenres: settings.excludedGenres.filter(g => g !== genre)
    });
  };

  const handleAddCountry = (e: React.FormEvent) => {
    e.preventDefault();
    if (!settings) return;
    const country = newCountry.trim();
    if (!country) return;

    if (settings.excludedCountries.some(c => c.toLowerCase() === country.toLowerCase())) {
      setNewCountry('');
      return;
    }

    setSettings({
      ...settings,
      excludedCountries: [...settings.excludedCountries, country]
    });
    setNewCountry('');
  };

  const handleRemoveCountry = (country: string) => {
    if (!settings) return;
    setSettings({
      ...settings,
      excludedCountries: settings.excludedCountries.filter(c => c !== country)
    });
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-center">
        <Loader2 className="w-8 h-8 animate-spin text-amber-500 mb-3" />
        <p className="text-sm text-neutral-400">Зареждане на настройките от базата данни...</p>
      </div>
    );
  }

  if (!settings) return null;

  return (
    <div className="space-y-8" data-testid="settings-panel">
      {/* Settings Notification Banner */}
      {message && (
        <div
          data-testid="settings-alert-message"
          className={`p-4 rounded-xl text-sm border flex items-center justify-between gap-3 animate-in fade-in duration-200 ${
            message.type === 'success'
              ? 'bg-emerald-950/60 border-emerald-800 text-emerald-200'
              : 'bg-red-950/60 border-red-800 text-red-200'
          }`}
        >
          <div className="flex items-center gap-2.5">
            {message.type === 'success' ? (
              <Check className="w-5 h-5 text-emerald-400 shrink-0" />
            ) : (
              <AlertTriangle className="w-5 h-5 text-red-400 shrink-0" />
            )}
            <span className="font-medium">{message.text}</span>
          </div>
        </div>
      )}

      {/* Main Settings Header Notice */}
      <div className="bg-neutral-950 border border-neutral-800/80 p-4 rounded-xl flex items-start gap-3 text-xs text-neutral-400">
        <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
        <div className="space-y-1">
          <p className="font-semibold text-neutral-200">Бележка за синхронизацията:</p>
          <p>
            Промените в <strong>RSS фийдовете</strong>, <strong>филтрирането на жанрове</strong> и <strong>филтрирането на държави</strong> се прилагат директно по време на следващото сканиране на RSS емисиите.
            Промените в <strong>минималните рейтинги</strong> се ползват като стойности по подразбиране при зареждането на каталога в браузъра.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        {/* Left column: RSS Feeds Management (span 2) */}
        <div className="lg:col-span-2 space-y-6">
          {/* RSS Feeds Panel */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 pb-2 border-b border-neutral-800">
              <Rss className="w-5 h-5 text-amber-500" />
              <h2 className="text-base font-bold text-neutral-100">RSS Feeds (Емисии)</h2>
            </div>

            {/* List / Table of feeds */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs text-neutral-300 border-collapse">
                <thead>
                  <tr className="border-b border-neutral-800 text-neutral-500 font-semibold uppercase tracking-wider">
                    <th className="py-2.5 px-3">Име</th>
                    <th className="py-2.5 px-3">Тип</th>
                    <th className="py-2.5 px-3">URL</th>
                    <th className="py-2.5 px-3 text-right">Действия</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-neutral-800/50">
                  {(Object.entries(settings.rssFeeds) as [string, RssFeedConfig][]).map(([name, config]) => (
                    <tr key={name} className="hover:bg-neutral-800/30 transition-colors" data-testid={`feed-row-${name}`}>
                      <td className="py-3 px-3 font-semibold text-neutral-200">{name}</td>
                      <td className="py-3 px-3">
                        <span className={`inline-flex items-center px-2 py-0.5 rounded text-[10px] font-semibold uppercase ${
                          config.type === 'movie'
                            ? 'bg-blue-950/60 text-blue-400 border border-blue-900/50'
                            : 'bg-purple-950/60 text-purple-400 border border-purple-900/50'
                        }`}>
                          {config.type === 'movie' ? 'Филми' : 'Сериали'}
                        </span>
                      </td>
                      <td className="py-3 px-3 font-mono text-neutral-400 truncate max-w-[200px] sm:max-w-[320px]" title={config.url}>
                        {config.url}
                      </td>
                      <td className="py-3 px-3 text-right">
                        <button
                          type="button"
                          onClick={() => handleRemoveFeed(name)}
                          data-testid={`remove-feed-${name}`}
                          className="p-1.5 rounded-lg text-neutral-500 hover:text-red-400 hover:bg-neutral-850 transition-colors cursor-pointer"
                          title="Изтриване на фийд"
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </td>
                    </tr>
                  ))}
                  {Object.keys(settings.rssFeeds).length === 0 && (
                    <tr>
                      <td colSpan={4} className="py-6 text-center text-neutral-500">
                        Няма конфигурирани RSS емисии.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Add Feed Form */}
            <form onSubmit={handleAddFeed} className="bg-neutral-950 p-4 rounded-lg border border-neutral-800/80 space-y-3" data-testid="add-feed-form">
              <h3 className="text-xs font-bold text-neutral-300 uppercase tracking-wider">Добави Нов RSS Фийд</h3>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="space-y-1">
                  <label className="block text-[11px] font-semibold text-neutral-400">Име на емисията</label>
                  <input
                    type="text"
                    value={newFeedName}
                    onChange={(e) => setNewFeedName(e.target.value)}
                    placeholder="напр. Movies Ultra HD"
                    className="w-full px-3 py-2 bg-neutral-900 border border-neutral-800 rounded-lg text-xs text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
                    required
                  />
                </div>
                <div className="space-y-1 sm:col-span-2">
                  <label className="block text-[11px] font-semibold text-neutral-400">Atom/RSS URL адрес</label>
                  <input
                    type="url"
                    value={newFeedUrl}
                    onChange={(e) => setNewFeedUrl(e.target.value)}
                    placeholder="https://feed.rutracker.cc/atom/f/..."
                    className="w-full px-3 py-2 bg-neutral-900 border border-neutral-800 rounded-lg text-xs text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500 font-mono"
                    required
                  />
                </div>
              </div>
              <div className="flex items-center justify-between pt-1">
                <div className="flex items-center gap-4">
                  <span className="text-[11px] font-semibold text-neutral-400">Тип на съдържанието:</span>
                  <label className="inline-flex items-center gap-1.5 text-xs text-neutral-300 cursor-pointer">
                    <input
                      type="radio"
                      name="feed_type"
                      checked={newFeedType === 'movie'}
                      onChange={() => setNewFeedType('movie')}
                      className="text-amber-500 focus:ring-amber-500 cursor-pointer"
                    />
                    <span>Филми</span>
                  </label>
                  <label className="inline-flex items-center gap-1.5 text-xs text-neutral-300 cursor-pointer">
                    <input
                      type="radio"
                      name="feed_type"
                      checked={newFeedType === 'series'}
                      onChange={() => setNewFeedType('series')}
                      className="text-amber-500 focus:ring-amber-500 cursor-pointer"
                    />
                    <span>Сериали</span>
                  </label>
                </div>
                <button
                  type="submit"
                  data-testid="submit-add-feed-btn"
                  className="inline-flex items-center gap-1.5 min-h-[36px] px-4 py-1.5 text-xs font-semibold text-neutral-950 bg-amber-500 hover:bg-amber-400 rounded-lg transition-colors cursor-pointer"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Добави
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* Right column: Exclusions & Threshold Defaults */}
        <div className="space-y-6">
          {/* Default Thresholds for UI filtering */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 pb-2 border-b border-neutral-800">
              <Film className="w-5 h-5 text-amber-500" />
              <h2 className="text-base font-bold text-neutral-100">Филтриране по подразбиране</h2>
            </div>
            <p className="text-[11px] text-neutral-400 leading-relaxed">
              Тези стойности се зареждат по подразбиране в интерфейса при първото отваряне на каталога.
            </p>

            <div className="space-y-4 pt-2">
              {/* Min Movie Rating */}
              <div className="space-y-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-neutral-300 font-semibold">🎬 Мин. Филм Рейтинг</span>
                  <span className="font-mono font-bold text-amber-400">
                    {settings.minMovieRating > 0 ? settings.minMovieRating.toFixed(1) : 'Няма'}
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="10"
                  step="0.1"
                  value={settings.minMovieRating}
                  onChange={(e) =>
                    setSettings({ ...settings, minMovieRating: parseFloat(e.target.value) })
                  }
                  className="w-full h-1.5 bg-neutral-850 rounded-lg appearance-none cursor-pointer accent-amber-500"
                />
              </div>

              {/* Min Series Rating */}
              <div className="space-y-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-neutral-300 font-semibold">📺 Мин. Сериал Рейтинг</span>
                  <span className="font-mono font-bold text-amber-400">
                    {settings.minSeriesRating > 0 ? settings.minSeriesRating.toFixed(1) : 'Няма'}
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="10"
                  step="0.1"
                  value={settings.minSeriesRating}
                  onChange={(e) =>
                    setSettings({ ...settings, minSeriesRating: parseFloat(e.target.value) })
                  }
                  className="w-full h-1.5 bg-neutral-850 rounded-lg appearance-none cursor-pointer accent-amber-500"
                />
              </div>

              {/* Min IMDb Votes */}
              <div className="space-y-1.5">
                <div className="flex justify-between items-center text-xs">
                  <span className="text-neutral-300 font-semibold">👥 Мин. IMDb Гласове</span>
                  <span className="font-mono font-bold text-amber-400">
                    {settings.minImdbVotes > 0 ? settings.minImdbVotes.toLocaleString() : 'Няма'}
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max="20000"
                  step="250"
                  value={settings.minImdbVotes}
                  onChange={(e) =>
                    setSettings({ ...settings, minImdbVotes: parseInt(e.target.value, 10) })
                  }
                  className="w-full h-1.5 bg-neutral-850 rounded-lg appearance-none cursor-pointer accent-amber-500"
                />
              </div>
            </div>
          </div>

          {/* Excluded Genres */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 pb-2 border-b border-neutral-800">
              <Tag className="w-5 h-5 text-amber-500" />
              <h2 className="text-base font-bold text-neutral-100">Изключени Жанрове</h2>
            </div>
            <p className="text-[11px] text-neutral-400">
              Филми и сериали, които съдържат някой от тези жанрове, ще бъдат автоматично отхвърляни по време на сканирането.
            </p>

            <div className="flex flex-wrap gap-1.5 min-h-12 p-2 bg-neutral-950 rounded-lg border border-neutral-850">
              {settings.excludedGenres.map((genre) => (
                <span
                  key={genre}
                  data-testid={`genre-tag-${genre}`}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-red-950/40 text-red-300 border border-red-900/30"
                >
                  <span>{genre}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveGenre(genre)}
                    className="p-0.5 text-neutral-400 hover:text-red-200 cursor-pointer"
                    title="Премахване на жанр"
                  >
                    <Plus className="w-3 h-3 rotate-45" />
                  </button>
                </span>
              ))}
              {settings.excludedGenres.length === 0 && (
                <span className="text-neutral-600 text-xs my-auto italic">Няма изключени жанрове</span>
              )}
            </div>

            <form onSubmit={handleAddGenre} className="flex gap-2">
              <input
                type="text"
                value={newGenre}
                onChange={(e) => setNewGenre(e.target.value)}
                placeholder="напр. Horror, Romance"
                className="flex-1 px-3 py-1.5 bg-neutral-950 border border-neutral-800 rounded-lg text-xs text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
              />
              <button
                type="submit"
                className="min-h-[32px] px-3 bg-neutral-800 border border-neutral-700 hover:bg-neutral-750 text-neutral-200 rounded-lg text-xs font-semibold cursor-pointer flex items-center justify-center"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>

          {/* Excluded Countries */}
          <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 shadow-sm space-y-4">
            <div className="flex items-center gap-2 pb-2 border-b border-neutral-800">
              <Globe className="w-5 h-5 text-amber-500" />
              <h2 className="text-base font-bold text-neutral-100">Изключени Държави</h2>
            </div>
            <p className="text-[11px] text-neutral-400">
              Ако медията е произведена единствено в тези държави, тя ще бъде автоматично отхвърлена по време на сканирането.
            </p>

            <div className="flex flex-wrap gap-1.5 min-h-12 p-2 bg-neutral-950 rounded-lg border border-neutral-850">
              {settings.excludedCountries.map((country) => (
                <span
                  key={country}
                  data-testid={`country-tag-${country}`}
                  className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg text-xs font-medium bg-red-950/40 text-red-300 border border-red-900/30"
                >
                  <span>{country}</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveCountry(country)}
                    className="p-0.5 text-neutral-400 hover:text-red-200 cursor-pointer"
                    title="Премахване на държава"
                  >
                    <Plus className="w-3 h-3 rotate-45" />
                  </button>
                </span>
              ))}
              {settings.excludedCountries.length === 0 && (
                <span className="text-neutral-600 text-xs my-auto italic">Няма изключени държави</span>
              )}
            </div>

            <form onSubmit={handleAddCountry} className="flex gap-2">
              <input
                type="text"
                value={newCountry}
                onChange={(e) => setNewCountry(e.target.value)}
                placeholder="напр. India, Turkey"
                className="flex-1 px-3 py-1.5 bg-neutral-950 border border-neutral-800 rounded-lg text-xs text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
              />
              <button
                type="submit"
                className="min-h-[32px] px-3 bg-neutral-800 border border-neutral-700 hover:bg-neutral-750 text-neutral-200 rounded-lg text-xs font-semibold cursor-pointer flex items-center justify-center"
              >
                <Plus className="w-3.5 h-3.5" />
              </button>
            </form>
          </div>
        </div>
      </div>

      {/* API Keys & Scanner Integration (LocalStorage / Client Keys) */}
      <div className="bg-neutral-900 border border-neutral-800 rounded-xl p-5 shadow-sm space-y-4">
        <div className="flex items-center gap-2 pb-2 border-b border-neutral-800">
          <Key className="w-5 h-5 text-amber-500" />
          <div>
            <h2 className="text-base font-bold text-neutral-100">API Ключове и GitHub Интеграция (Браузър / Клиентски)</h2>
            <p className="text-xs text-neutral-400 mt-0.5">
              Тези ключове се пазят сигурно във вашия браузър (<code className="text-amber-400">localStorage</code>) и се използват за ръчен рефреш и 1-click стартиране на сканиране.
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-neutral-200">
              OMDb API Key (за браузъра)
            </label>
            <input
              type="password"
              value={omdbApiKey}
              onChange={(e) => setOmdbApiKey(e.target.value)}
              placeholder="напр. 1a2b3c4d"
              data-testid="input-settings-omdb-key"
              className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-xs font-mono text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
            />
            <p className="text-[11px] text-neutral-400 leading-relaxed">
              Необходим при ръчно въвеждане или рефреш на IMDb ID в детайлите на филм. В GitHub Actions скенерът използва тайния ключ от GitHub Secrets (<code className="text-neutral-300">OMDB_API_KEY</code>).
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-neutral-200">
              GitHub Personal Access Token (PAT)
            </label>
            <input
              type="password"
              value={ghPat}
              onChange={(e) => setGhPat(e.target.value)}
              placeholder="ghp_..."
              data-testid="input-settings-gh-pat"
              className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-xs font-mono text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
            />
            <p className="text-[11px] text-neutral-400 leading-relaxed">
              Нужен само за директно стартиране на GitHub Actions сканирането от бутона в хедъра (изисква права <code className="text-neutral-300">actions:write</code>).
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-neutral-200">
              GitHub Потребител / Организация (Owner)
            </label>
            <input
              type="text"
              value={ghOwner}
              onChange={(e) => setGhOwner(e.target.value)}
              placeholder="напр. your-username"
              data-testid="input-settings-gh-owner"
              className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-xs text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
            />
          </div>

          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-neutral-200">
              GitHub Репозитория (Repository)
            </label>
            <input
              type="text"
              value={ghRepo}
              onChange={(e) => setGhRepo(e.target.value)}
              placeholder="movies-feed"
              data-testid="input-settings-gh-repo"
              className="w-full px-3 py-2 bg-neutral-950 border border-neutral-800 rounded-lg text-xs text-neutral-100 placeholder-neutral-600 focus:outline-none focus:border-amber-500"
            />
          </div>
        </div>
      </div>

      {/* Footer sticky-style save actions */}
      <div className="flex items-center justify-between pt-6 border-t border-neutral-800">
        <button
          type="button"
          onClick={handleResetDefaults}
          data-testid="reset-defaults-settings-btn"
          className="inline-flex items-center gap-2 min-h-[40px] px-4 py-2 text-sm font-semibold text-neutral-400 hover:text-neutral-200 border border-neutral-800 hover:border-neutral-700 rounded-lg transition-colors cursor-pointer"
        >
          <RotateCcw className="w-4 h-4" />
          Фабрични Настройки
        </button>

        <button
          type="button"
          onClick={handleSave}
          disabled={isSaving}
          data-testid="save-settings-btn"
          className="inline-flex items-center gap-2 min-h-[44px] px-6 py-2.5 text-sm font-semibold text-neutral-950 bg-amber-500 hover:bg-amber-400 rounded-lg transition-colors shadow-sm disabled:opacity-50 cursor-pointer"
        >
          {isSaving ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin text-neutral-950" />
              <span>Запазване...</span>
            </>
          ) : (
            <>
              <Save className="w-4 h-4" />
              <span>Запази Настройките</span>
            </>
          )}
        </button>
      </div>
    </div>
  );
};
