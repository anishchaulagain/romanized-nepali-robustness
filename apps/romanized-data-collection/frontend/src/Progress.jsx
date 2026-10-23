export default function Progress({ pct, label, big = false }) {
  return (
    <div className={`progress-track ${big ? 'big' : ''} ${pct >= 100 ? 'full' : ''}`} role="progressbar"
      aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
      <div className="progress-fill" style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  );
}
