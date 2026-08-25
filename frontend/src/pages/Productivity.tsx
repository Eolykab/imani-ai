import { FormEvent, useEffect, useRef, useState } from 'react'
import { Bell, Brain, FileText, Mic, Send, Trash2, Upload } from 'lucide-react'
import { api, bytes } from '../lib/api'

type Chat = { id?: number; role: string; content: string; tools_used?: string[] }
export function GeneralChat() {
  const [rows, setRows] = useState<Chat[]>([]); const [message, setMessage] = useState(''); const [busy, setBusy] = useState(false); const bottom = useRef<HTMLDivElement>(null)
  useEffect(() => { api<Chat[]>('/chat/history').then(setRows) }, [])
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [rows, busy])
  async function send(text: string) {
    if (!text.trim() || busy) return
    const next = [...rows, { role: 'user', content: text }]; setRows(next); setMessage(''); setBusy(true)
    try { const result = await api<{ response: string; tools_used: string[] }>('/chat', { method: 'POST', body: JSON.stringify({ message: text, history: rows.slice(-20) }) }); setRows([...next, { role: 'assistant', content: result.response, tools_used: result.tools_used }]) }
    catch (reason) { setRows([...next, { role: 'assistant', content: (reason as Error).message }]) } finally { setBusy(false) }
  }
  return <div className="persisted-chat"><div className="general-banner"><Brain size={18}/><div><b>General knowledge + local actions</b><small>Persistent local conversation powered by Qwen. Current facts require an approved live tool.</small></div><button onClick={async () => { await api('/chat/history', { method: 'DELETE' }); setRows([]) }}><Trash2 size={15}/> Clear</button></div><div className="chat panel"><div className="messages">{!rows.length && <div className="empty"><Brain/><h2>What can I help with?</h2><p>Ask for knowledge, writing, code, planning, or PiPilot actions.</p><div className="chips">{['Explain edge AI simply','Write my presentation introduction','Give me five demo questions','Analyse system health'].map(value => <button onClick={() => send(value)} key={value}>{value}</button>)}</div></div>}{rows.map((row, index) => <div className={`bubble ${row.role}`} key={row.id || index}>{row.tools_used?.length ? <small>Approved tool: {row.tools_used.join(', ')}</small> : null}<p>{row.content}</p></div>)}{busy && <p className="muted">Local Qwen is thinking…</p>}<div ref={bottom}/></div><form onSubmit={event => { event.preventDefault(); void send(message) }}><input value={message} onChange={event => setMessage(event.target.value)} placeholder="Ask PiPilot anything…"/><button disabled={busy}><Send size={18}/></button></form></div></div>
}

type Reminder = { id: number; title: string; display_time: string; recurrence?: string; status: string }
export function RemindersPage() {
  const [rows, setRows] = useState<Reminder[]>([]); const [title, setTitle] = useState(''); const [when, setWhen] = useState('tomorrow at 9'); const [recurrence, setRecurrence] = useState('')
  const load = () => api<Reminder[]>('/reminders').then(setRows)
  useEffect(() => { void load(); const timer = window.setInterval(load, 5000); return () => clearInterval(timer) }, [])
  async function add(event: FormEvent) { event.preventDefault(); await api('/reminders', { method: 'POST', body: JSON.stringify({ title, remind_at: when, recurrence: recurrence || null }) }); setTitle(''); await load() }
  return <div className="panel reminders"><div className="toolbar"><div><h3>Reminders</h3><small className="muted">Telegram reminders are delivered by the PiPilot service</small></div><Bell/></div><form className="reminder-create" onSubmit={add}><input value={title} onChange={event => setTitle(event.target.value)} placeholder="What should I remind you about?" required/><input value={when} onChange={event => setWhen(event.target.value)} placeholder="tomorrow at 9" required/><select value={recurrence} onChange={event => setRecurrence(event.target.value)}><option value="">Once</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select><button>Add reminder</button></form>{rows.map(row => <div className="reminder-row" key={row.id}><Bell size={17}/><div><b>{row.title}</b><small>{row.display_time}{row.recurrence ? ` · ${row.recurrence}` : ''} · owner {row.id}</small></div><button onClick={async () => { await api(`/reminders/${row.id}`, { method: 'DELETE' }); await load() }}><Trash2/></button></div>)}</div>
}

