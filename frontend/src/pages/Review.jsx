import { useState, useEffect } from 'react';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import { api } from '../api';

const FAILURE_TYPES = [
  'none',
  'hallucination',
  'retrieval_failure',
  'context_loss',
  'reasoning_failure',
  'prompt_failure',
];

export default function Review() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showResolved, setShowResolved] = useState(true);
  const [recalibrating, setRecalibrating] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const params = showResolved ? {} : { resolved: 'false' };
      const data = await api.getReviewQueue(params);
      setItems(data);
      setError(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [showResolved]);

  const submitLabel = async (id, label, notes) => {
    try {
      await api.labelReviewItem(id, { label, notes, reviewer: 'dashboard' });
      await load();
    } catch (err) {
      setError(err.message);
    }
  };

  const recalibrate = async () => {
    setRecalibrating(true);
    try {
      await api.recalibrateEvaluators();
    } catch (err) {
      setError(err.message);
    } finally {
      setRecalibrating(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Human Review Queue"
        description="Low-confidence and high-risk traces awaiting expert labels"
      />

      <div className="flex items-center justify-between mb-6">
        <label className="flex items-center gap-2 text-sm text-gray-400">
          <input
            type="checkbox"
            checked={showResolved}
            onChange={(e) => setShowResolved(e.target.checked)}
            className="rounded border-gray-700 bg-gray-900"
          />
          Show resolved
        </label>
        <button
          onClick={recalibrate}
          disabled={recalibrating}
          className="px-4 py-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm rounded-lg transition-colors"
        >
          {recalibrating ? 'Recalibrating...' : 'Recalibrate Evaluators'}
        </button>
      </div>

      {error && (
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-4 mb-6">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center h-64">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-500" />
        </div>
      ) : items.length === 0 ? (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-16 text-center">
          <p className="text-gray-500 text-sm">No items {showResolved ? '' : 'awaiting review'}</p>
        </div>
      ) : (
        <div className="space-y-4">
          {items.map((item) => (
            <ReviewCard key={item.id} item={item} onLabel={submitLabel} />
          ))}
        </div>
      )}
    </div>
  );
}

function ReviewCard({ item, onLabel }) {
  const [label, setLabel] = useState(item.label || 'none');
  const [notes, setNotes] = useState(item.notes || '');
  const resolved = !!item.resolved_at;

  return (
    <div className={`bg-gray-900 border rounded-xl p-5 ${resolved ? 'border-gray-800 opacity-70' : 'border-yellow-400/30'}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-xs text-gray-500 font-mono break-all">trace: {item.trace_id}</p>
          <p className="text-xs text-gray-500">created: {new Date(item.created_at).toLocaleString()}</p>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={item.reason} />
          <StatusBadge status={item.severity} />
          {item.risk_tier !== 'general' && <StatusBadge status={item.risk_tier} />}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-3">
        <div>
          <label className="block text-xs text-gray-500 mb-1">Ground-truth label</label>
          <select
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            disabled={resolved}
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100"
          >
            {FAILURE_TYPES.map((t) => (
              <option key={t} value={t}>{t}</option>
            ))}
          </select>
        </div>
        <div className="md:col-span-2">
          <label className="block text-xs text-gray-500 mb-1">Notes</label>
          <input
            type="text"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            disabled={resolved}
            placeholder="Reviewer notes..."
            className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100"
          />
        </div>
      </div>

      {!resolved ? (
        <button
          onClick={() => onLabel(item.id, label, notes)}
          className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm rounded-lg transition-colors"
        >
          Submit label
        </button>
      ) : (
        <p className="text-xs text-gray-500">
          Resolved {new Date(item.resolved_at).toLocaleString()} — label: {item.label}
        </p>
      )}
    </div>
  );
}
