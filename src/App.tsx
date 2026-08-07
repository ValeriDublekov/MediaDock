/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { AuthProvider } from './application/AuthContext';
import { firebaseAuthAdapter } from './adapters/firebaseAuthAdapter';
import { AuthGate } from './components/AuthGate';

export default function App() {
  return (
    <AuthProvider adapter={firebaseAuthAdapter}>
      <AuthGate>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8" data-testid="catalog-placeholder">
          <p className="text-neutral-500 text-center">Catalog feature coming soon.</p>
        </div>
      </AuthGate>
    </AuthProvider>
  );
}
