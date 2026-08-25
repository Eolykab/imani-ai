import { FormEvent, useEffect, useState } from 'react'
import { Check, Plus, Trash2 } from 'lucide-react'
import { api } from '../lib/api'

type Task = { id: number; title: string; status: string; created_at: string }

export default function TasksLive() {
  const [rows, setRows] = useState<Task[]>([])
  const [text, setText] = useState('')
  const [error, setError] = useState('')

  const load = async () => {
    try { setRows(await api<Task[]>('/tasks')); setError('') }
    catch (reason) { setError((reason as Error).message) }
  }
  useEffect(() => {
    void load()
    const timer = window.setInterval(load, 2000)
    return () => window.clearInterval(timer)
  }, [])

  async function add(event: FormEvent) {
    event.preventDefault()
    await api('/tasks', { method: 'POST', body: JSON.stringify({ title: text }) })
    setText(''); await load()
  }

  return <div className="panel">
    <div className="toolbar"><h3>Tasks</h3><span className="live-pill"><i/> LIVE FROM TELEGRAM</span></div>
    {error && <p className="error">{error}</p>}
    <form className="add" onSubmit={add}><input value={text} onChange={event => setText(event.target.value)} placeholder="New task" required/><button><Plus/> Add</button></form>
    {rows.map(row => <div className={`listrow ${row.status === 'completed' ? 'done' : ''}`} key={row.id}>
      <button className="check" onClick={async () => { await api(`/tasks/${row.id}`, { method: 'PATCH', body: JSON.stringify({ status: row.status === 'completed' ? 'pending' : 'completed' }) }); await load() }}><Check/></button>
      <div><p>{row.title}</p><small>{row.status} · {new Date(row.created_at).toLocaleString()}</small></div>
      <button className="icon" onClick={async () => { await api(`/tasks/${row.id}`, { method: 'DELETE' }); await load() }}><Trash2/></button>
    </div>)}
  </div>
}
