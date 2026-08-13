/**
 * Silent capture & standard camera preview.
 *
 * Supports a "stealth mode" that captures without illuminating the screen
 * (screen brightness is set to minimum during capture).
 */
import React, { useRef, useEffect, useState } from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { CameraView, CameraType } from 'expo-camera';
import * as Haptics from 'expo-haptics';
import { Colors, Typography, Spacing, BorderRadius } from '../../theme';

interface Props {
  onCapture: (base64: string) => void;
  stealth?: boolean;
}

export function CameraPreview({ onCapture, stealth = false }: Props) {
  const cameraRef = useRef<CameraView>(null);
  const [facing, setFacing] = useState<CameraType>('back');
  const [ready, setReady] = useState(false);

  const takePicture = async () => {
    if (!cameraRef.current || !ready) return;

    if (!stealth) {
      await Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    }

    try {
      const photo = await cameraRef.current.takePictureAsync({
        base64: true,
        quality: 0.8,
        skipProcessing: false,
      });
      if (photo?.base64) {
        onCapture(photo.base64);
      }
    } catch (err) {
      console.warn('[CameraPreview] Capture failed:', err);
    }
  };

  const flip = () => {
    setFacing((f) => (f === 'back' ? 'front' : 'back'));
  };

  return (
    <View style={styles.container}>
      <CameraView
        ref={cameraRef}
        style={styles.camera}
        facing={facing}
        onCameraReady={() => setReady(true)}
        mode="picture"
      />
      {stealth && (
        <View style={styles.stealthOverlay} pointerEvents="none" />
      )}
      <View style={styles.controls}>
        <TouchableOpacity style={styles.flipBtn} onPress={flip}>
          <Text style={styles.flipText}>⇄</Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.captureBtn, !ready && styles.captureBtnDisabled]}
          onPress={takePicture}
          disabled={!ready}
        >
          <View style={styles.captureInner} />
        </TouchableOpacity>
        <View style={styles.flipBtn} />
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.bgDarkest,
    borderRadius: BorderRadius.lg,
    overflow: 'hidden',
  },
  camera: {
    flex: 1,
  },
  stealthOverlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.97)',
  },
  controls: {
    position: 'absolute',
    bottom: 0,
    left: 0,
    right: 0,
    flexDirection: 'row',
    justifyContent: 'space-around',
    alignItems: 'center',
    paddingVertical: Spacing.lg,
    backgroundColor: 'rgba(11,15,23,0.7)',
  },
  flipBtn: {
    width: 48,
    height: 48,
    justifyContent: 'center',
    alignItems: 'center',
  },
  flipText: {
    fontSize: 24,
    color: Colors.cyan,
  },
  captureBtn: {
    width: 70,
    height: 70,
    borderRadius: 35,
    borderWidth: 3,
    borderColor: Colors.cyan,
    justifyContent: 'center',
    alignItems: 'center',
  },
  captureBtnDisabled: {
    borderColor: Colors.textMuted,
  },
  captureInner: {
    width: 54,
    height: 54,
    borderRadius: 27,
    backgroundColor: Colors.cyan,
  },
});
