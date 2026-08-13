/**
 * OfflineQueueScreen — pending sync queue manager.
 */
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  RefreshControl,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors, Typography, Spacing, BorderRadius } from '../theme';
import { offlineQueue } from '../services/offline/offlineQueue';
import { QueuedPayload } from '../types';

export function OfflineQueueScreen() {
  const [entries, setEntries] = useState<QueuedPayload[]>([]);
  const [refreshing, setRefreshing] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const load = async () => {
    const list = await offlineQueue.listAll();
    setEntries(list);
  };

  useEffect(() => {
    load();
    offlineQueue.onQueueChange(() => load());
  }, []);

  const onRefresh = async () => {
    setRefreshing(true);
    await load();
    setRefreshing(false);
  };

  const handleSync = async () => {
    setSyncing(true);
    const result = await offlineQueue.syncNow();
    setSyncing(false);
    await load();
    Alert.alert(
      'Sync Complete',
      `Synced: ${result.synced}\nFailed: ${result.failed}`,
    );
  };

  const renderItem = ({ item }: { item: QueuedPayload }) => (
    <View style={styles.entryCard}>
      <View style={styles.entryHeader}>
        <Text style={styles.entryId}>#{item.id}</Text>
        <View
          style={[
            styles.statusBadge,
            { backgroundColor: item.status === 'failed' ? Colors.emergency : Colors.warning },
          ]}
        >
          <Text style={styles.statusText}>{item.status.toUpperCase()}</Text>
        </View>
      </View>
      <Text style={styles.entryTime}>
        {new Date(item.created_at).toLocaleString()}
      </Text>
      <Text style={styles.entryDetail}>
        Retries: {item.retry_count} · GPS:{' '}
        {item.payload.exif_extracted_gps
          ? `${item.payload.exif_extracted_gps.lat.toFixed(4)}, ${item.payload.exif_extracted_gps.lon.toFixed(4)}`
          : 'N/A'}
      </Text>
    </View>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>OFFLINE QUEUE</Text>
        <Text style={styles.subtitle}>
          {entries.length} pending snapshot{entries.length !== 1 ? 's' : ''}
        </Text>
      </View>

      {entries.length > 0 && (
        <TouchableOpacity
          style={[styles.syncBtn, syncing && styles.syncBtnDisabled]}
          onPress={handleSync}
          disabled={syncing}
        >
          <Text style={styles.syncBtnText}>
            {syncing ? 'SYNCING...' : 'SYNC NOW'}
          </Text>
        </TouchableOpacity>
      )}

      <FlatList
        data={entries}
        keyExtractor={(item) => item.id.toString()}
        renderItem={renderItem}
        refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} />}
        contentContainerStyle={styles.list}
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyText}>Queue is empty</Text>
            <Text style={styles.emptySubtext}>All snapshots synced</Text>
          </View>
        }
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bgDarkest,
    padding: Spacing.lg,
  },
  header: {
    paddingVertical: Spacing.lg,
  },
  title: {
    fontSize: 20,
    fontWeight: 'bold',
    color: Colors.textPrimary,
    letterSpacing: 1,
  },
  subtitle: {
    ...Typography.body,
    marginTop: Spacing.xs,
  },
  syncBtn: {
    paddingVertical: Spacing.md,
    borderRadius: BorderRadius.md,
    backgroundColor: Colors.cyan + '20',
    borderWidth: 2,
    borderColor: Colors.cyan,
    alignItems: 'center',
    marginBottom: Spacing.lg,
  },
  syncBtnDisabled: {
    opacity: 0.5,
  },
  syncBtnText: {
    fontSize: 14,
    fontWeight: 'bold',
    color: Colors.cyan,
    letterSpacing: 2,
  },
  list: {
    paddingBottom: Spacing.xxl,
  },
  entryCard: {
    backgroundColor: Colors.bgCard,
    borderRadius: BorderRadius.md,
    borderWidth: 1,
    borderColor: Colors.borderDim,
    padding: Spacing.md,
    marginBottom: Spacing.sm,
  },
  entryHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  entryId: {
    ...Typography.mono,
    fontSize: 14,
    color: Colors.cyanBright,
  },
  statusBadge: {
    paddingHorizontal: Spacing.sm,
    paddingVertical: 2,
    borderRadius: BorderRadius.sm,
  },
  statusText: {
    fontSize: 10,
    fontWeight: 'bold',
    color: Colors.bgDarkest,
  },
  entryTime: {
    ...Typography.caption,
    marginTop: Spacing.xs,
  },
  entryDetail: {
    ...Typography.mono,
    fontSize: 11,
    color: Colors.textMuted,
    marginTop: 2,
  },
  empty: {
    alignItems: 'center',
    marginTop: Spacing.xxl,
  },
  emptyText: {
    ...Typography.subtitle,
    color: Colors.textMuted,
  },
  emptySubtext: {
    ...Typography.caption,
    marginTop: Spacing.xs,
  },
});
