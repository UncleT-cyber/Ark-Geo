/**
 * SafetyTimerScreen — Dead-Man's switch configuration & status.
 */
import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  TextInput,
  Alert,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Colors, Typography, Spacing, BorderRadius } from '../theme';
import { api } from '../services/api/client';
import { locationService } from '../services/location/locationService';
import { DeadManStatus } from '../types';

const DURATIONS = [10, 30, 60, 120];

export function SafetyTimerScreen() {
  const [duration, setDuration] = useState(30);
  const [pin, setPin] = useState('');
  const [status, setStatus] = useState<DeadManStatus | null>(null);
  const [arming, setArming] = useState(false);

  const fetchStatus = async () => {
    try {
      const s = await api.deadManStatus('mobile-user');
      setStatus(s);
    } catch {
      // backend may be offline
    }
  };

  useEffect(() => {
    fetchStatus();
  }, []);

  const handleArm = async () => {
    if (pin.length < 4) {
      Alert.alert('Invalid PIN', 'PIN must be at least 4 digits.');
      return;
    }
    setArming(true);
    try {
      // Note: in production, hash the PIN locally before sending.
      // Here we send a simple hash for demo.
      const pinHash = `hash:${pin}`;
      const gps = await locationService.getCurrentGps();
      const s = await api.armDeadMan({
        user_id: 'mobile-user',
        duration_minutes: duration,
        pin_hash: pinHash,
        emergency_contacts: [{ name: 'Emergency Contact', phone: '+15551234567' }],
        last_known_gps: gps,
      });
      setStatus(s);
      Alert.alert('Armed', `Dead-Man's switch armed for ${duration} minutes.`);
    } catch (err) {
      Alert.alert('Error', 'Could not arm switch. Backend offline?');
    } finally {
      setArming(false);
    }
  };

  const handleCheckIn = async () => {
    if (pin.length < 4) {
      Alert.alert('Enter PIN', 'Enter your safety PIN to check in.');
      return;
    }
    try {
      const pinHash = `hash:${pin}`;
      const s = await api.checkInDeadMan('mobile-user', pinHash);
      setStatus(s);
      Alert.alert('Checked In', 'Timer reset successfully.');
    } catch {
      Alert.alert('Error', 'Check-in failed.');
    }
  };

  const handleDisarm = async () => {
    try {
      await api.disarmDeadMan('mobile-user');
      setStatus(null);
      Alert.alert('Disarmed', 'Dead-Man\'s switch disarmed.');
    } catch {
      Alert.alert('Error', 'Disarm failed.');
    }
  };

  const armed = status?.armed;
  const remaining = status?.grace_remaining_seconds ?? 0;
  const minutes = Math.floor(remaining / 60);
  const seconds = remaining % 60;

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>DEAD-MAN'S SWITCH</Text>
      </View>

      {armed ? (
        <View style={styles.armedContainer}>
          <View style={[styles.statusCard, { borderColor: Colors.emergency }]}>
            <Text style={styles.armedLabel}>ARMED</Text>
            <Text style={styles.timerText}>
              {String(minutes).padStart(2, '0')}:{String(seconds).padStart(2, '0')}
            </Text>
            <Text style={styles.timerSubtext}>remaining</Text>
          </View>

          <TextInput
            style={styles.input}
            placeholder="Enter PIN to check in"
            placeholderTextColor={Colors.textMuted}
            value={pin}
            onChangeText={setPin}
            keyboardType="numeric"
            secureTextEntry
          />

          <TouchableOpacity style={styles.checkInBtn} onPress={handleCheckIn}>
            <Text style={styles.checkInBtnText}>CHECK IN</Text>
          </TouchableOpacity>

          <TouchableOpacity style={styles.disarmBtn} onPress={handleDisarm}>
            <Text style={styles.disarmBtnText}>DISARM</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <View style={styles.configContainer}>
          <Text style={styles.sectionLabel}>DURATION</Text>
          <View style={styles.durationRow}>
            {DURATIONS.map((d) => (
              <TouchableOpacity
                key={d}
                style={[styles.durationBtn, duration === d && styles.durationBtnActive]}
                onPress={() => setDuration(d)}
              >
                <Text
                  style={[
                    styles.durationText,
                    duration === d && styles.durationTextActive,
                  ]}
                >
                  {d}m
                </Text>
              </TouchableOpacity>
            ))}
          </View>

          <Text style={styles.sectionLabel}>SAFETY PIN</Text>
          <TextInput
            style={styles.input}
            placeholder="Set a 4+ digit PIN"
            placeholderTextColor={Colors.textMuted}
            value={pin}
            onChangeText={setPin}
            keyboardType="numeric"
            secureTextEntry
          />

          <Text style={styles.sectionLabel}>EMERGENCY CONTACTS</Text>
          <View style={styles.contactCard}>
            <Text style={styles.contactName}>Emergency Contact</Text>
            <Text style={styles.contactPhone}>+1 (555) 123-4567</Text>
          </View>

          <TouchableOpacity
            style={[styles.armBtn, arming && styles.armBtnDisabled]}
            onPress={handleArm}
            disabled={arming}
          >
            <Text style={styles.armBtnText}>ARM SWITCH</Text>
          </TouchableOpacity>
        </View>
      )}
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
  armedContainer: {
    flex: 1,
    alignItems: 'center',
  },
  statusCard: {
    width: '100%',
    backgroundColor: Colors.bgCard,
    borderRadius: BorderRadius.xl,
    borderWidth: 2,
    padding: Spacing.xxl,
    alignItems: 'center',
    marginBottom: Spacing.xl,
  },
  armedLabel: {
    fontSize: 14,
    fontWeight: 'bold',
    color: Colors.emergency,
    letterSpacing: 3,
  },
  timerText: {
    fontSize: 48,
    fontWeight: 'bold',
    color: Colors.emergency,
    fontVariant: ['tabular-nums'],
    marginTop: Spacing.md,
  },
  timerSubtext: {
    ...Typography.caption,
    marginTop: Spacing.xs,
  },
  configContainer: {
    flex: 1,
  },
  sectionLabel: {
    ...Typography.mono,
    fontSize: 11,
    marginTop: Spacing.lg,
    marginBottom: Spacing.sm,
  },
  durationRow: {
    flexDirection: 'row',
    gap: Spacing.sm,
  },
  durationBtn: {
    flex: 1,
    paddingVertical: Spacing.md,
    borderRadius: BorderRadius.md,
    backgroundColor: Colors.bgCard,
    borderWidth: 1,
    borderColor: Colors.border,
    alignItems: 'center',
  },
  durationBtnActive: {
    borderColor: Colors.cyan,
    backgroundColor: Colors.cyan + '15',
  },
  durationText: {
    ...Typography.mono,
    color: Colors.textSecondary,
  },
  durationTextActive: {
    color: Colors.cyan,
    fontWeight: 'bold',
  },
  input: {
    backgroundColor: Colors.bgInput,
    borderRadius: BorderRadius.md,
    borderWidth: 1,
    borderColor: Colors.border,
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    color: Colors.textPrimary,
    fontSize: 16,
  },
  contactCard: {
    backgroundColor: Colors.bgCard,
    borderRadius: BorderRadius.md,
    borderWidth: 1,
    borderColor: Colors.borderDim,
    padding: Spacing.md,
  },
  contactName: {
    ...Typography.subtitle,
  },
  contactPhone: {
    ...Typography.body,
    marginTop: 2,
  },
  armBtn: {
    marginTop: Spacing.xxl,
    paddingVertical: Spacing.lg,
    borderRadius: BorderRadius.lg,
    backgroundColor: Colors.emergency + '20',
    borderWidth: 2,
    borderColor: Colors.emergency,
    alignItems: 'center',
  },
  armBtnDisabled: {
    opacity: 0.5,
  },
  armBtnText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: Colors.emergency,
    letterSpacing: 2,
  },
  checkInBtn: {
    width: '100%',
    paddingVertical: Spacing.lg,
    borderRadius: BorderRadius.lg,
    backgroundColor: Colors.cyan + '20',
    borderWidth: 2,
    borderColor: Colors.cyan,
    alignItems: 'center',
    marginBottom: Spacing.md,
  },
  checkInBtnText: {
    fontSize: 16,
    fontWeight: 'bold',
    color: Colors.cyan,
    letterSpacing: 2,
  },
  disarmBtn: {
    paddingVertical: Spacing.md,
  },
  disarmBtnText: {
    ...Typography.mono,
    color: Colors.textSecondary,
  },
});
