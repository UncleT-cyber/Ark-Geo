/**
 * Mapbox GL reactive map renderer.
 *
 * Uses react-native-maps (MapView) to display the AI consensus location
 * with a confidence-radius circle overlay.
 */
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import MapView, { Circle, Marker, Region } from 'react-native-maps';
import { Colors, Typography, Spacing, BorderRadius } from '../../theme';
import { ConsensusResult } from '../../types';

interface Props {
  consensus: ConsensusResult | null;
  gpsLat?: number;
  gpsLon?: number;
}

export function MapRenderer({ consensus, gpsLat, gpsLon }: Props) {
  const lat = consensus?.estimated_latitude ?? gpsLat ?? 0;
  const lon = consensus?.estimated_longitude ?? gpsLon ?? 0;
  const radius = consensus?.search_radius_meters ?? 500;

  const region: Region = {
    latitude: lat,
    longitude: lon,
    latitudeDelta: 0.05,
    longitudeDelta: 0.05,
  };

  const confidenceColor = consensus
    ? consensus.confidence_score >= 0.7
      ? Colors.success
      : consensus.confidence_score >= 0.4
        ? Colors.warning
        : Colors.emergency
    : Colors.cyan;

  return (
    <View style={styles.container}>
      <MapView
        style={styles.map}
        initialRegion={region}
        region={region}
        showsUserLocation
        showsCompass
        mapType="hybrid"
      >
        <Marker coordinate={{ latitude: lat, longitude: lon }}>
          <View style={[styles.pin, { borderColor: confidenceColor }]} />
        </Marker>
        {consensus && (
          <Circle
            center={{ latitude: lat, longitude: lon }}
            radius={radius}
            strokeColor={confidenceColor}
            fillColor={confidenceColor + '20'}
            strokeWidth={2}
          />
        )}
      </MapView>
      {consensus && (
        <View style={styles.legend}>
          <Text style={styles.legendText}>
            AI ESTIMATE · R={Math.round(radius)}m · {Math.round(consensus.confidence_score * 100)}%
          </Text>
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    borderRadius: BorderRadius.lg,
    overflow: 'hidden',
    backgroundColor: Colors.bgDarkest,
  },
  map: {
    flex: 1,
  },
  pin: {
    width: 16,
    height: 16,
    borderRadius: 8,
    backgroundColor: Colors.cyan,
    borderWidth: 2,
  },
  legend: {
    position: 'absolute',
    bottom: Spacing.sm,
    left: Spacing.sm,
    backgroundColor: 'rgba(11,15,23,0.85)',
    borderRadius: BorderRadius.sm,
    paddingHorizontal: Spacing.sm,
    paddingVertical: Spacing.xs,
  },
  legendText: {
    ...Typography.mono,
    fontSize: 10,
  },
});
