import { NavLink } from 'react-router-dom';
import {
  LayoutDashboard,
  ListTree,
  Wrench,
  Activity,
  Heart,
  Terminal,
} from 'lucide-react';
import clsx from 'clsx';

const links = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/admin', label: 'Admin Console', icon: Terminal },
  { to: '/traces', label: 'Traces', icon: ListTree },
  { to: '/healing', label: 'Healing', icon: Wrench },
  { to: '/evaluator-health', label: 'Evaluators', icon: Heart },
  { to: '/drift', label: 'Drift', icon: Activity },
];

export default function Sidebar() {
  return (
    <aside className="fixed inset-y-0 left-0 w-56 bg-gray-900 border-r border-gray-800 flex flex-col">
      <div className="h-16 flex items-center gap-2 px-5 border-b border-gray-800">
        <div className="w-8 h-8 rounded-lg bg-brand-600 flex items-center justify-center text-white font-bold text-sm">
          AI
        </div>
        <span className="font-semibold text-sm text-gray-100">System Debugger</span>
      </div>

      <nav className="flex-1 py-4 px-3 space-y-1">
        {links.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors',
                isActive
                  ? 'bg-brand-600/20 text-brand-400'
                  : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'
              )
            }
          >
            <Icon size={18} />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="px-5 py-4 border-t border-gray-800">
        <p className="text-xs text-gray-500">v0.1.0</p>
      </div>
    </aside>
  );
}
