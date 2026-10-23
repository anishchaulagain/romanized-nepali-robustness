// Placeholder shapes that match the real layouts, shown while data loads.
const Line = ({ w = '100%', h = '1rem', className = '' }) => (
  <span className={`sk ${className}`} style={{ width: w, height: h }} />
);

function Loading({ children, className = '' }) {
  return (
    <div className={className} aria-busy="true">
      <span className="sr-only">Loading</span>
      <div aria-hidden="true">{children}</div>
    </div>
  );
}

export function UnitSkeleton() {
  return (
    <Loading>
      <div className="unit-head"><Line w="9rem" h="1.6rem" /></div>
      {['70%', '55%', '62%'].map((w, i) => (
        <div key={i} className="segment">
          <Line w="5rem" h=".8rem" />
          <Line w={w} h="1.4rem" className="sk-gap" />
          <div className="bubble-row"><Line w="min(100%, 640px)" h="2.6rem" className="sk-bubble" /></div>
        </div>
      ))}
    </Loading>
  );
}

export function WriterSkeleton() {
  return (
    <Loading className="page">
      <div className="topbar">
        <span className="mark" />
        <Line w="7rem" />
        <Line w="10rem" h=".85rem" />
      </div>
      <UnitSkeleton />
    </Loading>
  );
}

export function AdminSkeleton() {
  return (
    <Loading>
      <div className="summary">
        {[0, 1, 2].map((i) => <div key={i}><Line w="4rem" h="1.7rem" /><Line w="8rem" h=".85rem" className="sk-gap" /></div>)}
      </div>
      <div className="slots">
        {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="slot"><Line w="4rem" h=".8rem" /><Line w="70%" className="sk-gap" /></div>)}
      </div>
      <div className="card">
        <Line w="6rem" h="1.1rem" />
        {[0, 1, 2, 3].map((i) => <Line key={i} h="1.1rem" className="sk-row" />)}
      </div>
    </Loading>
  );
}

export function PageError({ message }) {
  return <div className="center"><div className="error" role="alert">{message}</div></div>;
}
