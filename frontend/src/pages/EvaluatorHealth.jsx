import { useState, useEffect } from 'react';
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip,
} from 'recharts';
import PageHeader from '../components/PageHeader';
import MetricCard from '../components/MetricCard';
import { api } from '../api';

const EVALUATOR_COLORS = {
  llm_judge: '#4c6ef5',
  embedding_similarity: '#22c55e',
  rule_based: '#eab308',
};

export default function EvaluatorHealth() {
  const [evaluators, setEvaluators] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.getEvaluatorHealth()
      .then(setEvaluators)
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
        <PageHeader title="Evaluator Health" description="Meta-evaluation metrics for each evaluator" />
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-6 text-center">
          <p className="text-red-400 text-sm">Failed to load: {error}</p>
          <p className="text-gray-500 text-xs mt-2">Ensure the backend is running at localhost:8000</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        title="Evaluator Health"
        description="Reliability metrics for the ensemble evaluation engine"
      />

      {/* Evaluator cards */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mb-8">
        {evaluators.map((ev) => (
          <div
            key={ev.evaluator_type}
            className="bg-gray-900 border border-gray-800 rounded-xl p-6"
          >
            <div className="flex items-center gap-3 mb-4">
              <div
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: EVALUATOR_COLORS[ev.evaluator_type] }}
              />
              <h3 className="text-sm font-semibold text-gray-200">
                {ev.evaluator_type.replace(/_/g, ' ')}
              </h3>
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-gray-500 text-xs">Accuracy</p>
                <p className="text-gray-100 font-semibold">{(ev.accuracy * 100).toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">Precision</p>
                <p className="text-gray-100 font-semibold">{(ev.precision * 100).toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">Recall</p>
                <p className="text-gray-100 font-semibold">{(ev.recall * 100).toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">F1 Score</p>
                <p className="text-gray-100 font-semibold">{(ev.f1_score * 100).toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">Agreement Rate</p>
                <p className="text-gray-100 font-semibold">{(ev.agreement_rate * 100).toFixed(1)}%</p>
              </div>
              <div>
                <p className="text-gray-500 text-xs">Total Evaluations</p>
                <p className="text-gray-100 font-semibold">{ev.total_evaluations.toLocaleString()}</p>
              </div>
            </div>

            {ev.last_calibrated && (
              <p className="text-xs text-gray-500 mt-4">
                Last calibrated: {new Date(ev.last_calibrated).toLocaleString()}
              </p>
            )}
          </div>
        ))}
      </div>

      {/* Radar chart comparison */}
      {evaluators.length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <h3 className="text-sm font-medium text-gray-400 mb-4">Evaluator Comparison</h3>
          <ResponsiveContainer width="100%" height={350}>
            <RadarChart
              data={[
                { metric: 'Accuracy', ...Object.fromEntries(evaluators.map(e => [e.evaluator_type, e.accuracy * 100])) },
                { metric: 'Precision', ...Object.fromEntries(evaluators.map(e => [e.evaluator_type, e.precision * 100])) },
                { metric: 'Recall', ...Object.fromEntries(evaluators.map(e => [e.evaluator_type, e.recall * 100])) },
                { metric: 'F1', ...Object.fromEntries(evaluators.map(e => [e.evaluator_type, e.f1_score * 100])) },
                { metric: 'Agreement', ...Object.fromEntries(evaluators.map(e => [e.evaluator_type, e.agreement_rate * 100])) },
              ]}
            >
              <PolarGrid stroke="#374151" />
              <PolarAngleAxis dataKey="metric" tick={{ fill: '#9ca3af', fontSize: 12 }} />
              <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fill: '#6b7280', fontSize: 10 }} />
              {evaluators.map((ev) => (
                <Radar
                  key={ev.evaluator_type}
                  name={ev.evaluator_type.replace(/_/g, ' ')}
                  dataKey={ev.evaluator_type}
                  stroke={EVALUATOR_COLORS[ev.evaluator_type]}
                  fill={EVALUATOR_COLORS[ev.evaluator_type]}
                  fillOpacity={0.15}
                />
              ))}
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '0.5rem' }}
                itemStyle={{ color: '#e5e7eb' }}
                formatter={(value) => `${value.toFixed(1)}%`}
              />
            </RadarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
