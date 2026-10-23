import { useCallback, useEffect, useRef, useState } from 'react';

// Short confirmations after an action ("Saved"). One toast at a time; a new one replaces the old.
export function useToast() {
  const [toast, setToast] = useState(null);
  const timer = useRef(null);
  const show = useCallback((message, kind = 'ok') => {
    clearTimeout(timer.current);
    setToast({ message, kind, id: Date.now() });
    timer.current = setTimeout(() => setToast(null), kind === 'error' ? 5000 : 2200);
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);
  return [toast, show];
}

export function Toast({ toast }) {
  return (
    <div className="toast-region" role="status" aria-live="polite">
      {toast && <div key={toast.id} className={`toast ${toast.kind}`}>{toast.message}</div>}
    </div>
  );
}
