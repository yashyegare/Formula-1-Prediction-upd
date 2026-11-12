export default function StateMessage({
  title,
  message,
  retry,
}: {
  title: string;
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="ri-empty" role="status">
      <span className="ri-state-mark" aria-hidden="true">
        /
      </span>
      <h2>{title}</h2>
      <p>{message}</p>
      {retry && (
        <button className="ri-button ri-button--primary" onClick={retry}>
          Try again
        </button>
      )}
    </div>
  );
}
