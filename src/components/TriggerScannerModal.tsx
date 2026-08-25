import React from 'react';
import { ExternalLink, Play } from 'lucide-react';

interface TriggerScannerModalProps {
  buttonClassName?: string;
  buttonVariant?: 'primary' | 'secondary' | 'header';
}

export const TriggerScannerModal: React.FC<TriggerScannerModalProps> = ({
  buttonClassName,
  buttonVariant = 'header',
}) => {
  const owner = (import.meta.env.VITE_GITHUB_OWNER || '').trim();
  const repo = (import.meta.env.VITE_GITHUB_REPO || '').trim();
  const workflow = (import.meta.env.VITE_GITHUB_WORKFLOW || 'scanner.yml').trim();
  const workflowUrl = owner && repo
    ? `https://github.com/${owner}/${repo}/actions/workflows/${workflow}`
    : null;

  const defaultButtonClass =
    buttonVariant === 'header'
      ? 'inline-flex items-center gap-2 min-h-[40px] px-3.5 py-2 text-sm font-semibold text-amber-400 bg-amber-500/10 border border-amber-500/30 rounded-xl hover:bg-amber-500/20 hover:border-amber-500/50 transition-all cursor-pointer shadow-sm'
      : 'inline-flex items-center gap-2 min-h-[44px] px-4 py-2.5 text-sm font-semibold text-neutral-950 bg-amber-500 hover:bg-amber-400 rounded-lg transition-colors cursor-pointer shadow-sm';

  if (!workflowUrl) {
    return (
      <span
        data-testid="trigger-scanner-unconfigured"
        className={buttonClassName || defaultButtonClass}
        title="Configure the public GitHub repository URL"
      >
        <Play className="w-4 h-4" aria-hidden="true" />
        <span>Actions</span>
      </span>
    );
  }

  return (
    <a
      href={workflowUrl}
      target="_blank"
      rel="noopener noreferrer"
      data-testid="trigger-scanner-button"
      className={buttonClassName || defaultButtonClass}
      title="Open the protected GitHub Actions workflow"
    >
      <Play className="w-4 h-4" aria-hidden="true" />
      <span>Actions</span>
      <ExternalLink className="w-3.5 h-3.5" aria-hidden="true" />
    </a>
  );
};
