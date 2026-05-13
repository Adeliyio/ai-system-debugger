import { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import PageHeader from '../components/PageHeader';
import { api } from '../api';

export default function Latency() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [windowHours, setWindowHours] = useState(24);

  useEffect(() => {
    setLoading(true);
    api.getLatencyMetrics({ window_hours: windowHours })
      .then(setData)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [windowHours]);

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
        <PageHeader title="Latency Breakdown" description="Per-component latency percentiles" />
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-6 text-center">
          <p className="text-red-400 text-sm">Failed to load: {error}</p>
        </div>
      </div>
    );
  }

  const chartData = (data?.components ?? []).map((c) => ({
    name: c.component,
    p50: c.p50_ms,
    p90: c.p90_ms,
    p99: c.p99_ms,
    samples: c.sample_count,
  }));

  return (
    <div>
      <PageHeader
        title="Latency Breakdown"
        description={`Per-component P50/P90/P99 over the last ${windowHours} hours`}
      />

      <div className="flex justify-end mb-4">
        <select
          value={windowHours}
          onChange={(e) => setWindowHours(parseInt(e.target.value))}
          className="bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100"
        >
          <option value={1}>Last 1h</option>
          <option value={24}>Last 24h</option>
          <option value={168}>Last 7d</option>
          <option value={720}>Last 30d</option>
        </select>
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-8">
        <h3 className="text-sm font-medium text-gray-400 mb-4">P50 / P90 / P99 by Component</h3>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={340}>
            <BarChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
              <YAxis
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                tickFormatter={(v) => `${v} ms`}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '0.5rem' }}
                itemStyle={{ color: '#e5e7eb' }}
                formatter={(value) => `${Number(value).toFixed(1)} ms`}
              />
              <Legend wrapperStyle={{ color: '#9ca3af', fontSize: 12 }} />
              <Bar dataKey="p50" name="P50" fill="#4c6ef5" radius={[4, 4, 0, 0]} />
              <Bar dataKey="p90" name="P90" fill="#eab308" radius={[4, 4, 0, 0]} />
              <Bar dataKey="p99" name="P99" fill="#ef4444" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500 text-sm text-center py-16">No latency data</p>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {chartData.map((c) => (
          <div key={c.name} className="bg-gray-900 border border-gray-800 rounded-xl p-5">
            <p className="text-sm font-medium text-gray-300 mb-3">{c.name}</p>
            <div className="grid grid-cols-3 gap-2 text-sm">
              <div>
                <p className="text-gray-500 text-xs">P50</p>
                <p className="text-gray-100 font-semibold">{c.p50.toFixed(1)} ms</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">P90</p>
                <p className="text-gray-100 font-semibold">{c.p90.toFixed(1)} ms</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">P99</p>
                <p className="text-gray-100 font-semibold">{c.p99.toFixed(1)} ms</p>
              </div>
            </div>
            <p className="text-xs text-gray-500 mt-3">samples: {c.samples}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
