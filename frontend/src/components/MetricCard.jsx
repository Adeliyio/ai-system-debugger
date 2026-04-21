import clsx from 'clsx';

export default function MetricCard({ label, value, subtitle, trend, className }) {
  const isPositive = trend === 'up';
  const isNegative = trend === 'down';

  return (
    <div className={clsx('bg-gray-900 border border-gray-800 rounded-xl p-5', className)}>
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="mt-2 text-2xl font-bold text-gray-100">{value}</p>
      {subtitle && (
        <p
          className={clsx(
            'mt-1 text-xs',
            isPositive && 'text-green-400',
            isNegative && 'text-red-400',
            !isPositive && !isNegative && 'text-gray-500'
          )}
        >
          {subtitle}
        </p>
      )}
    </div>
  );
}
