import { useState, useEffect, useRef } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Cell,
} from 'recharts';
import {
  Play, CheckCircle, XCircle, Clock, AlertTriangle,
  Server, Database, Cpu, Activity,
} from 'lucide-react';
import PageHeader from '../components/PageHeader';
import StatusBadge from '../components/StatusBadge';
import MetricCard from '../components/MetricCard';
import { api } from '../api';

// Pipeline step status indicator
function StepStatus({ step, status, duration }) {
  const icons = {
    idle: <Clock size={16} className="text-gray-500" />,
    running: <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-brand-400" />,
    success: <CheckCircle size={16} className="text-green-400" />,
    error: <XCircle size={16} className="text-red-400" />,
  };

  return (
    <div className={`flex items-center gap-3 px-4 py-3 rounded-lg border ${
      status === 'running' ? 'bg-brand-600/10 border-brand-600/30' :
      status === 'success' ? 'bg-green-400/5 border-green-400/20' :
      status === 'error' ? 'bg-red-400/5 border-red-400/20' :
      'bg-gray-900 border-gray-800'
    }`}>
      {icons[status]}
      <div className="flex-1">
        <p className="text-sm text-gray-200">{step}</p>
        {duration && <p className="text-xs text-gray-500">{duration}ms</p>}
      </div>
    </div>
  );
}