type LocalFile = { id: number; name: string; size: number; created_at: string }
export function FilesLive() {
  const [rows, setRows] = useState<LocalFile[]>([]); const [selected, setSelected] = useState<number>(); const [question, setQuestion] = useState('Summarise this file and cite page numbers where available.'); const [answer, setAnswer] = useState(''); const [error, setError] = useState(''); const [busy, setBusy] = useState(false)
  const load = () => api<LocalFile[]>('/files').then(setRows).catch(reason => setError(reason.message))
  useEffect(() => { void load() }, [])
  async function upload(file: File) { setError(''); const body = new FormData(); body.append('file', file); try { const saved = await api<{ id: number }>('/files', { method: 'POST', body }); await load(); setSelected(saved.id) } catch (reason) { setError((reason as Error).message) } }
  async function ask() { if (!selected) return; setBusy(true); setError(''); try { const result = await api<{ response: string }>(`/files/${selected}/ask`, { method: 'POST', body: JSON.stringify({ question }) }); setAnswer(result.response) } catch (reason) { setError((reason as Error).message) } finally { setBusy(false) } }
  return <div className="files-workspace"><section className="panel"><h3>Private local documents</h3><label className="drop"><Upload/><b>Choose a file</b><span>.txt, .md, .json, .log or .pdf · maximum configured server size</span><input type="file" accept=".txt,.md,.json,.log,.pdf" onChange={event => event.target.files?.[0] && void upload(event.target.files[0])}/></label>{error && <p className="error">{error}</p>}<div className="file-list">{rows.map(row => <div className={`file-card ${selected === row.id ? 'selected' : ''}`} key={row.id} onClick={() => { setSelected(row.id); setAnswer('') }}><FileText/><div><b>{row.name}</b><small>{bytes(row.size)} · {new Date(row.created_at).toLocaleString()}</small></div><button title="Delete" onClick={async event => { event.stopPropagation(); await api(`/files/${row.id}`, { method: 'DELETE' }); if (selected === row.id) setSelected(undefined); await load() }}><Trash2/></button></div>)}</div></section><section className="panel file-ask"><h3>Ask the selected document</h3><textarea value={question} onChange={event => setQuestion(event.target.value)}/><button disabled={!selected || busy} onClick={ask}>{busy ? 'Reading locally…' : 'Ask PiPilot'}</button>{!selected && <p className="muted">Select an uploaded file first.</p>}{answer && <div className="document-answer">{answer}</div>}</section></div>
}

type Voice = { id: number; transcript: string; duration_seconds: number; engine: string; tools_used: string[]; created_at: string }
export function VoiceHistoryPage() {
  const [rows, setRows] = useState<Voice[]>([])
  useEffect(() => { const load = () => api<Voice[]>('/voice/history').then(setRows); void load(); const timer = setInterval(load, 3000); return () => clearInterval(timer) }, [])
  return <div className="panel"><div className="toolbar"><div><h3>Hailo voice history</h3><small className="muted">Transcripts only; temporary audio is deleted</small></div><Mic/></div>{!rows.length && <p className="muted">Send an authorized Telegram voice note to begin.</p>}{rows.map(row => <div className="voice-row" key={row.id}><Mic/><div><b>“{row.transcript}”</b><small>{row.engine} · {row.duration_seconds}s · {new Date(row.created_at).toLocaleString()}</small>{row.tools_used.length > 0 && <span>Tool: {row.tools_used.join(', ')}</span>}</div></div>)}</div>
}
