/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { useState } from 'react';
import { AuthProvider, useAuth } from './application/AuthContext';
import { firebaseAuthAdapter } from './adapters/firebaseAuthAdapter';
import { AuthGate } from './components/AuthGate';
import { CatalogView } from './components/CatalogView';
import { ParseLogView } from './components/ParseLogView';
import { TriggerScannerModal } from './components/TriggerScannerModal';
import { Film, FileText } from 'lucide-react';

function AppContent() {
  const [activeTab, setActiveTab] = useState<'catalog' | 'parseLogs'>('catalog');
  const { user } = useAuth();

  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
      {/* Top Navigation Menu Bar */}
      <header className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-4 border-b border-neutral-800">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 text-amber-400 flex items-center justify-center font-bold text-lg shadow-sm">
            MF
          </div>
          <div>
            <h1 className="text-xl font-extrabold tracking-tight text-neutral-100">MoviesFeed</h1>
            <p className="text-xs text-neutral-400">Media aggregator & RSS scanner</p>
          </div>
        </div>

        {/* Actions & Menu Tabs */}
        <div className="flex flex-wrap items-center gap-3">
          <TriggerScannerModal />

          <nav className="flex items-center gap-2 bg-neutral-900 border border-neutral-800 p-1.5 rounded-xl self-start sm:self-auto" aria-label="Main Navigation">
            <button
              onClick={() => setActiveTab('catalog')}
              data-testid="nav-tab-catalog"
              className={`inline-flex items-center gap-2 min-h-[40px] px-4 py-2 text-sm font-semibold rounded-lg transition-all cursor-pointer ${
                activeTab === 'catalog'
                  ? 'bg-amber-500 text-neutral-950 shadow-sm'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/60'
              }`}
            >
              <Film className="w-4 h-4" />
              Каталог
            </button>
            <button
              onClick={() => setActiveTab('parseLogs')}
              data-testid="nav-tab-parse-logs"
              className={`inline-flex items-center gap-2 min-h-[40px] px-4 py-2 text-sm font-semibold rounded-lg transition-all cursor-pointer ${
                activeTab === 'parseLogs'
                  ? 'bg-amber-500 text-neutral-950 shadow-sm'
                  : 'text-neutral-400 hover:text-neutral-200 hover:bg-neutral-800/60'
              }`}
            >
              <FileText className="w-4 h-4" />
              Лог от парсването
            </button>
          </nav>
        </div>
      </header>

      {/* Main View Area */}
      <main>
        {activeTab === 'catalog' ? <CatalogView /> : <ParseLogView currentUserUid={user?.uid} />}
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider adapter={firebaseAuthAdapter}>
      <AuthGate>
        <AppContent />
      </AuthGate>
    </AuthProvider>
  );
}


