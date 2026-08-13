/**
 * HomeScreen — Quick snap & safety check-in UI.
 *
 * Central capture button pairs an image with GPS + 5s audio and sends
 * the full ingest payload to the backend. Falls back to the offline queue
 * when network is unavailable.
 */
import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ScrollView,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors, Typography, Spacing, BorderRadius } from '../theme';
import { StatusBanner } from '../components/HUD/StatusBanner';
import { TacticalRadarOverlay } from '../components/HUD/TacticalRadarOverlay';
import { DualDataCards } from '../components/HUD/DualDataCards';
import { MapRenderer } from '../components/map/MapRenderer';
import { SosModal } from '../components/modal/SosModal';
import { locationService } from '../services/location/locationService';
import { audioService } from '../services/audio/audioService';
import { offlineQueue } from '../services/offline/offlineQueue';
import { api } from '../services/api/client';
import {
  AnalyzeResponse,
  ARKGEOIngestPayload,
  GpsFix,
  EmergencyContact,
} from '../types';

export function HomeScreen() {
  const [online, setOnline] = useState(true);
  const [gpsFix, setGpsFix] = useState<GpsFix | null>(null);
  const [queueCount, setQueueCount] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState<AnalyzeResponse | null>(null);
  const [showSos, setShowSos] = useState(false);
  const [stealth, setStealth] = useState(false);
  const [lastImage, setLastImage] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      await locationService.requestPermissions();
      await audioService.requestPermissions();
      await offlineQueue.init();
      offlineQueue.onQueueChange(setQueueCount);
      const gps = await locationService.getCurrentGps();
      setGpsFix(gps);
    })();
  }, []);

  const handleCapture = useCallback(
    async (imageBase64: string) => {
      setLastImage(imageBase64);
      setProcessing(true);

      const telemetry = await locationService.buildTelemetry();
      const audioB64 = await audioService.record5Seconds();

      const payload: ARKGEOIngestPayload = {
        image_base64: imageBase64,
        exif_extracted_gps: telemetry.last_known_outdoor_gps
          ? { lat: telemetry.last_known_outdoor_gps.lat, lon: telemetry.last_known_outdoor_gps.lon }
          : null,
        device_telemetry: telemetry,
        audio_base64: audioB64,
        user_id: 'mobile-user',
      };

      try {
        const resp = await api.ingest(payload);
        setResult(resp);
        setOnline(true);
      } catch (err) {
        console.warn('[HomeScreen] Ingest failed, queueing offline:', err);
        await offlineQueue.enqueue(payload);
        setQueueCount(await offlineQueue.pendingCount());
        setOnline(false);
        Alert.alert('Offline', 'Snapshot queued for sync when signal returns.');
      } finally {
        setProcessing(false);
      }
    },
    [],
  );

  // Simulate capture for the central button (real camera would use CameraPreview)
  const handleSnap = () => {
    // In production this is triggered by CameraPreview.onCapture
    // For the button-based UI we use a placeholder base64
    handleCapture('placeholder');
  };

  const handleSos = async () => {
    setShowSos(false);
    try {
      const gps = await locationService.getCurrentGps();
      await api.sos({
        user_id: 'mobile-user',
        last_known_gps: gps,
        last_capture_image_base64: lastImage,
        contacts: [
          { name: 'Emergency Contact', phone: '+15551234567' },
        ],
      });
      Alert.alert('SOS Dispatched', 'Emergency contacts have been notified.');
    } catch (err) {
      Alert.alert('SOS Failed', 'Could not dispatch. Check network.');
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <StatusBanner online={online} gpsActive={!!gpsFix} queueCount={queueCount} />

      <ScrollView contentContainerStyle={styles.scroll}>
        {/* Viewfinder / Map */}
        <View style={styles.viewfinder}>
          {result ? (
            <MapRenderer
              consensus={result.consensus}
              gpsLat={gpsFix?.lat}
              gpsLon={gpsFix?.lon}
            />
          ) : (
            <View style={styles.viewfinderPlaceholder}>
              <Text style={styles.placeholderText}>ARKGEO HUD</Text>
              <Text style={styles.placeholderSubtext}>Tap SNAP to capture & analyze</Text>
            </View>
          )}
          <TacticalRadarOverlay
            active={processing}
            confidence={result?.consensus.confidence_score}
          />
        </View>

        {/* Primary Action Hub */}
        <View style={styles.actionHub}>
          <TouchableOpacity
            style={styles.snapBtn}
            onPress={handleSnap}
            disabled={processing}
          >
            <Text style={styles.snapBtnText}>SNAP &</Text>
            <Text style={styles.snapBtnText}>CHECK-IN</Text>
          </TouchableOpacity>

          <View style={styles.quickControls}>
            <TouchableOpacity
              style={[styles.quickBtn, stealth && styles.quickBtnActive]}
              onPress={() => setStealth(!stealth)}
            >
              <Text style={styles.quickBtnText}>STEALTH</Text>
            </TouchableOpacity>

            <TouchableOpacity
              style={styles.sosBtn}
              onPress={() => setShowSos(true)}
            >
              <Text style={styles.sosBtnText}>TRIGGER SOS</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Dual Data Cards */}
        <DualDataCards
          gpsFix={gpsFix}
          exifIntact={!!result?.exif_raw && Object.keys(result.exif_raw).length > 0}
          consensus={result?.consensus ?? null}
        />
      </ScrollView>

      <SosModal
        visible={showSos}
        onCancel={() => setShowSos(false)}
        onConfirm={handleSos}
      />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bgDarkest,
  },
  scroll: {
    padding: Spacing.lg,
    paddingBottom: Spacing.xxl,
  },
  viewfinder: {
    height: 260,
    borderRadius: BorderRadius.lg,
    overflow: 'hidden',
    marginBottom: Spacing.lg,
    backgroundColor: Colors.bgCard,
    borderWidth: 1,
    borderColor: Colors.borderDim,
  },
  viewfinderPlaceholder: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  placeholderText: {
    fontSize: 28,
    fontWeight: 'bold',
    color: Colors.cyan + '60',
    letterSpacing: 4,
  },
  placeholderSubtext: {
    ...Typography.body,
    marginTop: Spacing.sm,
  },
  actionHub: {
    alignItems: 'center',
    marginBottom: Spacing.xl,
  },
  snapBtn: {
    width: '100%',
    paddingVertical: Spacing.xl,
    borderRadius: BorderRadius.lg,
    backgroundColor: Colors.bgCardElevated,
    borderWidth: 2,
    borderColor: Colors.cyan,
    alignItems: 'center',
    justifyContent: 'center',
  },
  snapBtnText: {
    fontSize: 18,
    fontWeight: 'bold',
    color: Colors.cyan,
    letterSpacing: 2,
  },
  quickControls: {
    flexDirection: 'row',
    gap: Spacing.md,
    marginTop: Spacing.lg,
    width: '100%',
  },
  quickBtn: {
    flex: 1,
    paddingVertical: Spacing.md,
    borderRadius: BorderRadius.md,
    backgroundColor: Colors.bgCard,
    borderWidth: 1,
    borderColor: Colors.border,
    alignItems: 'center',
  },
  quickBtnActive: {
    borderColor: Colors.cyan,
    backgroundColor: Colors.cyan + '15',
  },
  quickBtnText: {
    ...Typography.mono,
    fontSize: 12,
  },
  sosBtn: {
    flex: 1,
    paddingVertical: Spacing.md,
    borderRadius: BorderRadius.md,
    backgroundColor: Colors.emergency + '20',
    borderWidth: 2,
    borderColor: Colors.emergency,
    alignItems: 'center',
  },
  sosBtnText: {
    fontSize: 14,
    fontWeight: 'bold',
    color: Colors.emergency,
    letterSpacing: 1,
  },
});
