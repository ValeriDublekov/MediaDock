/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import { AuthProvider } from './application/AuthContext';
import { firebaseAuthAdapter } from './adapters/firebaseAuthAdapter';
import { AuthGate } from './components/AuthGate';
import { CatalogView } from './components/CatalogView';

export default function App() {
  return (
    <AuthProvider adapter={firebaseAuthAdapter}>
      <AuthGate>
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <CatalogView />
        </div>
      </AuthGate>
    </AuthProvider>
  );
}

