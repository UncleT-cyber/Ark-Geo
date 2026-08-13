/**
 * Device GPS & EXIF parser wrapper.
 *
 * Uses expo-location to obtain current coordinates and expo-file-system +
 * a lightweight base64 encoder to prepare images for upload.
 */
import * as Location from 'expo-location';
import * as FileSystem from 'expo-file-system';
import { GpsFix, CellTowerInfo, DeviceTelemetry } from '../../types';

class LocationService {
  private lastKnownGps: GpsFix | null = null;

  async requestPermissions(): Promise<boolean> {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      const bg = await Location.requestBackgroundPermissionsAsync();
      return bg.status === 'granted';
    }
    return true;
  }

  async getCurrentGps(): Promise<GpsFix | null> {
    try {
      const loc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.Highest,
      });
      const fix: GpsFix = {
        lat: loc.coords.latitude,
        lon: loc.coords.longitude,
        altitude: loc.coords.altitude ?? undefined,
        timestamp: Date.now(),
      };
      this.lastKnownGps = fix;
      return fix;
    } catch (err) {
      console.warn('[LocationService] GPS fetch failed:', err);
      return this.lastKnownGps;
    }
  }

  get lastKnown(): GpsFix | null {
    return this.lastKnownGps;
  }

  /**
   * Build the device telemetry payload.
   * Cell tower and Wi-Fi BSSID APIs are not available in the Expo SDK
   * without a native module, so they are left as null and populated by
   * a custom native module if available.
   */
  async buildTelemetry(): Promise<DeviceTelemetry> {
    const gps = await this.getCurrentGps();
    return {
      last_known_outdoor_gps: gps,
      connected_cell_tower: null,
      nearby_wifi_bssids: [],
    };
  }

  /** Read a file and return base64 (without data-URI prefix). */
  async fileToBase64(uri: string): Promise<string> {
    const result = await FileSystem.readAsStringAsync(uri, {
      encoding: FileSystem.EncodingType.Base64,
    });
    return result;
  }
}

export const locationService = new LocationService();
