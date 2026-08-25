import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Check, Pencil, Plus, Trash2, X } from 'lucide-react'
import { api } from '../lib/api'

type Task = { id: number; title: string; description?: string; status: string; due_date?: string; created_at: string }
type Draft = { title: string; description: string; due_date: string }
const emptyDraft: Draft = { title: '', description: '', due_date: '' }

export default function TasksLive() {
  const [rows, setRows] = useState<Task[]>([])
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [editing, setEditing] = useState<number>()
  const [editDraft, setEditDraft] = useState<Draft>(emptyDraft)
  const [filter, setFilter] = useState('all')
  const [error, setError] = useState('')
  const load = async () => { try { setRows(await api<Task[]>('/tasks')); setError('') } catch (reason) { setError((reason as Error).message) } }

  useEffect(() => { void load(); const timer = window.setInterval(load, 2000); return () => window.clearInterval(timer) }, [])
  const visible = useMemo(() => filter === 'all' ? rows : rows.filter(row => row.status === filter), [rows, filter])
  const localDate = (value?: string) => value ? new Date(value).toISOString().slice(0, 16) : ''

  async function add(event: FormEvent) {
    event.preventDefault()
    await api('/tasks', { method: 'POST', body: JSON.stringify({ title: draft.title, description: draft.description || null, due_date: draft.due_date ? new Date(draft.due_date).toISOString() : null }) })
    setDraft(emptyDraft); await load()
  }
  async function save(id: number) {
    await api(`/tasks/${id}`, { method: 'PATCH', body: JSON.stringify({ title: editDraft.title, description: editDraft.description || null, due_date: editDraft.due_date ? new Date(editDraft.due_date).toISOString() : null }) })
    setEditing(undefined); await load()
  }

  return <div className="panel tasks-manager">
    <div className="toolbar"><div><h3>Task manager</h3><small className="muted">Create here or instruct PiPilot through Telegram</small></div><span className="live-pill"><i/> LIVE FROM TELEGRAM</span></div>
    {error && <p className="error">{error}</p>}
    <form className="task-create" onSubmit={add}>
      <input value={draft.title} onChange={event => setDraft({ ...draft, title: event.target.value })} placeholder="Task title" required/>
      <input value={draft.description} onChange={event => setDraft({ ...draft, description: event.target.value })} placeholder="Description (optional)"/>
      <input type="datetime-local" value={draft.due_date} onChange={event => setDraft({ ...draft, due_date: event.target.value })}/>
      <button><Plus size={17}/> Add task</button>
    </form>
    <div className="task-filters">{['all', 'pending', 'completed', 'cancelled'].map(value => <button className={filter === value ? 'active' : ''} onClick={() => setFilter(value)} key={value}>{value}</button>)}</div>
    {!visible.length && <p className="muted">No {filter === 'all' ? '' : filter} tasks.</p>}
    {visible.map(row => editing === row.id ? <div className="task-edit" key={row.id}>
      <input value={editDraft.title} onChange={event => setEditDraft({ ...editDraft, title: event.target.value })}/>
      <input value={editDraft.description} onChange={event => setEditDraft({ ...editDraft, description: event.target.value })} placeholder="Description"/>
      <input type="datetime-local" value={editDraft.due_date} onChange={event => setEditDraft({ ...editDraft, due_date: event.target.value })}/>
      <button onClick={() => save(row.id)}>Save</button><button className="secondary" onClick={() => setEditing(undefined)}><X size={16}/></button>
    </div> : <div className={`task-row ${row.status === 'completed' ? 'done' : ''}`} key={row.id}>
      <button className="check" title="Toggle complete" onClick={async () => { await api(`/tasks/${row.id}`, { method: 'PATCH', body: JSON.stringify({ status: row.status === 'completed' ? 'pending' : 'completed' }) }); await load() }}><Check/></button>
      <div className="task-copy"><b>{row.title}</b>{row.description && <p>{row.description}</p>}<small>{row.status}{row.due_date ? ` · Due ${new Date(row.due_date).toLocaleString()}` : ''} · ID {row.id}</small></div>
      <button className="icon" title="Edit" onClick={() => { setEditing(row.id); setEditDraft({ title: row.title, description: row.description || '', due_date: localDate(row.due_date) }) }}><Pencil/></button>
      <button className="icon danger" title="Delete" onClick={async () => { await api(`/tasks/${row.id}`, { method: 'DELETE' }); await load() }}><Trash2/></button>
    </div>)}
  </div>
}
