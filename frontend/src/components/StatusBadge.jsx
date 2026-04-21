import clsx from 'clsx';

const variants = {
  pending: 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20',
  analyzed: 'bg-blue-400/10 text-blue-400 border-blue-400/20',
  failed: 'bg-red-400/10 text-red-400 border-red-400/20',
  healed: 'bg-green-400/10 text-green-400 border-green-400/20',
  low: 'bg-green-400/10 text-green-400 border-green-400/20',
  medium: 'bg-yellow-400/10 text-yellow-400 border-yellow-400/20',
  high: 'bg-orange-400/10 text-orange-400 border-orange-400/20',
  critical: 'bg-red-400/10 text-red-400 border-red-400/20',
  passed: 'bg-green-400/10 text-green-400 border-green-400/20',
  'not passed': 'bg-red-400/10 text-red-400 border-red-400/20',
};

export default function StatusBadge({ status }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center px-2 py-0.5 rounded-md text-xs font-medium border',
        variants[status] || 'bg-gray-400/10 text-gray-400 border-gray-400/20'
      )}
    >
      {status}
    </span>
  );
}
