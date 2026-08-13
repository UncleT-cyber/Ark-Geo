/**
 * TierCard — [CARD 3: METADATA / SOURCE TIER]
 *
 * Clearly displays which pipeline tier produced the result, with a colored
 * tier indicator and source label.
 */
import React from 'react';

interface Props {
  source: string;
  tier: string;
}

interface TierInfo {
  icon: string;
  label: string;
  color: string;
  description: string;
}

function tierInfo(source: string, tier: string): TierInfo {
  switch (source) {
    case 'NATIVE_EXIF_HARDWARE':
      return {
        icon: '🟢',
        label: 'TIER 1: Native Hardware EXIF',
        color: '#22C55E',
        description: 'GPS coordinates extracted from image EXIF metadata',
      };
    case 'AI_VISION':
      return {
        icon: '🔵',
        label: 'TIER 2: Visual AI Ensemble',
        color: '#38BDF8',
        description: 'Location estimated by AI vision models',
      };
    case 'TELEMETRY':
      return {
        icon: '🟡',
        label: 'TIER 3: Cellular / Wi-Fi Telemetry',
        color: '#F59E0B',
        description: 'Location derived from cell tower or Wi-Fi BSSID lookup',
      };
    case 'NO_METADATA_NO_AI_KEY':
      return {
        icon: '🔴',
        label: 'DEGRADED: No Metadata / No AI Key',
        color: '#EF4444',
        description: 'EXIF stripped and no AI keys configured on server',
      };
    default:
      return {
        icon: '⚪',
        label: `TIER: ${tier}`,
        color: '#94A3B8',
        description: `Source: ${source}`,
      };
  }
}

export function TierCard({ source, tier }: Props) {
  const info = tierInfo(source, tier);
  return (
    <div className="panel-section tier-card">
      <div className="panel-title">SOURCE TIER</div>
      <div className="tier-badge" style={{ borderLeftColor: info.color }}>
        <span className="tier-icon">{info.icon}</span>
        <div className="tier-text">
          <div className="tier-label" style={{ color: info.color }}>{info.label}</div>
          <div className="tier-desc">{info.description}</div>
        </div>
      </div>
    </div>
  );
}
