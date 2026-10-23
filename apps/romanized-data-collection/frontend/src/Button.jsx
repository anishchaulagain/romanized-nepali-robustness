import { useRef, useState } from 'react';

// A button that shows a spinner and ignores clicks while its action is running.

export function Spinner() {
  return <span className="spinner" aria-hidden="true" />;
}

export function Button({ busy = false, disabled = false, children, ...rest }) {
  return (
    <button {...rest} disabled={disabled || busy} aria-busy={busy || undefined}>
      {busy && <Spinner />}
      {children}
    </button>
  );
}

// For one-off actions: onClick may return a promise; the button is busy until it settles.
export function AsyncButton({ onClick, ...rest }) {
  const [busy, setBusy] = useState(false);
  const running = useRef(false); // blocks a second click before the re-render lands
  async function handle(e) {
    if (running.current) return;
    running.current = true;
    setBusy(true);
    try {
      await onClick(e);
    } finally {
      running.current = false;
      setBusy(false);
    }
  }
  return <Button {...rest} busy={busy || rest.busy} onClick={handle} />;
}

// Shared lock for a group of buttons (e.g. Previous / Next): one action at a time, spinner on the one running.
export function useActionLock() {
  const [running, setRunning] = useState(null);
  const current = useRef(null);
  const run = async (name, fn) => {
    if (current.current) return undefined;
    current.current = name;
    setRunning(name);
    try {
      return await fn();
    } finally {
      current.current = null;
      setRunning(null);
    }
  };
  return [running, run];
}
