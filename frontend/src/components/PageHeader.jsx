export default function PageHeader({ title, description }) {
  return (
    <div className="mb-6">
      <h1 className="text-2xl font-bold text-gray-100">{title}</h1>
      {description && <p className="mt-1 text-sm text-gray-400">{description}</p>}
    </div>
  );
}
