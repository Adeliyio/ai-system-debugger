import { useState, useEffect } from 'react';
import {
  BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import PageHeader from '../components/PageHeader';
import MetricCard from '../components/MetricCard';
import { api } from '../api';

const STATUS_COLORS = {
  pending: '#eab308',
  analyzed: '#3b82f6',
  failed: '#ef4444',
  healed: '#22c55e',
};

const FAILURE_COLORS = ['#ef4444', '#f97316', '#eab308', '#8b5cf6', '#6b7280'];

export default function Dashboard() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getMetrics({ window_hours: 24 })
      .then(setMetrics)
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
        <PageHeader title="Dashboard" description="Pipeline overview — last 24 hours" />
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-6 text-center">
          <p className="text-red-400 text-sm">Failed to load metrics: {error}</p>
          <p className="text-gray-500 text-xs mt-2">Ensure the backend is running at localhost:8000</p>
        </div>
      </div>
    );
  }

  const statusData = metrics
    ? Object.entries(metrics.traces_by_status).map(([status, count]) => ({
        name: status,
        value: count,
      }))
    : [];

  const failureData = metrics
    ? Object.entries(metrics.top_failure_sources).map(([source, count]) => ({
        name: source,
        count,
      }))
    : [];

  const modelData = metrics
    ? Object.entries(metrics.model_usage).map(([model, count]) => ({
        name: model,
        count,
      }))
    : [];

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Pipeline overview — last 24 hours"
      />

      {/* Metric cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <MetricCard
          label="Total Traces"
          value={metrics?.total_traces?.toLocaleString() ?? '—'}
        />
        <MetricCard
          label="Failure Rate"
          value={metrics ? `${(metrics.failure_rate * 100).toFixed(1)}%` : '—'}
          trend={metrics?.failure_rate > 0.1 ? 'down' : 'up'}
          subtitle={metrics?.failure_rate > 0.1 ? 'Above threshold' : 'Healthy'}
        />
        <MetricCard
          label="P95 Latency"
          value={metrics ? `${metrics.p95_latency_ms.toFixed(0)} ms` : '—'}
        />
        <MetricCard
          label="Healing Success"
          value={metrics ? `${(metrics.healing_success_rate * 100).toFixed(1)}%` : '—'}
          trend={metrics?.healing_success_rate > 0.7 ? 'up' : 'down'}
          subtitle={metrics?.healing_success_rate > 0.7 ? 'On target' : 'Below target'}
        />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trace status pie chart */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-sm font-medium text-gray-400 mb-4">Traces by Status</h3>
          {statusData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={statusData}
                  cx="50%"
                  cy="50%"
                  innerRadius={50}
                  outerRadius={80}
                  dataKey="value"
                  stroke="none"
                >
                  {statusData.map((entry) => (
                    <Cell key={entry.name} fill={STATUS_COLORS[entry.name] || '#6b7280'} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '0.5rem' }}
                  itemStyle={{ color: '#e5e7eb' }}
                />
                <Legend
                  formatter={(value) => <span className="text-xs text-gray-400">{value}</span>}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-500 text-sm text-center py-16">No trace data</p>
          )}
        </div>

        {/* Top failure sources bar chart */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-sm font-medium text-gray-400 mb-4">Top Failure Sources</h3>
          {failureData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={failureData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis dataKey="name" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                <YAxis tick={{ fill: '#9ca3af', fontSize: 11 }} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '0.5rem' }}
                  itemStyle={{ color: '#e5e7eb' }}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {failureData.map((_, i) => (
                    <Cell key={i} fill={FAILURE_COLORS[i % FAILURE_COLORS.length]} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-500 text-sm text-center py-16">No failure data</p>
          )}
        </div>

        {/* Model usage bar chart */}
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5">
          <h3 className="text-sm font-medium text-gray-400 mb-4">Model Usage</h3>
          {modelData.length > 0 ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={modelData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
                <XAxis type="number" tick={{ fill: '#9ca3af', fontSize: 11 }} />
                <YAxis dataKey="name" type="category" tick={{ fill: '#9ca3af', fontSize: 11 }} width={100} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '0.5rem' }}
                  itemStyle={{ color: '#e5e7eb' }}
                />
                <Bar dataKey="count" fill="#4c6ef5" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <p className="text-gray-500 text-sm text-center py-16">No model data</p>
          )}
        </div>
      </div>
    </div>
  );
}
