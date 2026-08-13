/**
 * 5-second ambient audio recording engine.
 *
 * Uses expo-av to capture a short ambient audio clip that pairs with each
 * safety snapshot for additional context.
 */
import { Audio } from 'expo-av';
import * as FileSystem from 'expo-file-system';

class AudioService {
  private recording: Audio.Recording | null = null;

  async requestPermissions(): Promise<boolean> {
    const perm = await Audio.requestPermissionsAsync();
    return perm.status === 'granted';
  }

  /** Record a 5-second ambient clip and return base64. */
  async record5Seconds(): Promise<string | null> {
    try {
      await Audio.setAudioModeAsync({
        allowsRecordingIOS: true,
        playsInSilentModeIOS: true,
      });

      const { recording } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY,
      );
      this.recording = recording;

      await new Promise((resolve) => setTimeout(resolve, 5000));

      await recording.stopAndUnloadAsync();
      const uri = recording.getURI();
      this.recording = null;

      if (!uri) return null;

      const b64 = await FileSystem.readAsStringAsync(uri, {
        encoding: FileSystem.EncodingType.Base64,
      });
      return b64;
    } catch (err) {
      console.warn('[AudioService] Recording failed:', err);
      return null;
    }
  }

  async cancel(): Promise<void> {
    if (this.recording) {
      try {
        await this.recording.stopAndUnloadAsync();
      } catch {
        // ignore
      }
      this.recording = null;
    }
  }
}

export const audioService = new AudioService();
