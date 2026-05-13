import { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from 'recharts';
import PageHeader from '../components/PageHeader';
import MetricCard from '../components/MetricCard';
import { api } from '../api';

const MODEL_COLORS = ['#4c6ef5', '#22c55e', '#eab308', '#ef4444', '#8b5cf6', '#6b7280'];

function formatUSD(value) {
  if (typeof value !== 'number') return '$0.00';
  if (value < 0.01) return `$${value.toFixed(4)}`;
  return `$${value.toFixed(2)}`;
}

export default function Costs() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [windowHours, setWindowHours] = useState(24);

  useEffect(() => {
    setLoading(true);
    api.getCostMetrics({ window_hours: windowHours })
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
        <PageHeader title="Cost Metrics" description="Spend across the LLM pipeline" />
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-6 text-center">
          <p className="text-red-400 text-sm">Failed to load: {error}</p>
        </div>
      </div>
    );
  }

  const modelBreakdown = data
    ? Object.entries(data.cost_by_model).map(([model, cost]) => ({ name: model, cost }))
    : [];

  return (
    <div>
      <PageHeader
        title="Cost Metrics"
        description={`Pipeline spend over the last ${windowHours} hours`}
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

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <MetricCard label="Total Spend" value={formatUSD(data?.total_cost_usd ?? 0)} />
        <MetricCard label="Model Cost" value={formatUSD(data?.model_cost_usd ?? 0)} />
        <MetricCard label="Evaluation Cost" value={formatUSD(data?.evaluation_cost_usd ?? 0)} />
        <MetricCard label="Cost per Trace" value={formatUSD(data?.cost_per_trace ?? 0)} />
      </div>

      <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
        <h3 className="text-sm font-medium text-gray-400 mb-4">Cost by Model</h3>
        {modelBreakdown.length > 0 ? (
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={modelBreakdown}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
              <YAxis
                tick={{ fill: '#9ca3af', fontSize: 11 }}
                tickFormatter={(v) => `$${v.toFixed(2)}`}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '0.5rem' }}
                itemStyle={{ color: '#e5e7eb' }}
                formatter={(value) => formatUSD(value)}
              />
              <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
                {modelBreakdown.map((_, i) => (
                  <Cell key={i} fill={MODEL_COLORS[i % MODEL_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <p className="text-gray-500 text-sm text-center py-16">No cost data yet</p>
        )}
      </div>
    </div>
  );
}
