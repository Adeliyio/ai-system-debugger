import { useState } from 'react';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import { api } from '../api';

export default function Healing() {
  const [traceId, setTraceId] = useState('');
  const [evaluationId, setEvaluationId] = useState('');
  const [rcaId, setRcaId] = useState('');
  const [step, setStep] = useState('rca'); // rca -> heal -> compare
  const [rcaResult, setRcaResult] = useState(null);
  const [healingResult, setHealingResult] = useState(null);
  const [comparisonResult, setComparisonResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleRCA = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const result = await api.runRCA({ trace_id: traceId, evaluation_id: evaluationId });
      setRcaResult(result);
      setRcaId(result.id);
      setStep('heal');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleHeal = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.applyFix({ trace_id: traceId, rca_id: rcaId });
      setHealingResult(result);
      setStep('compare');
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleCompare = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.compareResponses({
        trace_id: traceId,
        healing_id: healingResult.id,
      });
      setComparisonResult(result);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const resetAll = () => {
    setStep('rca');
    setRcaResult(null);
    setHealingResult(null);
    setComparisonResult(null);
    setError(null);
  };

  return (
    <div>
      <PageHeader
        title="Self-Healing Pipeline"
        description="Run root cause analysis and apply automated fixes to failed traces"
      />

      {error && (
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-4 mb-6">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Step indicator */}
      <div className="flex items-center gap-2 mb-8">
        {['rca', 'heal', 'compare'].map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <div
              className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold ${
                step === s
                  ? 'bg-brand-600 text-white'
                  : i < ['rca', 'heal', 'compare'].indexOf(step)
                  ? 'bg-green-600 text-white'
                  : 'bg-gray-800 text-gray-500'
              }`}
            >
              {i + 1}
            </div>
            <span className={`text-sm ${step === s ? 'text-gray-100' : 'text-gray-500'}`}>
              {s === 'rca' ? 'Root Cause Analysis' : s === 'heal' ? 'Apply Fix' : 'Compare'}
            </span>
            {i < 2 && <div className="w-8 h-px bg-gray-700 mx-1" />}
          </div>
        ))}
      </div>

      {/* Step 1: RCA input */}
      {step === 'rca' && (
        <form onSubmit={handleRCA} className="bg-gray-900 border border-gray-800 rounded-xl p-6">
          <h3 className="text-sm font-medium text-gray-300 mb-4">Identify Root Cause</h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
            <div>
              <label className="block text-xs text-gray-500 mb-1">Trace ID</label>
              <input
                type="text"
                value={traceId}
                onChange={(e) => setTraceId(e.target.value)}
                placeholder="Enter trace ID..."
                className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-brand-500"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Evaluation ID</label>
              <input
                type="text"
                value={evaluationId}
                onChange={(e) => setEvaluationId(e.target.value)}
                placeholder="Enter evaluation ID..."
                className="w-full bg-gray-950 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-brand-500"
              />
            </div>
          </div>
          <button
            type="submit"
            disabled={loading || !traceId || !evaluationId}
            className="px-5 py-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {loading ? 'Analyzing...' : 'Run RCA'}
          </button>
        </form>
      )}

      {/* RCA Results */}
      {rcaResult && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-gray-300">RCA Results</h3>
            <StatusBadge status={rcaResult.primary_source} />
          </div>
          <p className="text-sm text-gray-300 mb-4">{rcaResult.analysis_summary}</p>
          <div className="space-y-2">
            {rcaResult.findings.map((finding, i) => (
              <div key={i} className="bg-gray-950 rounded-lg p-3 border border-gray-800">
                <div className="flex items-center justify-between mb-1">
                  <span className="text-xs font-medium text-gray-400">{finding.source}</span>
                  <span className="text-xs text-gray-500">
                    Confidence: {(finding.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <p className="text-sm text-gray-300">{finding.evidence}</p>
                <p className="text-xs text-brand-400 mt-1">{finding.suggested_action}</p>
              </div>
            ))}
          </div>
          {step === 'heal' && (
            <button
              onClick={handleHeal}
              disabled={loading}
              className="mt-4 px-5 py-2 bg-green-600 hover:bg-green-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {loading ? 'Healing...' : 'Apply Self-Healing Fix'}
            </button>
          )}
        </div>
      )}

      {/* Healing Results */}
      {healingResult && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-medium text-gray-300">Healing Results</h3>
            <div className="flex items-center gap-2">
              <StatusBadge status={healingResult.strategy.replace('_', ' ')} />
              <StatusBadge status={healingResult.regression_passed ? 'passed' : 'not passed'} />
            </div>
          </div>

          <div className="grid grid-cols-3 gap-4 mb-4 text-sm">
            <div>
              <p className="text-gray-500">Strategy</p>
              <p className="text-gray-200 mt-1">{healingResult.strategy.replace(/_/g, ' ')}</p>
            </div>
            <div>
              <p className="text-gray-500">Attempts</p>
              <p className="text-gray-200 mt-1">{healingResult.attempt_number}</p>
            </div>
            <div>
              <p className="text-gray-500">Improvement</p>
              <p className="text-gray-200 mt-1">
                {(healingResult.improvement_score * 100).toFixed(1)}%
              </p>
            </div>
          </div>

          <div className="bg-gray-950 rounded-lg p-4 border border-gray-800">
            <p className="text-xs text-gray-500 mb-2">Repaired Response</p>
            <pre className="text-sm text-gray-200 whitespace-pre-wrap max-h-48 overflow-y-auto">
              {healingResult.repaired_response}
            </pre>
          </div>

          {step === 'compare' && !comparisonResult && (
            <button
              onClick={handleCompare}
              disabled={loading}
              className="mt-4 px-5 py-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {loading ? 'Comparing...' : 'View Side-by-Side Comparison'}
            </button>
          )}
        </div>
      )}

      {/* Comparison Results */}
      {comparisonResult && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-6 mb-6">
          <h3 className="text-sm font-medium text-gray-300 mb-4">Side-by-Side Comparison</h3>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-red-400">Original</p>
                <span className="text-xs text-gray-500">
                  Score: {(comparisonResult.original_score * 100).toFixed(1)}%
                </span>
              </div>
              <pre className="text-sm text-gray-300 whitespace-pre-wrap bg-gray-950 rounded-lg p-4 border border-red-900/30 max-h-64 overflow-y-auto">
                {comparisonResult.original_response}
              </pre>
            </div>
            <div>
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium text-green-400">Repaired</p>
                <span className="text-xs text-gray-500">
                  Score: {(comparisonResult.repaired_score * 100).toFixed(1)}%
                </span>
              </div>
              <pre className="text-sm text-gray-300 whitespace-pre-wrap bg-gray-950 rounded-lg p-4 border border-green-900/30 max-h-64 overflow-y-auto">
                {comparisonResult.repaired_response}
              </pre>
            </div>
          </div>
          <div className="mt-4 flex items-center gap-4 text-sm">
            <span className="text-gray-400">
              Improvement: <strong className="text-green-400">{(comparisonResult.improvement * 100).toFixed(1)}%</strong>
            </span>
            <span className="text-gray-400">
              Strategy: <strong className="text-brand-400">{comparisonResult.strategy_used.replace(/_/g, ' ')}</strong>
            </span>
          </div>
        </div>
      )}

      {/* Reset button */}
      {step !== 'rca' && (
        <button
          onClick={resetAll}
          className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-lg transition-colors"
        >
          Start New Analysis
        </button>
      )}
    </div>
  );
}
