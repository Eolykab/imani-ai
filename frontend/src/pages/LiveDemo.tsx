import { useEffect, useMemo, useState } from 'react'
import { Activity, Brain, CheckCircle2, ListTodo, Radio, Server, Smartphone } from 'lucide-react'
import { api } from '../lib/api'

type Memory = { id: number; content: string; created_at: string }
type Task = { id: number; title: string; status: string; created_at: string }
type Event = { id: number; source: string; event: string; detail: string; created_at: string }
type Status = { system: any; ollama: any; hailo: any; telegram: any }

export default function LiveDemo() {
  const [memories, setMemories] = useState<Memory[]>([])
  const [tasks, setTasks] = useState<Task[]>([])
  const [events, setEvents] = useState<Event[]>([])
  const [status, setStatus] = useState<Status>()
  const [lastSync, setLastSync] = useState<Date>()
  const [error, setError] = useState('')

  useEffect(() => {
    let active = true
    const refresh = async () => {
      try {
        const [nextStatus, nextMemories, nextTasks, nextEvents] = await Promise.all([
          api<Status>('/status'), api<Memory[]>('/memories'), api<Task[]>('/tasks'), api<Event[]>('/activity?limit=12'),
        ])
        if (!active) return
        setStatus(nextStatus); setMemories(nextMemories); setTasks(nextTasks); setEvents(nextEvents)
        setLastSync(new Date()); setError('')
      } catch (reason) { if (active) setError((reason as Error).message) }
    }
    void refresh()
    const timer = window.setInterval(refresh, 2000)
    return () => { active = false; window.clearInterval(timer) }
  }, [])

  const pending = useMemo(() => tasks.filter(task => task.status !== 'completed'), [tasks])
  const completed = tasks.filter(task => task.status === 'completed').length
  const healthy = status?.ollama.online && status?.ollama.model_ready

  return <div className="demo-board">
    <section className="demo-stage"><div><span className="eyebrow">ELJOENAI MUNINGA · LIVE TELEGRAM AUTOMATION</span><h2>PiPilot Command Center</h2><p>Send an instruction from your phone. Watch the approved action appear here in real time.</p></div><div className="live-pill"><Radio size={15}/> LIVE <small>{lastSync ? `synced ${lastSync.toLocaleTimeString()}` : 'connecting'}</small></div></section>
    {error && <p className="error">Live sync: {error}</p>}
    <div className="demo-flow"><div><Smartphone/><b>Telegram</b><small>Natural instruction</small></div><i>→</i><div><Brain/><b>Local Qwen</b><small>Chooses approved tool</small></div><i>→</i><div><Server/><b>Raspberry Pi</b><small>Executes real action</small></div><i>→</i><div><Activity/><b>Dashboard</b><small>Updates live</small></div></div>
    <div className="demo-stats"><article><small>LOCAL AI</small><strong className={healthy ? 'green' : ''}>{healthy ? 'READY' : 'CHECKING'}</strong><span>Qwen 2.5 via Ollama</span></article><article><small>PENDING TASKS</small><strong>{pending.length}</strong><span>{completed} completed</span></article><article><small>SAVED MEMORIES</small><strong>{memories.length}</strong><span>Shared with Telegram</span></article><article><small>HAILO-8</small><strong className={status?.hailo.detected ? 'green' : ''}>{status?.hailo.detected ? 'CONNECTED' : 'NOT DETECTED'}</strong><span>Hardware monitoring only</span></article></div>
    <div className="grid two"><section className="panel demo-panel"><h3><ListTodo size={17}/> Live tasks</h3><div className="telegram-example">Try: “Add rehearse presentation to my tasks”</div>{!pending.length && <p className="muted">No pending tasks. Send one from Telegram.</p>}{pending.slice(0, 6).map(task => <div className="demo-item" key={task.id}><i/><div><b>{task.title}</b><small>Created {new Date(task.created_at).toLocaleTimeString()}</small></div></div>)}</section><section className="panel demo-panel"><h3><Brain size={17}/> Live memory</h3><div className="telegram-example">Try: “Remember that the demo starts at 10 AM”</div>{!memories.length && <p className="muted">No memories yet. Save one from Telegram.</p>}{memories.slice(0, 6).map(memory => <div className="demo-item memory" key={memory.id}><i/><div><b>{memory.content}</b><small>Saved {new Date(memory.created_at).toLocaleTimeString()}</small></div></div>)}</section></div>
    <section className="panel activity-strip"><h3><Activity size={17}/> Live operational feed</h3><div className="event-grid">{events.slice(0, 8).map(event => <div className="event" key={event.id}><CheckCircle2 size={14}/><div><b>{event.source} · {event.event.replaceAll('_', ' ')}</b><small>{event.detail} · {new Date(event.created_at).toLocaleTimeString()}</small></div></div>)}</div></section>
  </div>
}