export default function Admin() {
  // System health
  const [systemHealth, setSystemHealth] = useState(null);
  const [healthLoading, setHealthLoading] = useState(true);

  // Trace submission
  const [traceForm, setTraceForm] = useState({
    session_id: '',
    prompt: '',
    response: '',
    model_used: 'gpt-4o',
    context_documents: '',
    latency_ms: '',
    token_count_input: '',
    token_count_output: '',
  });

  // Pipeline execution state
  const [pipelineState, setPipelineState] = useState({
    trace: { status: 'idle', data: null, duration: null },
    evaluation: { status: 'idle', data: null, duration: null },
    rca: { status: 'idle', data: null, duration: null },
    healing: { status: 'idle', data: null, duration: null },
  });

  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineLog, setPipelineLog] = useState([]);
  const logRef = useRef(null);

  // Scroll log to bottom on new entries
  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [pipelineLog]);

  // Check system health on mount
  useEffect(() => {
    checkHealth();
  }, []);

  const addLog = (message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString();
    setPipelineLog((prev) => [...prev, { timestamp, message, type }]);
  };

  const checkHealth = async () => {
    setHealthLoading(true);
    try {
      const health = await api.getHealth();
      setSystemHealth({ ...health, backend: true });
      addLog('Backend health check passed', 'success');
    } catch {
      setSystemHealth({ backend: false });
      addLog('Backend unreachable — ensure uvicorn is running on port 8000', 'error');
    }
    setHealthLoading(false);
  };

  const updateStep = (step, updates) => {
    setPipelineState((prev) => ({
      ...prev,
      [step]: { ...prev[step], ...updates },
    }));
  };

  // Run the full pipeline: Submit -> Evaluate -> RCA -> Heal
  const runFullPipeline = async () => {
    if (pipelineRunning) return;
    setPipelineRunning(true);
    setPipelineLog([]);
    setPipelineState({
      trace: { status: 'idle', data: null, duration: null },
      evaluation: { status: 'idle', data: null, duration: null },
      rca: { status: 'idle', data: null, duration: null },
      healing: { status: 'idle', data: null, duration: null },
    });

    try {
      // Step 1: Submit trace
      addLog('Submitting trace...', 'info');
      updateStep('trace', { status: 'running' });
      const t0 = performance.now();

      const contextDocs = traceForm.context_documents
        ? traceForm.context_documents.split('\n').filter(Boolean)
        : [];

      const traceResult = await api.submitTrace({
        session_id: traceForm.session_id || `session-${Date.now()}`,
        prompt: traceForm.prompt,
        response: traceForm.response,
        model_used: traceForm.model_used,
        context_documents: contextDocs,
        latency_ms: parseFloat(traceForm.latency_ms) || 0,
        token_count_input: parseInt(traceForm.token_count_input) || 0,
        token_count_output: parseInt(traceForm.token_count_output) || 0,
      });

      const traceDuration = Math.round(performance.now() - t0);
      updateStep('trace', { status: 'success', data: traceResult, duration: traceDuration });
      addLog(`Trace captured: ${traceResult.id} (${traceDuration}ms)`, 'success');

      // Step 2: Evaluate
      addLog('Running ensemble evaluation (LLM judge + embeddings + rules)...', 'info');
      updateStep('evaluation', { status: 'running' });
      const t1 = performance.now();

      const evalResult = await api.analyzeTrace({ trace_id: traceResult.id });
      const evalDuration = Math.round(performance.now() - t1);

      updateStep('evaluation', { status: 'success', data: evalResult, duration: evalDuration });
      addLog(
        `Evaluation complete: ${evalResult.passed ? 'PASSED' : 'FAILED'} ` +
        `(score: ${evalResult.overall_score}, severity: ${evalResult.severity}, ` +
        `agreement: ${evalResult.agreement_count}/3) — ${evalDuration}ms`,
        evalResult.passed ? 'success' : 'warning'
      );

      // Log individual verdicts
      evalResult.verdicts.forEach((v) => {
        addLog(
          `  ${v.evaluator_type}: ${v.passed ? 'PASS' : 'FAIL'} (${v.score.toFixed(2)}) — ${v.reasoning}`,
          v.passed ? 'info' : 'warning'
        );
      });

      // Step 3: RCA (only if evaluation failed)
      if (evalResult.failure_detected) {
        addLog('Failure detected — running root cause analysis...', 'info');
        updateStep('rca', { status: 'running' });
        const t2 = performance.now();

        const rcaResult = await api.runRCA({
          trace_id: traceResult.id,
          evaluation_id: evalResult.id,
        });
        const rcaDuration = Math.round(performance.now() - t2);

        updateStep('rca', { status: 'success', data: rcaResult, duration: rcaDuration });
        addLog(
          `RCA complete: primary source = ${rcaResult.primary_source} — ${rcaDuration}ms`,
          'success'
        );
        rcaResult.findings.forEach((f) => {
          addLog(
            `  [${f.source}] confidence: ${(f.confidence * 100).toFixed(0)}% — ${f.evidence}`,
            'info'
          );
        });
        addLog(`Summary: ${rcaResult.analysis_summary}`, 'info');

        // Step 4: Self-healing
        addLog('Applying self-healing fix via LangGraph pipeline...', 'info');
        updateStep('healing', { status: 'running' });
        const t3 = performance.now();

        const healResult = await api.applyFix({
          trace_id: traceResult.id,
          rca_id: rcaResult.id,
        });
        const healDuration = Math.round(performance.now() - t3);

        updateStep('healing', { status: 'success', data: healResult, duration: healDuration });
        addLog(
          `Healing complete: strategy = ${healResult.strategy}, ` +
          `regression ${healResult.regression_passed ? 'PASSED' : 'FAILED'}, ` +
          `improvement: ${(healResult.improvement_score * 100).toFixed(1)}% — ${healDuration}ms`,
          healResult.regression_passed ? 'success' : 'warning'
        );
      } else {
        addLog('Evaluation passed — no healing needed.', 'success');
        updateStep('rca', { status: 'idle' });
        updateStep('healing', { status: 'idle' });
      }

      addLog('Pipeline execution complete.', 'success');
    } catch (err) {
      addLog(`Pipeline error: ${err.message}`, 'error');
      // Mark current running step as error
      setPipelineState((prev) => {
        const updated = { ...prev };
        for (const step of ['trace', 'evaluation', 'rca', 'healing']) {
          if (updated[step].status === 'running') {
            updated[step] = { ...updated[step], status: 'error' };
          }
        }
        return updated;
      });
    }

    setPipelineRunning(false);
  };

  // Load a preset scenario
  const loadPreset = (preset) => {
    const presets = {
      passing: {
        session_id: `eval-${Date.now()}`,
        prompt: 'What are the key differences between REST and GraphQL APIs?',
        response: 'REST uses fixed endpoints with HTTP methods where each endpoint returns a predetermined data structure. GraphQL provides a single endpoint with a query language that lets clients request exactly the data they need. REST can lead to over-fetching or under-fetching, while GraphQL allows precise field selection.',
        model_used: 'gpt-4o',
        context_documents: 'REST (Representational State Transfer) is an architectural style for distributed systems using standard HTTP methods.\nGraphQL is a query language for APIs developed by Facebook that gives clients the power to ask for exactly what they need.',
        latency_ms: '1250',
        token_count_input: '45',
        token_count_output: '96',
      },
      failing_refusal: {
        session_id: `eval-${Date.now()}`,
        prompt: 'Explain how a transformer model processes input text step by step.',
        response: "I don't have access to that information.",
        model_used: 'llama3.2',
        context_documents: '',
        latency_ms: '89',
        token_count_input: '52',
        token_count_output: '9',
      },
      failing_hallucination: {
        session_id: `eval-${Date.now()}`,
        prompt: 'Based on the provided report, what was the companys revenue growth in Q3?',
        response: 'According to the report, revenue grew 47% to $2.3 billion, with cloud services growing 62%. The EBITDA margin expanded to 34% and free cash flow increased by $890 million year-over-year.',
        model_used: 'gpt-4o',
        context_documents: 'Q3 Financial Highlights: Total revenue reached $2.3B, up 47% YoY. Cloud services revenue grew 62% to $1.4B.',
        latency_ms: '1890',
        token_count_input: '128',
        token_count_output: '87',
      },
    };
    setTraceForm(presets[preset]);
    addLog(`Loaded preset: ${preset}`, 'info');
  };

  return (
    <div>
      <PageHeader
        title="Admin & Evaluation Console"
        description="End-to-end pipeline execution, system monitoring, and evaluation testing"
      />

      {/* System Status Bar */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-8">
        <MetricCard
          label="Backend"
          value={healthLoading ? '...' : systemHealth?.backend ? 'Online' : 'Offline'}
          subtitle={systemHealth?.version ? `v${systemHealth.version}` : null}
          trend={systemHealth?.backend ? 'up' : 'down'}
        />
        <MetricCard
          label="API Version"
          value={systemHealth?.version || '—'}
        />
        <MetricCard
          label="Pipeline Status"
          value={pipelineRunning ? 'Running' : 'Idle'}
          trend={pipelineRunning ? 'up' : null}
        />
        <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 flex items-center justify-center">
          <button
            onClick={checkHealth}
            className="px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-lg transition-colors"
          >
            Refresh Status
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Left: Trace Submission Form */}
        <div className="space-y-6">
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-gray-300">Submit Trace for Evaluation</h3>
              <div className="flex gap-2">
                <button
                  onClick={() => loadPreset('passing')}
                  className="px-2 py-1 text-xs bg-green-400/10 text-green-400 border border-green-400/20 rounded hover:bg-green-400/20 transition-colors"
                >
                  Passing
                </button>
                <button
                  onClick={() => loadPreset('failing_refusal')}
                  className="px-2 py-1 text-xs bg-red-400/10 text-red-400 border border-red-400/20 rounded hover:bg-red-400/20 transition-colors"
                >
                  Refusal
                </button>
                <button
                  onClick={() => loadPreset('failing_hallucination')}
                  className="px-2 py-1 text-xs bg-yellow-400/10 text-yellow-400 border border-yellow-400/20 rounded hover:bg-yellow-400/20 transition-colors"
                >
                  Hallucination
                </button>
              </div>
            </div>

            <div className="space-y-3">
              <div>
                <label className="block text-xs text-gray-500 mb-1">Prompt</label>
                <textarea
                  value={traceForm.prompt}
                  onChange={(e) => setTraceForm({ ...traceForm, prompt: e.target.value })}
                  rows={3}
                  className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-brand-500"
                  placeholder="The prompt sent to the LLM..."
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Response</label>
                <textarea
                  value={traceForm.response}
                  onChange={(e) => setTraceForm({ ...traceForm, response: e.target.value })}
                  rows={3}
                  className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-brand-500"
                  placeholder="The LLM-generated response..."
                />
              </div>
              <div>
                <label className="block text-xs text-gray-500 mb-1">Context Documents (one per line)</label>
                <textarea
                  value={traceForm.context_documents}
                  onChange={(e) => setTraceForm({ ...traceForm, context_documents: e.target.value })}
                  rows={2}
                  className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-brand-500"
                  placeholder="Retrieved context documents..."
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Model</label>
                  <select
                    value={traceForm.model_used}
                    onChange={(e) => setTraceForm({ ...traceForm, model_used: e.target.value })}
                    className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-brand-500"
                  >
                    <option value="gpt-4o">GPT-4o</option>
                    <option value="llama3.2">Llama 3.2</option>
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Latency (ms)</label>
                  <input
                    type="number"
                    value={traceForm.latency_ms}
                    onChange={(e) => setTraceForm({ ...traceForm, latency_ms: e.target.value })}
                    className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-brand-500"
                    placeholder="0"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Input Tokens</label>
                  <input
                    type="number"
                    value={traceForm.token_count_input}
                    onChange={(e) => setTraceForm({ ...traceForm, token_count_input: e.target.value })}
                    className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-brand-500"
                    placeholder="0"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Output Tokens</label>
                  <input
                    type="number"
                    value={traceForm.token_count_output}
                    onChange={(e) => setTraceForm({ ...traceForm, token_count_output: e.target.value })}
                    className="w-full bg-gray-950 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 focus:outline-none focus:border-brand-500"
                    placeholder="0"
                  />
                </div>
              </div>

              <button
                onClick={runFullPipeline}
                disabled={pipelineRunning || !traceForm.prompt || !traceForm.response}
                className="w-full flex items-center justify-center gap-2 px-5 py-3 bg-brand-600 hover:bg-brand-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
              >
                <Play size={16} />
                {pipelineRunning ? 'Pipeline Running...' : 'Run Full Pipeline'}
              </button>
            </div>
          </div>

          {/* Pipeline Steps Visualization */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <h3 className="text-sm font-medium text-gray-300 mb-4">Pipeline Execution</h3>
            <div className="space-y-2">
              <StepStatus
                step="1. Trace Capture & Instrumentation"
                status={pipelineState.trace.status}
                duration={pipelineState.trace.duration}
              />
              <div className="flex justify-center">
                <div className="w-px h-4 bg-gray-700" />
              </div>
              <StepStatus
                step="2. Ensemble Evaluation (LLM + Embeddings + Rules)"
                status={pipelineState.evaluation.status}
                duration={pipelineState.evaluation.duration}
              />
              <div className="flex justify-center">
                <div className="w-px h-4 bg-gray-700" />
              </div>
              <StepStatus
                step="3. Root Cause Analysis"
                status={pipelineState.rca.status}
                duration={pipelineState.rca.duration}
              />
              <div className="flex justify-center">
                <div className="w-px h-4 bg-gray-700" />
              </div>
              <StepStatus
                step="4. Self-Healing (LangGraph + FAISS + Regression)"
                status={pipelineState.healing.status}
                duration={pipelineState.healing.duration}
              />
            </div>
          </div>
        </div>

        {/* Right: Live Pipeline Log + Results */}
        <div className="space-y-6">
          {/* Live Log */}
          <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-gray-300">Pipeline Log</h3>
              <button
                onClick={() => setPipelineLog([])}
                className="text-xs text-gray-500 hover:text-gray-300"
              >
                Clear
              </button>
            </div>
            <div
              ref={logRef}
              className="bg-gray-950 rounded-lg border border-gray-800 p-3 h-72 overflow-y-auto font-mono text-xs space-y-0.5"
            >
              {pipelineLog.length === 0 && (
                <p className="text-gray-600 text-center py-8">Run the pipeline to see logs...</p>
              )}
              {pipelineLog.map((entry, i) => (
                <div key={i} className="flex gap-2">
                  <span className="text-gray-600 flex-shrink-0">[{entry.timestamp}]</span>
                  <span className={
                    entry.type === 'error' ? 'text-red-400' :
                    entry.type === 'warning' ? 'text-yellow-400' :
                    entry.type === 'success' ? 'text-green-400' :
                    'text-gray-400'
                  }>
                    {entry.message}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Evaluation Results Summary */}
          {pipelineState.evaluation.data && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
              <h3 className="text-sm font-medium text-gray-300 mb-4">Evaluation Results</h3>
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="text-center">
                  <p className="text-2xl font-bold text-gray-100">
                    {(pipelineState.evaluation.data.overall_score * 100).toFixed(1)}%
                  </p>
                  <p className="text-xs text-gray-500">Overall Score</p>
                </div>
                <div className="text-center">
                  <StatusBadge status={pipelineState.evaluation.data.passed ? 'passed' : 'not passed'} />
                  <p className="text-xs text-gray-500 mt-1">Verdict</p>
                </div>
                <div className="text-center">
                  <StatusBadge status={pipelineState.evaluation.data.severity} />
                  <p className="text-xs text-gray-500 mt-1">Severity</p>
                </div>
              </div>

              {/* Individual evaluator scores */}
              <div className="space-y-2">
                {pipelineState.evaluation.data.verdicts.map((v, i) => (
                  <div key={i} className="flex items-center justify-between bg-gray-950 rounded-lg p-3 border border-gray-800">
                    <div className="flex items-center gap-2">
                      {v.passed ?
                        <CheckCircle size={14} className="text-green-400" /> :
                        <XCircle size={14} className="text-red-400" />
                      }
                      <span className="text-xs text-gray-300">{v.evaluator_type.replace(/_/g, ' ')}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <div className="w-24 bg-gray-800 rounded-full h-1.5">
                        <div
                          className={`h-1.5 rounded-full ${v.passed ? 'bg-green-400' : 'bg-red-400'}`}
                          style={{ width: `${v.score * 100}%` }}
                        />
                      </div>
                      <span className="text-xs text-gray-400 w-10 text-right">{(v.score * 100).toFixed(0)}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Healing Results Summary */}
          {pipelineState.healing.data && (
            <div className="bg-gray-900 border border-gray-800 rounded-xl p-6">
              <h3 className="text-sm font-medium text-gray-300 mb-4">Healing Results</h3>
              <div className="grid grid-cols-3 gap-3 mb-4">
                <div className="text-center">
                  <p className="text-sm font-semibold text-gray-100">
                    {pipelineState.healing.data.strategy.replace(/_/g, ' ')}
                  </p>
                  <p className="text-xs text-gray-500">Strategy</p>
                </div>
                <div className="text-center">
                  <StatusBadge status={pipelineState.healing.data.regression_passed ? 'passed' : 'not passed'} />
                  <p className="text-xs text-gray-500 mt-1">Regression</p>
                </div>
                <div className="text-center">
                  <p className="text-lg font-bold text-green-400">
                    +{(pipelineState.healing.data.improvement_score * 100).toFixed(1)}%
                  </p>
                  <p className="text-xs text-gray-500">Improvement</p>
                </div>
              </div>

              {/* Side-by-side */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <p className="text-xs text-red-400 mb-1">Original</p>
                  <pre className="text-xs text-gray-300 whitespace-pre-wrap bg-gray-950 rounded-lg p-3 border border-red-900/20 max-h-32 overflow-y-auto">
                    {pipelineState.healing.data.original_response}
                  </pre>
                </div>
                <div>
                  <p className="text-xs text-green-400 mb-1">Repaired</p>
                  <pre className="text-xs text-gray-300 whitespace-pre-wrap bg-gray-950 rounded-lg p-3 border border-green-900/20 max-h-32 overflow-y-auto">
                    {pipelineState.healing.data.repaired_response}
                  </pre>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
