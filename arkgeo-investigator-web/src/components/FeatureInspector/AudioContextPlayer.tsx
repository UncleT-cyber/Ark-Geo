/**
 * AudioContextPlayer — paired ambient audio playback with waveform display.
 *
 * Placeholder waveform visualizer; in production this would use Web Audio
 * API to decode and render the actual waveform.
 */
import React, { useState, useRef, useEffect } from 'react';

interface Props {
  audioBase64?: string | null;
}

export function AudioContextPlayer({ audioBase64 }: Props) {
  const [playing, setPlaying] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    if (audioBase64) {
      const binary = atob(audioBase64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: 'audio/mp4' });
      setAudioUrl(URL.createObjectURL(blob));
    } else {
      setAudioUrl(null);
    }
  }, [audioBase64]);

  const toggle = () => {
    if (!audioRef.current) return;
    if (playing) {
      audioRef.current.pause();
    } else {
      audioRef.current.play();
    }
    setPlaying(!playing);
  };

  if (!audioBase64) {
    return (
      <div className="panel-section">
        <div className="panel-title">AUDIO CONTEXT</div>
        <div className="panel-empty">No paired audio recording</div>
      </div>
    );
  }

  return (
    <div className="panel-section">
      <div className="panel-title">AUDIO CONTEXT PLAYER</div>
      <div className="audio-player">
        <button className="audio-play-btn" onClick={toggle}>
          {playing ? '⏸' : '▶'}
        </button>
        <div className="audio-waveform">
          {Array.from({ length: 40 }).map((_, i) => (
            <div
              key={i}
              className="audio-bar"
              style={{
                height: `${20 + Math.abs(Math.sin(i * 0.5)) * 60}%`,
                opacity: playing ? 0.9 : 0.4,
              }}
            />
          ))}
        </div>
        <span className="audio-duration mono">0:05</span>
      </div>
      <audio
        ref={audioRef}
        src={audioUrl || undefined}
        onEnded={() => setPlaying(false)}
      />
    </div>
  );
}
