import { useState, useEffect } from 'react';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import { api } from '../api';

export default function Traces() {
  const [traces, setTraces] = useState([]);
  const [selectedTrace, setSelectedTrace] = useState(null);
  const [traceId, setTraceId] = useState('');
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');

  useEffect(() => {
    loadTraces();
  }, [statusFilter]);

  const loadTraces = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = { limit: 50 };
      if (statusFilter) params.status = statusFilter;
      const data = await api.listTraces(params);
      setTraces(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const handleSelect = async (trace) => {
    setDetailLoading(true);
    try {
      const data = await api.getTrace(trace.id);
      setSelectedTrace(data);
    } catch {
      setSelectedTrace(trace);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleLookup = async (e) => {
    e.preventDefault();
    if (!traceId.trim()) return;
    setDetailLoading(true);
    setError(null);
    try {
      const data = await api.getTrace(traceId.trim());
      setSelectedTrace(data);
    } catch (err) {
      setError(err.message);
    } finally {
      setDetailLoading(false);
    }
  };

  const STATUS_OPTIONS = ['', 'pending', 'analyzed', 'failed', 'healed', 'awaiting_review'];

  return (
    <div>
      <PageHeader
        title="Trace Explorer"
        description="Inspect AI interaction traces, view prompts, responses, and evaluation results"
      />

      {/* Search + filter bar */}
      <div className="flex flex-col sm:flex-row gap-3 mb-6">
        <form onSubmit={handleLookup} className="flex gap-3 flex-1">
          <input
            type="text"
            value={traceId}
            onChange={(e) => setTraceId(e.target.value)}
            placeholder="Look up by trace ID..."
            className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
          <button
            type="submit"
            disabled={detailLoading}
            className="px-5 py-2 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Lookup
          </button>
        </form>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-gray-900 border border-gray-700 rounded-lg px-4 py-2 text-sm text-gray-100 focus:outline-none focus:border-brand-500"
        >
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>{s || 'All statuses'}</option>
          ))}
        </select>
      </div>

      {error && (
        <div className="bg-red-400/10 border border-red-400/20 rounded-xl p-4 mb-6">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Trace list */}
        <div className="lg:col-span-1 space-y-2 max-h-[75vh] overflow-y-auto pr-1">
          {loading ? (
            <div className="flex items-center justify-center h-32">
              <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-brand-500" />
            </div>
          ) : traces.length === 0 ? (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-8 text-center">
              <p className="text-gray-500 text-sm">No traces found</p>
            </div>
          ) : (
            traces.map((t) => (
              <button
                key={t.id}
                onClick={() => handleSelect(t)}
                className={`w-full text-left bg-gray-900 border rounded-xl p-4 transition-colors hover:border-brand-600 ${
                  selectedTrace?.id === t.id ? 'border-brand-500' : 'border-gray-800'
                }`}
              >
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-mono text-gray-400">{t.session_id}</span>
                  <StatusBadge status={t.status} />
                </div>
                <p className="text-sm text-gray-300 line-clamp-1 mb-2">{t.prompt}</p>
                <div className="flex items-center gap-3 text-xs text-gray-500">
                  <span>{t.model_used}</span>
                  <span>{t.latency_ms?.toFixed(0)} ms</span>
                  <span>{new Date(t.created_at).toLocaleTimeString()}</span>
                </div>
              </button>
            ))
          )}
        </div>

        {/* Trace detail panel */}
        <div className="lg:col-span-2">
          {detailLoading ? (
            <div className="flex items-center justify-center h-64">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-brand-500" />
            </div>
          ) : selectedTrace ? (
            <div className="space-y-4">
              {/* Header */}
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <div className="flex items-center justify-between mb-4">
                  <h3 className="text-lg font-semibold text-gray-100">Trace Details</h3>
                  <StatusBadge status={selectedTrace.status} />
                </div>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm">
                  <div>
                    <p className="text-gray-500">ID</p>
                    <p className="text-gray-200 font-mono text-xs mt-1 break-all">{selectedTrace.id}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Session</p>
                    <p className="text-gray-200 font-mono text-xs mt-1">{selectedTrace.session_id}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Model</p>
                    <p className="text-gray-200 mt-1">{selectedTrace.model_used}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Latency</p>
                    <p className="text-gray-200 mt-1">{selectedTrace.latency_ms?.toFixed(0)} ms</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Input Tokens</p>
                    <p className="text-gray-200 mt-1">{selectedTrace.token_count_input?.toLocaleString()}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Output Tokens</p>
                    <p className="text-gray-200 mt-1">{selectedTrace.token_count_output?.toLocaleString()}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Risk Tier</p>
                    <p className="text-gray-200 mt-1">{selectedTrace.risk_tier || 'general'}</p>
                  </div>
                  <div>
                    <p className="text-gray-500">Created</p>
                    <p className="text-gray-200 mt-1">{new Date(selectedTrace.created_at).toLocaleString()}</p>
                  </div>
                </div>
              </div>

              {/* Prompt */}
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 className="text-sm font-medium text-gray-400 mb-3">Prompt</h3>
                <pre className="text-sm text-gray-200 whitespace-pre-wrap bg-gray-950 rounded-lg p-4 border border-gray-800 max-h-48 overflow-y-auto">
                  {selectedTrace.prompt}
                </pre>
              </div>

              {/* Response */}
              <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                <h3 className="text-sm font-medium text-gray-400 mb-3">Response</h3>
                <pre className="text-sm text-gray-200 whitespace-pre-wrap bg-gray-950 rounded-lg p-4 border border-gray-800 max-h-48 overflow-y-auto">
                  {selectedTrace.response}
                </pre>
              </div>

              {/* Context documents */}
              {selectedTrace.context_documents && selectedTrace.context_documents.length > 0 && (
                <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
                  <h3 className="text-sm font-medium text-gray-400 mb-3">
                    Context Documents ({selectedTrace.context_documents.length})
                  </h3>
                  <div className="space-y-2">
                    {selectedTrace.context_documents.map((doc, i) => (
                      <div key={i} className="bg-gray-950 rounded-lg p-3 border border-gray-800">
                        <p className="text-xs text-gray-500 mb-1">Document {i + 1}</p>
                        <p className="text-sm text-gray-300">{doc}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          ) : (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-16 text-center">
              <p className="text-gray-500 text-sm">Select a trace from the list to view details</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
