import { useState, useEffect } from 'react';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import { api } from '../api';

export default function Traces() {
  const [traceId, setTraceId] = useState('');
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleLookup = async (e) => {
    e.preventDefault();
    if (!traceId.trim()) return;

    setLoading(true);
    setError(null);
    try {
      const data = await api.getTrace(traceId.trim());
      setTrace(data);
    } catch (err) {
      setError(err.message);
      setTrace(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Trace Explorer"
        description="Inspect AI interaction traces, view prompts, responses, and evaluation results"
      />

      {/* Search */}
      <form onSubmit={handleLookup} className="flex gap-3 mb-8">
        <input
          type="text"
          value={traceId}
          onChange={(e) => setTraceId(e.target.value)}
          placeholder="Enter trace ID..."
          className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
        />
        <button
          type="submit"
          disabled={loading}
          className="px-5 py-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {loading ? 'Loading...' : 'Lookup'}
        </button>
      </form>

      {error && (
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-4 mb-6">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Trace detail */}
      {trace && (
        <div className="space-y-6">
          {/* Header info */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-lg font-semibold text-gray-100">Trace Details</h3>
              <StatusBadge status={trace.status} />
            </div>

            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
              <div>
                <p className="text-gray-500">ID</p>
                <p className="text-gray-200 font-mono text-xs mt-1 break-all">{trace.id}</p>
              </div>
              <div>
                <p className="text-gray-500">Session</p>
                <p className="text-gray-200 font-mono text-xs mt-1">{trace.session_id}</p>
              </div>
              <div>
                <p className="text-gray-500">Model</p>
                <p className="text-gray-200 mt-1">{trace.model_used}</p>
              </div>
              <div>
                <p className="text-gray-500">Latency</p>
                <p className="text-gray-200 mt-1">{trace.latency_ms.toFixed(0)} ms</p>
              </div>
              <div>
                <p className="text-gray-500">Input Tokens</p>
                <p className="text-gray-200 mt-1">{trace.token_count_input.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-gray-500">Output Tokens</p>
                <p className="text-gray-200 mt-1">{trace.token_count_output.toLocaleString()}</p>
              </div>
              <div>
                <p className="text-gray-500">Created</p>
                <p className="text-gray-200 mt-1">{new Date(trace.created_at).toLocaleString()}</p>
              </div>
            </div>
          </div>

          {/* Prompt */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-medium text-gray-400 mb-3">Prompt</h3>
            <pre className="text-sm text-gray-200 whitespace-pre-wrap bg-gray-950 rounded-lg p-4 border border-gray-800 max-h-64 overflow-y-auto">
              {trace.prompt}
            </pre>
          </div>

          {/* Response */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-medium text-gray-400 mb-3">Response</h3>
            <pre className="text-sm text-gray-200 whitespace-pre-wrap bg-gray-950 rounded-lg p-4 border border-gray-800 max-h-64 overflow-y-auto">
              {trace.response}
            </pre>
          </div>

          {/* Context documents */}
          {trace.context_documents && trace.context_documents.length > 0 && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
              <h3 className="text-sm font-medium text-gray-400 mb-3">
                Context Documents ({trace.context_documents.length})
              </h3>
              <div className="space-y-2">
                {trace.context_documents.map((doc, i) => (
                  <div key={i} className="bg-gray-950 rounded-lg p-3 border border-gray-800">
                    <p className="text-xs text-gray-500 mb-1">Document {i + 1}</p>
                    <p className="text-sm text-gray-300 line-clamp-3">{doc}</p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Empty state */}
      {!trace && !error && (
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-16 text-center">
          <p className="text-gray-500 text-sm">Enter a trace ID to inspect its details</p>
        </div>
      )}
    </div>
  );
}
