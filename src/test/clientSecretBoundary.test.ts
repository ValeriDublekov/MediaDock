import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const root = resolve(__dirname, '../..');
const envExample = resolve(root, '.env.example');
const productionFiles = [
  'vite.config.ts',
  'src/adapters/firestoreManualMappingAdapter.ts',
  'src/adapters/firestoreSettingsAdapter.ts',
  'src/adapters/omdbAdapter.ts',
  'src/components/SettingsView.tsx',
  'src/components/TitleCard.tsx',
  'src/components/TitleDetailModal.tsx',
  'src/components/TriggerScannerModal.tsx',
].map((file) => resolve(root, file));

describe('browser scanner credential boundary', () => {
  it('does not expose private scanner credential names or storage keys', () => {
    const source = productionFiles
      .map((file) => readFileSync(file, 'utf8'))
      .join('\n');

    expect(source).not.toMatch(/VITE_OMDB_API_KEY|VITE_GITHUB_PAT/);
    expect(source).not.toMatch(/import\.meta\.env\.OMDB_API_KEY/);
    expect(source).not.toMatch(/movies_feed_(?:omdb_api_key|gh_pat)/);
    expect(source).not.toMatch(/Authorization:\s*`Bearer/);
    expect(source).not.toMatch(/api\.github\.com\/repos/);
    expect(source).not.toMatch(/envPrefix[^\n]*OMDB_API_KEY/);

    const exampleConfig = readFileSync(envExample, 'utf8');
    expect(exampleConfig).not.toMatch(/VITE_OMDB_API_KEY|VITE_GITHUB_PAT/);
  });
});