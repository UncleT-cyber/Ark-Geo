/**
 * Dual data cards — hardware telemetry + AI intelligence.
 */
import React from 'react';
import { View, Text, StyleSheet, ScrollView } from 'react-native';
import { Colors, Typography, Spacing, BorderRadius } from '../../theme';
import { GpsFix, ConsensusResult, VisualEvidenceTag } from '../../types';

interface Props {
  gpsFix: GpsFix | null;
  exifIntact: boolean;
  consensus: ConsensusResult | null;
}

export function DualDataCards({ gpsFix, exifIntact, consensus }: Props) {
  return (
    <View style={styles.container}>
      {/* Hardware Telemetry Card */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>HARDWARE TELEMETRY</Text>
        </View>
        <View style={styles.cardBody}>
          <DataRow label="LAT" value={gpsFix ? gpsFix.lat.toFixed(6) : '---'} />
          <DataRow label="LON" value={gpsFix ? gpsFix.lon.toFixed(6) : '---'} />
          <DataRow label="ALT" value={gpsFix?.altitude ? `${gpsFix.altitude.toFixed(1)}m` : '---'} />
          <DataRow
            label="EXIF"
            value={exifIntact ? 'INTACT' : 'STRIPPED'}
            valueColor={exifIntact ? Colors.success : Colors.warning}
          />
        </View>
      </View>

      {/* AI Intelligence Card */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>AI INTELLIGENCE</Text>
          {consensus && (
            <View style={[styles.tierBadge, { backgroundColor: tierColor(consensus.tier_used) }]}>
              <Text style={styles.tierText}>{consensus.tier_used.toUpperCase()}</Text>
            </View>
          )}
        </View>
        <View style={styles.cardBody}>
          {consensus ? (
            <>
              <DataRow
                label="EST LAT"
                value={consensus.estimated_latitude.toFixed(6)}
              />
              <DataRow
                label="EST LON"
                value={consensus.estimated_longitude.toFixed(6)}
              />
              <DataRow
                label="RADIUS"
                value={`${Math.round(consensus.search_radius_meters)}m`}
              />
              <View style={styles.confidenceRow}>
                <Text style={styles.confidenceLabel}>CONFIDENCE</Text>
                <View style={styles.confidenceBar}>
                  <View
                    style={[
                      styles.confidenceFill,
                      {
                        width: `${Math.round(consensus.confidence_score * 100)}%`,
                        backgroundColor: confidenceColor(consensus.confidence_score),
                      },
                    ]}
                  />
                </View>
                <Text style={styles.confidenceValue}>
                  {Math.round(consensus.confidence_score * 100)}%
                </Text>
              </View>
              {consensus.primary_country && (
                <DataRow label="COUNTRY" value={consensus.primary_country} />
              )}
              {consensus.flag_low_context_indoor && (
                <Text style={styles.lowContextWarn}>⚠ LOW CONTEXT INDOOR</Text>
              )}
              {consensus.visual_evidence_tags.length > 0 && (
                <ScrollView horizontal style={styles.tagsRow} showsHorizontalScrollIndicator={false}>
                  {consensus.visual_evidence_tags.map((tag, i) => (
                    <EvidencePill key={i} tag={tag} />
                  ))}
                </ScrollView>
              )}
            </>
          ) : (
            <Text style={styles.placeholder}>No AI analysis yet. Tap SNAP to begin.</Text>
          )}
        </View>
      </View>
    </View>
  );
}

function DataRow({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <View style={styles.dataRow}>
      <Text style={styles.dataLabel}>{label}</Text>
      <Text style={[styles.dataValue, valueColor ? { color: valueColor } : null]}>{value}</Text>
    </View>
  );
}

function EvidencePill({ tag }: { tag: VisualEvidenceTag }) {
  const catColor: Record<string, string> = {
    architecture: Colors.cyan,
    botanical: Colors.success,
    ocr: Colors.warning,
    infrastructure: Colors.cyanDim,
  };
  return (
    <View style={[styles.pill, { borderColor: catColor[tag.category] || Colors.border }]}>
      <Text style={[styles.pillText, { color: catColor[tag.category] || Colors.textSecondary }]}>
        {tag.label}
      </Text>
    </View>
  );
}

function tierColor(tier: string): string {
  switch (tier) {
    case 'metadata': return Colors.success;
    case 'telemetry': return Colors.cyan;
    case 'vision':
    case 'consensus': return Colors.warning;
    default: return Colors.textMuted;
  }
}

function confidenceColor(score: number): string {
  if (score >= 0.7) return Colors.success;
  if (score >= 0.4) return Colors.warning;
  return Colors.emergency;
}

const styles = StyleSheet.create({
  container: {
    gap: Spacing.md,
  },
  card: {
    backgroundColor: Colors.bgCard,
    borderRadius: BorderRadius.lg,
    borderWidth: 1,
    borderColor: Colors.borderDim,
    overflow: 'hidden',
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.sm,
    backgroundColor: Colors.bgCardElevated,
  },
  cardTitle: {
    ...Typography.mono,
    fontSize: 11,
  },
  tierBadge: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
    borderRadius: BorderRadius.sm,
  },
  tierText: {
    fontSize: 9,
    fontWeight: 'bold',
    color: Colors.bgDarkest,
  },
  cardBody: {
    padding: Spacing.lg,
    gap: Spacing.sm,
  },
  dataRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  dataLabel: {
    ...Typography.mono,
    fontSize: 12,
    color: Colors.textMuted,
  },
  dataValue: {
    ...Typography.mono,
    fontSize: 12,
    color: Colors.textPrimary,
  },
  confidenceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.sm,
  },
  confidenceLabel: {
    ...Typography.mono,
    fontSize: 11,
    color: Colors.textMuted,
    width: 80,
  },
  confidenceBar: {
    flex: 1,
    height: 6,
    backgroundColor: Colors.bgInput,
    borderRadius: 3,
    overflow: 'hidden',
  },
  confidenceFill: {
    height: '100%',
    borderRadius: 3,
  },
  confidenceValue: {
    ...Typography.mono,
    fontSize: 12,
    color: Colors.cyanBright,
    width: 36,
    textAlign: 'right',
  },
  lowContextWarn: {
    fontSize: 11,
    color: Colors.warning,
    fontWeight: 'bold',
  },
  tagsRow: {
    flexDirection: 'row',
    marginTop: Spacing.xs,
  },
  pill: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.xs,
    borderRadius: BorderRadius.pill,
    borderWidth: 1,
    marginRight: Spacing.xs,
  },
  pillText: {
    fontSize: 11,
    fontWeight: '600',
  },
  placeholder: {
    ...Typography.body,
    fontStyle: 'italic',
  },
});
