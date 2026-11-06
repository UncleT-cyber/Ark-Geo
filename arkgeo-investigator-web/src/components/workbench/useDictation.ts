import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';

interface SpeechCapture {
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error: string }) => void) | null;
}

export function useDictation(onTranscript: (text: string) => void, onNotice: (text: string) => void) {
  const [state, setState] = useState<'idle' | 'starting' | 'recording' | 'transcribing'>('idle');
  const [backendAvailable, setBackendAvailable] = useState(false);
  const active = useRef<AbortController>();
  const stop = useRef<() => void>();
  const cleanup = useRef<() => void>();

  useEffect(() => {
    const request = new AbortController();
    const check = () => {
      void api.transcriptionAvailable(request.signal).then(available => {
        if (!request.signal.aborted) setBackendAvailable(available);
      }).catch(() => {});
    };
    check();
    window.addEventListener('ark:byok-changed', check);
    return () => {
      window.removeEventListener('ark:byok-changed', check);
      request.abort();
      active.current?.abort();
      cleanup.current?.();
    };
  }, []);

  const toggle = async () => {
    if (active.current) {
      stop.current?.();
      return;
    }
    const request = new AbortController();
    active.current = request;
    setState('starting');
    onNotice('');
    const finish = () => {
      if (request.signal.aborted) return;
      active.current = undefined;
      cleanup.current = undefined;
      stop.current = undefined;
      setState('idle');
    };
    const deliver = (text: string) => {
      if (request.signal.aborted) return;
      if (text.trim()) onTranscript(text.trim());
      else onNotice('No speech detected. Try recording again.');
    };

    try {
      const browser = window as Window & {
        SpeechRecognition?: new () => SpeechCapture;
        webkitSpeechRecognition?: new () => SpeechCapture;
      };
      const Recognition = browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
      const mime = typeof MediaRecorder !== 'undefined'
        ? ['audio/webm', 'audio/mp4', 'audio/ogg'].find(type => MediaRecorder.isTypeSupported(type))
        : undefined;

      if (backendAvailable && mime && navigator.mediaDevices?.getUserMedia) {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const release = () => stream.getTracks().forEach(track => track.stop());
        if (request.signal.aborted) { release(); return; }
        cleanup.current = release;
        const recorder = new MediaRecorder(stream, { mimeType: mime });
        const chunks: Blob[] = [];
        const stopRecording = () => {
          if (recorder.state !== 'inactive') recorder.stop();
        };
        const timer = window.setTimeout(stopRecording, 60_000);
        cleanup.current = () => { window.clearTimeout(timer); stopRecording(); release(); };
        stop.current = stopRecording;
        recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
        recorder.onerror = () => {
          window.clearTimeout(timer);
          release();
          recorder.onstop = null;
          if (!request.signal.aborted) onNotice('Microphone recording failed.');
          finish();
        };
        recorder.onstop = async () => {
          window.clearTimeout(timer);
          release();
          stop.current = undefined;
          if (request.signal.aborted) return;
          setState('transcribing');
          try {
            if (!chunks.length) { deliver(''); return; }
            deliver(await api.transcribeAudio(new Blob(chunks, { type: recorder.mimeType || mime }), request.signal));
          } catch {
            if (!request.signal.aborted) onNotice('Transcription failed. Check the backend and OpenAI configuration.');
          } finally {
            finish();
          }
        };
        recorder.start();
        setState('recording');
      } else if (Recognition) {
        const capture = new Recognition();
        cleanup.current = () => capture.abort();
        stop.current = () => capture.stop();
        capture.onresult = event => deliver(Array.from(event.results, result => result[0].transcript).join(' '));
        capture.onend = finish;
        capture.onerror = event => {
          if (request.signal.aborted) return;
          onNotice(event.error === 'not-allowed' ? 'Allow microphone access in your browser and system settings.' :
            'Browser dictation failed. Check microphone access or configure OpenAI transcription.');
        };
        capture.start();
        setState('recording');
      } else {
        onNotice('Dictation requires browser speech recognition or a configured OpenAI key and microphone access.');
        finish();
      }
    } catch (error) {
      if (request.signal.aborted) return;
      cleanup.current?.();
      onNotice(error instanceof DOMException && error.name === 'NotAllowedError'
        ? 'Allow microphone access in your browser and system settings.'
        : 'Could not start the microphone. Check that an input device is connected.');
      finish();
    }
  };

  return { state, toggle, backendAvailable };
}
