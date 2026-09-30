import { useState } from 'react'
import { CatalogView } from './features/catalog/CatalogView'
import { HistoryView } from './features/history/HistoryView'
import { OscarCatalogView } from './features/oscar/OscarCatalogView'
import { SourceSettingsView } from './features/sources/SourceSettingsView'

type Section = 'catalog' | 'oscar' | 'sources' | 'history'

const sections: { id: Section; number: string; label: string }[] = [
  { id: 'catalog', number: '01', label: 'Catalog' },
  { id: 'oscar', number: '02', label: 'Oscar catalog' },
  { id: 'sources', number: '03', label: 'Configuration' },
  { id: 'history', number: '04', label: 'Scan history' },
]

const sectionContent: Record<Section, { eyebrow: string; title: string; description: string }> = {
  catalog: {
    eyebrow: 'LIBRARY',
    title: 'Catalog',
    description: 'Browse titles collected from your configured feeds.',
  },
  oscar: {
    eyebrow: 'ACADEMY AWARDS',
    title: 'Oscar catalog',
    description: 'Browse nominated films, award outcomes, and available metadata.',
  },
  sources: {
    eyebrow: 'CONFIGURATION',
    title: 'Configuration',
    description: 'Manage feed sources, matching rules, and OMDb provider settings.',
  },
  history: {
    eyebrow: 'OPERATIONS',
    title: 'Scan history',
    description: 'Review completed scans and individual parser decisions.',
  },
}

function App() {
  const [section, setSection] = useState<Section>('catalog')
  const content = sectionContent[section]

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#catalog" onClick={() => setSection('catalog')}>
          <span className="brand-mark" aria-hidden="true">MD</span>
          <span className="brand-name">MediaDock</span>
        </a>

        <div className="sidebar-label">WORKSPACE</div>
        <nav className="primary-nav" aria-label="Main navigation">
          {sections.map((item) => (
            <button
              aria-current={section === item.id ? 'page' : undefined}
              className={`nav-item${section === item.id ? ' is-active' : ''}`}
              key={item.id}
              onClick={() => setSection(item.id)}
              type="button"
            >
              <span className="nav-number">{item.number}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="status-mark" aria-hidden="true" />
          <span>Local instance</span>
          <span className="status-caption">API-backed</span>
        </div>
      </aside>

      <main className="main-shell">
        <header className="topbar">
          <div className="breadcrumb">MEDIADOCK <span>/</span> {content.eyebrow}</div>
          <div className="topbar-tag"><span /> LOCAL WORKSPACE</div>
        </header>

        <div className="page-content">
          <div className="page-heading">
            <div>
              <p className="eyebrow">{content.eyebrow}</p>
              <h1>{content.title}</h1>
              <p className="page-description">{content.description}</p>
            </div>
            <div className="edition-mark">MEDIA LIBRARY <span>01</span></div>
          </div>

          {section === 'catalog' && <CatalogView />}
          {section === 'oscar' && <OscarCatalogView />}
          {section === 'sources' && <SourceSettingsView />}
          {section === 'history' && <HistoryView />}
        </div>
      </main>
    </div>
  )
}

export default App
