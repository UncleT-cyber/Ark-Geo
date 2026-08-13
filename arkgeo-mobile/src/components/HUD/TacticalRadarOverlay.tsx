/**
 * TacticalRadarOverlay — animated radar sweep displayed during AI processing.
 */
import React, { useEffect, useRef } from 'react';
import { View, Text, StyleSheet, Animated, Easing } from 'react-native';
import { Colors, Typography, Spacing, BorderRadius } from '../../theme';

interface Props {
  active: boolean;
  confidence?: number;
}

export function TacticalRadarOverlay({ active, confidence }: Props) {
  const sweep = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    if (active) {
      const loop = Animated.loop(
        Animated.timing(sweep, {
          toValue: 1,
          duration: 2000,
          easing: Easing.linear,
          useNativeDriver: true,
        }),
      );
      loop.start();
      return () => loop.stop();
    }
  }, [active, sweep]);

  const rotate = sweep.interpolate({
    inputRange: [0, 1],
    outputRange: ['0deg', '360deg'],
  });

  if (!active) return null;

  return (
    <View style={styles.overlay}>
      <View style={styles.radarContainer}>
        <View style={styles.ring} />
        <View style={[styles.ring, { width: 100, height: 100 }]} />
        <View style={[styles.ring, { width: 50, height: 50 }]} />
        <Animated.View
          style={[
            styles.sweep,
            { transform: [{ rotate }] },
          ]}
        />
        <View style={styles.crosshairH} />
        <View style={styles.crosshairV} />
        <Text style={styles.scanningText}>SCANNING</Text>
        {confidence !== undefined && (
          <Text style={styles.confidenceText}>{Math.round(confidence * 100)}%</Text>
        )}
      </View>
    </View>
  );
}

const radarSize = 150;

const styles = StyleSheet.create({
  overlay: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: 'rgba(11, 15, 23, 0.85)',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 100,
  },
  radarContainer: {
    width: radarSize,
    height: radarSize,
    justifyContent: 'center',
    alignItems: 'center',
  },
  ring: {
    position: 'absolute',
    width: radarSize,
    height: radarSize,
    borderRadius: radarSize / 2,
    borderWidth: 1,
    borderColor: Colors.cyan + '40',
  },
  sweep: {
    position: 'absolute',
    width: radarSize / 2,
    height: radarSize / 2,
    borderTopLeftRadius: radarSize / 2,
    backgroundColor: Colors.cyan + '20',
    borderRightWidth: 2,
    borderRightColor: Colors.cyan,
    left: radarSize / 2 - 1,
    top: 0,
    transformOrigin: 'bottom right',
  },
  crosshairH: {
    position: 'absolute',
    width: radarSize,
    height: 1,
    backgroundColor: Colors.cyan + '30',
  },
  crosshairV: {
    position: 'absolute',
    width: 1,
    height: radarSize,
    backgroundColor: Colors.cyan + '30',
  },
  scanningText: {
    ...Typography.mono,
    fontSize: 10,
    marginTop: radarSize + Spacing.sm,
    position: 'absolute',
    bottom: -28,
  },
  confidenceText: {
    ...Typography.mono,
    fontSize: 16,
    color: Colors.cyanBright,
    position: 'absolute',
    bottom: -48,
  },
});
