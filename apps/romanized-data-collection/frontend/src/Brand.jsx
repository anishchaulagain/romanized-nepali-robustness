export function Mark() {
  return <span className="mark" aria-hidden="true"><b>क</b><i>ka</i></span>;
}

export default function Brand({ sub }) {
  return (
    <div className="brand">
      <Mark />
      <div>Lekhai<small>{sub}</small></div>
    </div>
  );
}
