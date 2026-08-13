/**
 * SOS confirmation modal — hold-to-activate emergency trigger.
 */
import React, { useRef, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Modal,
  TouchableOpacity,
  Animated,
  Vibration,
} from 'react-native';
import { Colors, Typography, Spacing, BorderRadius } from '../../theme';

interface Props {
  visible: boolean;
  onCancel: () => void;
  onConfirm: () => void;
  holdDurationMs?: number;
}

export function SosModal({ visible, onCancel, onConfirm, holdDurationMs = 2000 }: Props) {
  const progress = useRef(new Animated.Value(0)).current;
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const startHold = () => {
    Vibration.vibrate(100);
    Animated.timing(progress, {
      toValue: 1,
      duration: holdDurationMs,
      useNativeDriver: false,
    }).start();
    timerRef.current = setTimeout(() => {
      Vibration.vibrate([200, 100, 200, 100, 400]);
      onConfirm();
    }, holdDurationMs);
  };

  const cancelHold = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    Animated.timing(progress, {
      toValue: 0,
      duration: 200,
      useNativeDriver: false,
    }).start();
  };

  useEffect(() => {
    if (!visible) {
      cancelHold();
      progress.setValue(0);
    }
  }, [visible]);

  const widthInterpolate = progress.interpolate({
    inputRange: [0, 1],
    outputRange: ['0%', '100%'],
  });

  return (
    <Modal visible={visible} transparent animationType="fade" onRequestClose={onCancel}>
      <View style={styles.backdrop}>
        <View style={styles.modal}>
          <Text style={styles.title}>EMERGENCY SOS</Text>
          <Text style={styles.subtitle}>
            Hold the button for {holdDurationMs / 1000}s to dispatch
          </Text>

          <TouchableOpacity
            style={styles.holdBtn}
            onPressIn={startHold}
            onPressOut={cancelHold}
            activeOpacity={0.8}
          >
            <Animated.View style={[styles.holdProgress, { width: widthInterpolate }]} />
            <Text style={styles.holdText}>HOLD</Text>
          </TouchableOpacity>

          <View style={styles.warningBox}>
            <Text style={styles.warningText}>
              This will send your location and last capture to all emergency contacts.
            </Text>
          </View>

          <TouchableOpacity style={styles.cancelBtn} onPress={onCancel}>
            <Text style={styles.cancelText}>CANCEL</Text>
          </TouchableOpacity>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  backdrop: {
    flex: 1,
    backgroundColor: 'rgba(11,15,23,0.92)',
    justifyContent: 'center',
    alignItems: 'center',
  },
  modal: {
    width: '85%',
    backgroundColor: Colors.bgCard,
    borderRadius: BorderRadius.xl,
    borderWidth: 2,
    borderColor: Colors.emergency,
    padding: Spacing.xxl,
    alignItems: 'center',
  },
  title: {
    fontSize: 24,
    fontWeight: 'bold',
    color: Colors.emergency,
    letterSpacing: 2,
  },
  subtitle: {
    ...Typography.body,
    marginTop: Spacing.sm,
    marginBottom: Spacing.xl,
  },
  holdBtn: {
    width: 160,
    height: 160,
    borderRadius: 80,
    backgroundColor: Colors.bgInput,
    borderWidth: 3,
    borderColor: Colors.emergency,
    justifyContent: 'center',
    alignItems: 'center',
    overflow: 'hidden',
    marginBottom: Spacing.xl,
  },
  holdProgress: {
    position: 'absolute',
    top: 0,
    left: 0,
    bottom: 0,
    backgroundColor: Colors.emergency + '40',
  },
  holdText: {
    fontSize: 22,
    fontWeight: 'bold',
    color: Colors.emergency,
    letterSpacing: 3,
  },
  warningBox: {
    backgroundColor: Colors.bgInput,
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    width: '100%',
    marginBottom: Spacing.lg,
  },
  warningText: {
    ...Typography.caption,
    textAlign: 'center',
    color: Colors.textSecondary,
  },
  cancelBtn: {
    paddingVertical: Spacing.sm,
    paddingHorizontal: Spacing.xl,
  },
  cancelText: {
    ...Typography.mono,
    color: Colors.textSecondary,
  },
});
