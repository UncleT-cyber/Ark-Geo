/**
 * Toast — brief notification that appears at the bottom of the screen and
 * auto-dismisses after a few seconds.  Used for "Copy Target Lat/Long" and
 * other transient UI confirmations.
 */
import React, { useEffect, useState, useCallback } from 'react';

export interface ToastState {
  id: number;
  message: string;
  variant: 'success' | 'warning' | 'error';
}

let toastId = 0;

export function useToast() {
  const [toasts, setToasts] = useState<ToastState[]>([]);

  const showToast = useCallback(
    (message: string, variant: ToastState['variant'] = 'success') => {
      const id = ++toastId;
      setToasts((prev) => [...prev, { id, message, variant }]);
      setTimeout(() => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
      }, 3000);
    },
    [],
  );

  const dismiss = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return { toasts, showToast, dismiss };
}

interface ToastContainerProps {
  toasts: ToastState[];
  onDismiss: (id: number) => void;
}

export function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
  return (
    <div className="toast-container">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`toast toast-${toast.variant}`}
          onClick={() => onDismiss(toast.id)}
        >
          <span className="toast-icon">
            {toast.variant === 'success' ? '✓' : toast.variant === 'warning' ? '⚠' : '✕'}
          </span>
          <span className="toast-message">{toast.message}</span>
        </div>
      ))}
    </div>
  );
}
