import { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine, Cell,
} from 'recharts';
import { AlertTriangle, CheckCircle } from 'lucide-react';
import PageHeader from '../components/PageHeader';
import { api } from '../api';

export default function Drift() {
  const [driftData, setDriftData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getDrift()
      .then(setDriftData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-500" />
      </div>
    );
  }

  if (error) {
    return (
      <div>
        <PageHeader title="Drift Detection" description="Monitor metric drift across pipeline" />
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-6 text-center">
          <p className="text-red-400 text-sm">Failed to load: {error}</p>
          <p className="text-gray-500 text-xs mt-2">Ensure the backend is running at localhost:8000</p>
        </div>
      </div>
    );
  }

  const driftingCount = driftData.filter((d) => d.is_drifting).length;

  const chartData = driftData.map((d) => ({
    name: d.metric_name.replace(/_/g, ' '),
    current: d.current_value * 100,
    baseline: d.baseline_value * 100,
    drift: d.drift_magnitude * 100,
    isDrifting: d.is_drifting,
  }));

  return (
    <div>
      <PageHeader
        title="Drift Detection"
        description={`Monitoring ${driftData.length} metrics — ${driftData[0]?.window_days || 7} day window`}
      />

      {/* Alert banner */}
      {driftingCount > 0 ? (
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-4 mb-6 flex items-center gap-3">
          <AlertTriangle size={18} className="text-red-400 flex-shrink-0" />
          <p className="text-red-400 text-sm">
            {driftingCount} metric{driftingCount > 1 ? 's' : ''} drifting beyond threshold
          </p>
        </div>
      ) : (
        <div className="bg-green-400/10 border border-green-400/20 rounded-xl p-4 mb-6 flex items-center gap-3">
          <CheckCircle size={18} className="text-green-400 flex-shrink-0" />
          <p className="text-green-400 text-sm">All metrics within acceptable bounds</p>
        </div>
      )}

      {/* Drift cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
        {driftData.map((d) => (
          <div
            key={d.metric_name}
            className={`bg-gray-900 border rounded-xl p-5 ${
              d.is_drifting ? 'border-red-400/30' : 'border-gray-800'
            }`}
          >
            <div className="flex items-center justify-between mb-3">
              <p className="text-sm font-medium text-gray-300">
                {d.metric_name.replace(/_/g, ' ')}
              </p>
              {d.is_drifting ? (
                <AlertTriangle size={16} className="text-red-400" />
              ) : (
                <CheckCircle size={16} className="text-green-400" />
              )}
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-gray-500 text-xs">Current</p>
                <p className="text-gray-100 font-semibold">
                  {(d.current_value * 100).toFixed(2)}%
                </p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">Baseline</p>
                <p className="text-gray-100 font-semibold">
                  {(d.baseline_value * 100).toFixed(2)}%
                </p>
              </div>
            </div>

            <div className="mt-3 pt-3 border-t border-gray-800">
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-500">Drift magnitude</span>
                <span className={d.is_drifting ? 'text-red-400 font-medium' : 'text-gray-400'}>
                  {(d.drift_magnitude * 100).toFixed(2)}%
                </span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Comparison chart */}
      {chartData.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <h3 className="text-sm font-medium text-gray-400 mb-4">
            Current vs Baseline Comparison
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
              <YAxis
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                tickFormatter={(v) => `${v}%`}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '0.5rem' }}
                itemStyle={{ color: '#e5e7eb' }}
                formatter={(value) => `${value.toFixed(2)}%`}
              />
              <Bar dataKey="baseline" name="Baseline" fill="#6b7280" radius={[4, 4, 0, 0]} />
              <Bar dataKey="current" name="Current" radius={[4, 4, 0, 0]}>
                {chartData.map((entry, i) => (
                  <Cell
                    key={i}
                    fill={entry.isDrifting ? '#ef4444' : '#22c55e'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
