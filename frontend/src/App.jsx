import { Routes, Route } from 'react-router-dom';
import Sidebar from './components/Sidebar';
import Dashboard from './pages/Dashboard';
import Traces from './pages/Traces';
import Healing from './pages/Healing';
import EvaluatorHealth from './pages/EvaluatorHealth';
import Drift from './pages/Drift';
import Admin from './pages/Admin';

export default function App() {
  return (
    <div className="flex min-h-screen bg-gray-950">
      <Sidebar />
      <main className="flex-1 ml-56 p-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/traces" element={<Traces />} />
          <Route path="/healing" element={<Healing />} />
          <Route path="/evaluator-health" element={<EvaluatorHealth />} />
          <Route path="/drift" element={<Drift />} />
          <Route path="/admin" element={<Admin />} />
        </Routes>
      </main>
    </div>
  );
}
