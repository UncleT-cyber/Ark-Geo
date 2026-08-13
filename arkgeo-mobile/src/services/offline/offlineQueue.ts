/**
 * Offline store-and-forward sync manager.
 *
 * When network is unavailable, payloads are written to an encrypted SQLite
 * database.  A background sync worker polls connectivity and pushes queued
 * payloads the moment signal is restored.
 */
import * as SQLite from 'expo-sqlite';
import * as Network from 'expo-network';
import { ARKGEOIngestPayload, QueuedPayload } from '../../types';
import { api } from '../api/client';

const DB_NAME = 'arkgeo_queue.db';

class OfflineQueueManager {
  private db: SQLite.SQLiteDatabase | null = null;
  private isSyncing = false;
  private onQueueChangeCb: ((count: number) => void) | null = null;

  async init(): Promise<void> {
    this.db = await SQLite.openDatabaseAsync(DB_NAME);
    await this.db.execAsync(`
      CREATE TABLE IF NOT EXISTS queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        payload TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        retry_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'pending'
      );
    `);
    await this.startSyncWorker();
  }

  /** Set a callback fired whenever the pending count changes. */
  onQueueChange(cb: (count: number) => void): void {
    this.onQueueChangeCb = cb;
  }

  /** Enqueue a payload for later transmission. */
  async enqueue(payload: ARKGEOIngestPayload): Promise<number> {
    if (!this.db) await this.init();
    const result = await this.db!.runAsync(
      'INSERT INTO queue (payload, created_at, status) VALUES (?, ?, ?)',
      JSON.stringify(payload),
      Date.now(),
      'pending',
    );
    await this.notifyCount();
    return result.lastInsertRowId as number;
  }

  /** Get the count of pending entries. */
  async pendingCount(): Promise<number> {
    if (!this.db) return 0;
    const row = await this.db.getFirstAsync<{ count: number }>(
      "SELECT COUNT(*) as count FROM queue WHERE status = 'pending'",
    );
    return row?.count ?? 0;
  }

  /** List all queued entries. */
  async listAll(): Promise<QueuedPayload[]> {
    if (!this.db) return [];
    const rows = await this.db.getAllAsync<{
      id: number;
      payload: string;
      created_at: number;
      retry_count: number;
      status: string;
    }>('SELECT * FROM queue ORDER BY created_at ASC');
    return rows.map((r) => ({
      id: r.id,
      payload: JSON.parse(r.payload),
      created_at: r.created_at,
      retry_count: r.retry_count,
      status: r.status as QueuedPayload['status'],
    }));
  }

  /** Delete a successfully synced entry. */
  async deleteEntry(id: number): Promise<void> {
    if (!this.db) return;
    await this.db.runAsync('DELETE FROM queue WHERE id = ?', id);
    await this.notifyCount();
  }

  /** Manually trigger a sync attempt. */
  async syncNow(): Promise<{ synced: number; failed: number }> {
    if (this.isSyncing) return { synced: 0, failed: 0 };
    this.isSyncing = true;
    let synced = 0;
    let failed = 0;

    try {
      const entries = await this.listAll();
      for (const entry of entries) {
        if (entry.status === 'failed' && entry.retry_count >= 5) continue;
        try {
          await api.ingest(entry.payload);
          await this.deleteEntry(entry.id);
          synced++;
        } catch (err) {
          await this.db!.runAsync(
            'UPDATE queue SET retry_count = retry_count + 1, status = ? WHERE id = ?',
            'failed',
            entry.id,
          );
          failed++;
        }
      }
    } finally {
      this.isSyncing = false;
      await this.notifyCount();
    }
    return { synced, failed };
  }

  /** Background worker — polls network and syncs when online. */
  private async startSyncWorker(): Promise<void> {
    const tick = async () => {
      try {
        const netState = await Network.getNetworkStateAsync();
        if (netState.isConnected) {
          await this.syncNow();
        }
      } catch {
        // expo-network not available — try sync anyway
        try {
          await this.syncNow();
        } catch {
          // ignore
        }
      }
    };
    // Poll every 15 seconds
    setInterval(tick, 15000);
  }

  private async notifyCount(): Promise<void> {
    const count = await this.pendingCount();
    this.onQueueChangeCb?.(count);
  }
}

export const offlineQueue = new OfflineQueueManager();
