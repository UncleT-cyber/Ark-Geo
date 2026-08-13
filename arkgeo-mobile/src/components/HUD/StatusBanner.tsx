/**
 * StatusBanner — live network status, GPS sync, and offline queue counter.
 */
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import { Colors, Typography, Spacing, BorderRadius } from '../../theme';

interface Props {
  online: boolean;
  gpsActive: boolean;
  queueCount: number;
}

export function StatusBanner({ online, gpsActive, queueCount }: Props) {
  return (
    <View style={styles.container}>
      <View style={styles.item}>
        <View style={[styles.dot, { backgroundColor: online ? Colors.success : Colors.emergency }]} />
        <Text style={styles.text}>{online ? 'ONLINE' : 'OFFLINE'}</Text>
      </View>
      <View style={styles.item}>
        <View style={[styles.dot, { backgroundColor: gpsActive ? Colors.cyan : Colors.textMuted }]} />
        <Text style={styles.text}>GPS {gpsActive ? 'SYNC' : 'NO-FIX'}</Text>
      </View>
      {queueCount > 0 && (
        <View style={styles.queueBadge}>
          <Text style={styles.queueText}>QUEUE: {queueCount}</Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.md,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.sm,
    backgroundColor: Colors.bgDark,
    borderBottomWidth: 1,
    borderBottomColor: Colors.borderDim,
  },
  item: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: Spacing.xs,
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 4,
  },
  text: {
    ...Typography.mono,
    fontSize: 11,
  },
  queueBadge: {
    backgroundColor: Colors.warning,
    borderRadius: BorderRadius.sm,
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
  },
  queueText: {
    fontSize: 10,
    fontWeight: 'bold',
    color: Colors.bgDarkest,
  },
});
