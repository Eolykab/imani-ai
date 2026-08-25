import { useEffect, useState, type ReactElement } from 'react'
import { Activity, Bell, Brain, CheckSquare, FileText, LayoutDashboard, Menu, MessageSquare, Mic, Radio, Server, Settings, ShieldCheck, X } from 'lucide-react'
import { Dashboard, SystemPage, MemoryPage, ActivityPage, SettingsPage } from './pages/Pages'
import LiveDemo from './pages/LiveDemo'
import TasksLive from './pages/TasksLive'
import { FilesLive, GeneralChat, RemindersPage, VoiceHistoryPage } from './pages/Productivity'

const items = [
  ['Dashboard', LayoutDashboard], ['Live Demo', Radio], ['Assistant', MessageSquare],
  ['System', Server], ['Memory', Brain], ['Tasks', CheckSquare], ['Reminders', Bell], ['Files', FileText], ['Voice', Mic],
  ['Activity', Activity], ['Settings', Settings],
] as const

export default function App() {
  const [page, setPage] = useState('Dashboard')
  const [open, setOpen] = useState(false)
  const [dataVersion, setDataVersion] = useState(0)

  useEffect(() => { if (location.pathname === '/demo') setPage('Live Demo') }, [])
  useEffect(() => {
    const timer = window.setInterval(() => setDataVersion(value => value + 1), 2000)
    return () => window.clearInterval(timer)
  }, [])

  const pages: Record<string, ReactElement> = {
    Dashboard: <Dashboard onNavigate={setPage}/>,
    'Live Demo': <LiveDemo/>,
    Assistant: <GeneralChat/>,
    System: <SystemPage/>,
    Memory: <MemoryPage/>,
    Tasks: <TasksLive/>,
    Reminders: <RemindersPage/>,
    Files: <FilesLive/>,
    Voice: <VoiceHistoryPage/>,
    Activity: <ActivityPage key={`activity-${dataVersion}`}/>,
    Settings: <SettingsPage/>,
  }

  return <div className="shell">
    <aside className={open ? 'open' : ''}>
      <div className="brand"><span className="mark">P</span><div><strong>PiPilot</strong><small>Eljoenai Muninga</small></div><button className="mobile" onClick={() => setOpen(false)}><X/></button></div>
      <nav>{items.map(([name, Icon]) => <button className={page === name ? 'active' : ''} onClick={() => { setPage(name); setOpen(false) }} key={name}><Icon size={18}/>{name}</button>)}</nav>
      <div className="privacy"><ShieldCheck size={18}/><div><strong>Private by design</strong><small>Inference stays local</small></div></div>
    </aside>
    <main><header><button className="mobile" onClick={() => setOpen(true)}><Menu/></button><div><h1>{page}</h1><p>Local Edge AI Assistant</p></div><span className="local"><i/> LOCAL AI</span></header><section className="content">{pages[page]}</section></main>
  </div>
}
