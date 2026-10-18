import { Check, CircleHelp, CircleSlash, Clock3, X } from 'lucide-react';
import type { CheckStatus } from '../types/api';

const statusMeta: Record<string, { label: string; className: string; icon: typeof Check }> = {
  passed: { label: 'Passed', className: 'status-passed', icon: Check },
  succeeded: { label: 'Succeeded', className: 'status-passed', icon: Check },
  failed: { label: 'Failed', className: 'status-failed', icon: X },
  rejected: { label: 'Rejected', className: 'status-failed', icon: X },
  unsupported: { label: 'Unsupported', className: 'status-skipped', icon: CircleSlash },
  skipped: { label: 'Skipped', className: 'status-skipped', icon: CircleSlash },
  not_run: { label: 'Not run', className: 'status-muted', icon: Clock3 },
  no_query: { label: 'No query', className: 'status-muted', icon: Clock3 },
  not_available: { label: 'Not available', className: 'status-muted', icon: CircleHelp },
  unknown: { label: 'Unknown', className: 'status-muted', icon: CircleHelp },
};

export function StatusBadge({ status }: { status?: CheckStatus }) {
  const meta = statusMeta[String(status || 'unknown').toLowerCase()] || statusMeta.unknown;
  const Icon = meta.icon;
  return <span className={`status-badge ${meta.className}`}><Icon size={13} aria-hidden="true" />{meta.label}</span>;
}

export function statusLabel(status?: CheckStatus): string {
  const key = String(status || 'unknown').toLowerCase();
  return statusMeta[key]?.label || 'Unknown';
}
