import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import type { AdminUser, InviteIn } from '../api/types.gen'
import { auditLog, createInvite, openInvites, resetLink, revokeInvite, updateUser, users } from '../api/sdk.gen'
import { Notice } from '../components/Form'
import { errorMessage, useMe, VERTICALS } from '../lib/api'

const ROLES = ['member', 'reviewer', 'admin'] as const
const STATUSES = ['active', 'alumni', 'disabled'] as const

function when(iso: string | null | undefined) {
  return iso ? new Date(iso).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

export default function Admin() {
  const { data: me } = useMe()
  if (me?.role !== 'admin') {
    return (
      <>
        <h1>Admins only</h1>
        <p className="muted">Ask a team admin if you need something changed.</p>
      </>
    )
  }
  return (
    <>
      <h1>Admin</h1>
      <InvitePanel />
      <Members />
    </>
  )
}

function CopyLink({ url, label }: { url: string; label: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="copy">
      <code>{url}</code>
      <button
        type="button"
        onClick={async () => {
          await navigator.clipboard.writeText(url)
          setCopied(true)
        }}
      >
        {copied ? 'Copied' : label}
      </button>
    </div>
  )
}

function InvitePanel() {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<InviteIn>({ role: 'member', vertical: null, note: '' })
  const open = useQuery({ queryKey: ['invites'], queryFn: async () => (await openInvites()).data })
  const create = useMutation({
    mutationFn: () => createInvite({ body: form }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['invites'] }),
  })
  const revoke = useMutation({
    mutationFn: (id: number) => revokeInvite({ path: { invite_id: id } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['invites'] }),
  })

  const submit = (e: FormEvent) => {
    e.preventDefault()
    create.mutate()
  }

  return (
    <section className="panel stack" aria-labelledby="invite-title">
      <h2 id="invite-title">Invite a member</h2>
      <form onSubmit={submit} className="row">
        <label>
          Role
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as InviteIn['role'] })}>
            {ROLES.map((r) => <option key={r}>{r}</option>)}
          </select>
        </label>
        <label>
          Vertical
          <select value={form.vertical ?? ''} onChange={(e) => setForm({ ...form, vertical: (e.target.value || null) as InviteIn['vertical'] })}>
            <option value="">Let them choose</option>
            {VERTICALS.map((v) => <option key={v}>{v}</option>)}
          </select>
        </label>
        <label className="grow">
          Note (who it's for)
          <input maxLength={80} value={form.note ?? ''} onChange={(e) => setForm({ ...form, note: e.target.value })} />
        </label>
        <button type="submit" disabled={create.isPending}>Create link</button>
      </form>
      {create.isError && <Notice tone="error">{errorMessage(create.error)}</Notice>}
      {create.data?.data && (
        <Notice tone="ok">
          Send this link privately. It works once and expires {when(create.data.data.expires_at)}.
          <CopyLink url={create.data.data.url} label="Copy link" />
        </Notice>
      )}
      {!!open.data?.length && (
        <table>
          <caption>Open invites</caption>
          <thead><tr><th>Note</th><th>Role</th><th>Vertical</th><th>Expires</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {open.data.map((i) => (
              <tr key={i.id}>
                <td>{i.note ?? '—'}</td>
                <td>{i.role}</td>
                <td>{i.vertical ?? '—'}</td>
                <td>{when(i.expires_at)}</td>
                <td><button type="button" className="link-button" onClick={() => revoke.mutate(i.id)}>Revoke</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function Members() {
  const { data: me } = useMe()
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: ['users'], queryFn: async () => (await users()).data })
  const [link, setLink] = useState<{ name: string; url: string } | null>(null)
  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: number; role?: AdminUser['role']; status?: AdminUser['status'] }) =>
      updateUser({ path: { user_id: id }, body }),
    onSettled: () => queryClient.invalidateQueries({ queryKey: ['users'] }),
  })
  const reset = useMutation({
    mutationFn: (u: AdminUser) => resetLink({ path: { user_id: u.id } }),
    onSuccess: ({ data }, u) => data && setLink({ name: u.display_name, url: data.url }),
  })

  return (
    <section className="panel stack" aria-labelledby="members-title">
      <h2 id="members-title">Members</h2>
      {update.isError && <Notice tone="error">{errorMessage(update.error)}</Notice>}
      {link && (
        <Notice tone="ok">
          Reset link for {link.name} (valid 24 h, works once):
          <CopyLink url={link.url} label="Copy link" />
        </Notice>
      )}
      <div className="table-scroll">
        <table>
          <thead><tr><th>Name</th><th>Email</th><th>Vertical</th><th>Role</th><th>Status</th><th>Last seen</th><th><span className="sr-only">Actions</span></th></tr></thead>
          <tbody>
            {list.data?.map((u) => {
              const self = u.id === me?.id
              return (
                <tr key={u.id}>
                  <td>{u.display_name}{u.leaderboard_opt_out && <span className="badge">hidden</span>}</td>
                  <td>{u.email}</td>
                  <td>{u.vertical ?? '—'}</td>
                  <td>
                    <select aria-label={`Role of ${u.display_name}`} value={u.role} disabled={self} onChange={(e) => update.mutate({ id: u.id, role: e.target.value as AdminUser['role'] })}>
                      {ROLES.map((r) => <option key={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>
                    <select aria-label={`Status of ${u.display_name}`} value={u.status} disabled={self} onChange={(e) => update.mutate({ id: u.id, status: e.target.value as AdminUser['status'] })}>
                      {STATUSES.map((s) => <option key={s}>{s}</option>)}
                    </select>
                  </td>
                  <td>{when(u.last_seen)}</td>
                  <td><button type="button" className="link-button" onClick={() => reset.mutate(u)}>Reset link</button></td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <AuditTrail />
    </section>
  )
}

function AuditTrail() {
  const log = useQuery({ queryKey: ['audit'], queryFn: async () => (await auditLog({ query: { limit: 20 } })).data })
  return (
    <details>
      <summary>Recent admin activity</summary>
      <ul className="audit">
        {log.data?.map((a) => (
          <li key={a.id}>
            <time>{when(a.at)}</time> {a.action} {a.target}
          </li>
        ))}
      </ul>
    </details>
  )
}
