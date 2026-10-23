export function Mark() {
  return <span className="mark" aria-hidden="true"><b>अ</b><i>a</i></span>;
}

export default function Brand({ sub }) {
  return (
    <div className="brand">
      <Mark />
      <div>Akshar<small>{sub}</small></div>
    </div>
  );
}
