import { type QueryKey, useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import {
  auditLogOptions,
  auditLogQueryKey,
  createInviteMutation,
  openInvitesOptions,
  openInvitesQueryKey,
  resetLinkMutation,
  revokeInviteMutation,
  updateUserMutation,
  usersOptions,
  usersQueryKey,
} from '../api/@tanstack/react-query.gen'
import { type AdminUser, type InviteIn, Role, Status, Vertical } from '../api/types.gen'
import { ErrorNotice, Field, Form, Notice, SelectField } from '../components/Form'
import { Page } from '../components/Page'
import { queryClient, useMe } from '../lib/api'

const when = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
    : '—'

/** Refetch what an admin action changed; the audit trail always changes. */
function refresh(...keys: QueryKey[]) {
  for (const queryKey of [...keys, auditLogQueryKey()]) queryClient.invalidateQueries({ queryKey })
}

export default function Admin() {
  const { data: me } = useMe()
  if (me?.role !== 'admin') {
    return (
      <Page title="Admins only">
        <p className="muted">Ask a team admin if you need something changed.</p>
      </Page>
    )
  }
  return (
    <Page title="Admin" eyebrow="Team">
      <InvitePanel />
      <Members selfId={me.id} />
      <AuditTrail />
    </Page>
  )
}

/** Shows a one-time link, focuses it for keyboard and screen-reader users, and copies it if allowed. */
function OneTimeLink({ label, url, expires }: { label: string; url: string; expires: string }) {
  const input = useRef<HTMLInputElement>(null)
  const [copied, setCopied] = useState<'yes' | 'manual' | null>(null)
  useEffect(() => input.current?.focus(), [url])
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url)
      setCopied('yes')
    } catch {
      input.current?.select()
      setCopied('manual')
    }
  }
  return (
    <Notice tone="ok">
      <p>
        {label} Send it privately: it works once and expires {when(expires)}.
      </p>
      <div className="copy">
        <input ref={input} readOnly value={url} aria-label={label} onFocus={(e) => e.target.select()} />
        <button type="button" onClick={copy}>
          {copied === 'yes' ? 'Copied' : 'Copy'}
        </button>
      </div>
      {copied === 'manual' && <p>Copying isn't allowed here: the link is selected, press Ctrl/⌘ + C.</p>}
    </Notice>
  )
}

function InvitePanel() {
  const [form, setForm] = useState<InviteIn>({ role: Role.MEMBER, vertical: null, note: '' })
  const [created, setCreated] = useState<{ note: string; url: string; expires: string } | null>(null)
  const invites = useQuery(openInvitesOptions())
  const create = useMutation({
    ...createInviteMutation(),
    onSuccess: (l, { body }) => {
      setCreated({ note: body.note ?? '', url: l.url, expires: l.expires_at })
      setForm({ ...form, note: '' })
      refresh(openInvitesQueryKey())
    },
  })
  const revoke = useMutation({ ...revokeInviteMutation(), onSuccess: () => refresh(openInvitesQueryKey()) })
  const revokeInvite = (id: number, note: string) => {
    if (window.confirm(`Revoke the invite for ${note}? The link stops working.`))
      revoke.mutate({ path: { invite_id: id } })
  }

  return (
    <section className="panel stack" aria-labelledby="invite-title">
      <h2 id="invite-title">Invite a member</h2>
      <Form onSubmit={() => create.mutate({ body: form })} className="row">
        <SelectField
          label="Role"
          value={form.role}
          onChange={(e) => setForm({ ...form, role: e.target.value as Role })}
        >
          {Object.values(Role).map((r) => (
            <option key={r}>{r}</option>
          ))}
        </SelectField>
        <SelectField
          label="Vertical"
          value={form.vertical ?? ''}
          onChange={(e) => setForm({ ...form, vertical: (e.target.value || null) as Vertical | null })}
        >
          <option value="">Let them choose</option>
          {Object.values(Vertical).map((v) => (
            <option key={v}>{v}</option>
          ))}
        </SelectField>
        <div className="grow">
          <Field
            label="Who it's for"
            required
            maxLength={80}
            value={form.note ?? ''}
            onChange={(e) => setForm({ ...form, note: e.target.value })}
          />
        </div>
        <button type="submit" disabled={create.isPending || !form.note?.trim()}>
          Create link
        </button>
      </Form>
      <ErrorNotice error={create.error} />
      <ErrorNotice error={revoke.error} />
      {created && <OneTimeLink label={`Invite for ${created.note}.`} url={created.url} expires={created.expires} />}
      {!!invites.data?.length && (
        <>
          <h3>Open invites</h3>
          <ul className="list invites">
            {invites.data.map((i) => (
              <li key={i.id} className="item">
                <span className="item-title">{i.note ?? 'No note'}</span>
                <span className="muted">
                  {i.role}
                  {i.vertical && ` · ${i.vertical}`} · expires {when(i.expires_at)}
                </span>
                <button
                  type="button"
                  className="link-button"
                  aria-label={`Revoke invite for ${i.note ?? 'unnamed'}`}
                  onClick={() => revokeInvite(i.id, i.note ?? 'unnamed')}
                >
                  Revoke
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

const CONFIRM: Partial<Record<string, (name: string) => string>> = {
  disabled: (n) => `Disable ${n}? They'll be signed out and can't sign in until re-enabled.`,
  alumni: (n) => `Mark ${n} as alumni? They'll be signed out and leave the leaderboards.`,
  admin: (n) => `Make ${n} an admin? Admins can invite people and change anyone's role.`,
}

const matches = (u: AdminUser, q: string) =>
  [u.display_name, u.email, u.vertical ?? '', u.role, u.status].some((s) => s.toLowerCase().includes(q))

function Members({ selfId }: { selfId: number }) {
  const users = useQuery(usersOptions())
  const [query, setQuery] = useState('')
  const [changed, setChanged] = useState('')
  const [link, setLink] = useState<{ userId: number; url: string; expires: string } | null>(null)
  const update = useMutation({
    ...updateUserMutation(),
    onSuccess: (u) => setChanged(`${u.display_name} is now ${u.role}, ${u.status}.`),
    onSettled: () => refresh(usersQueryKey()),
  })
  const reset = useMutation({
    ...resetLinkMutation(),
    onSuccess: (l, vars) => {
      setLink({ userId: vars.path.user_id, url: l.url, expires: l.expires_at })
      refresh()
    },
  })

  const change = (u: AdminUser, body: { role?: Role; status?: Status }) => {
    const ask = CONFIRM[body.role ?? body.status ?? '']
    if (ask && !window.confirm(ask(u.display_name))) return
    setChanged('')
    update.mutate({ path: { user_id: u.id }, body })
  }
  const q = query.trim().toLowerCase()
  const shown = users.data?.filter((u) => matches(u, q))

  return (
    <section className="panel stack" aria-labelledby="members-title">
      <h2 id="members-title">Members ({users.data?.length ?? '…'})</h2>
      {(users.data?.length ?? 0) > 5 && (
        <Field
          label="Find a member"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          hint="Name, email, vertical, role or status."
        />
      )}
      <ErrorNotice error={update.error} />
      {changed && <Notice tone="ok">{changed}</Notice>}
      {q && shown?.length === 0 && <p className="muted">Nobody matches “{query.trim()}”.</p>}
      <ul className="list members">
        {shown?.map((u) => {
          const self = u.id === selfId
          const locked = u.locked_until && new Date(u.locked_until) > new Date()
          return (
            <li key={u.id}>
              <fieldset className="item member">
                <legend className="sr-only">{u.display_name}</legend>
                <div className="who">
                  <span className="item-title">
                    {u.display_name}
                    {self && <span className="badge">you</span>}
                    {u.leaderboard_opt_out && <span className="badge">off leaderboard</span>}
                    {locked && <span className="badge warn">locked until {when(u.locked_until)}</span>}
                  </span>
                  <span className="muted">
                    {u.email} · {u.vertical ?? 'no vertical'} · seen {when(u.last_seen)}
                  </span>
                </div>
                <SelectField
                  label="Role"
                  value={u.role}
                  disabled={self}
                  onChange={(e) => change(u, { role: e.target.value as Role })}
                >
                  {Object.values(Role).map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </SelectField>
                <SelectField
                  label="Status"
                  value={u.status}
                  disabled={self}
                  onChange={(e) => change(u, { status: e.target.value as Status })}
                >
                  {Object.values(Status).map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </SelectField>
                <button
                  type="button"
                  className="secondary"
                  aria-label={`Reset link for ${u.display_name}`}
                  onClick={() => reset.mutate({ path: { user_id: u.id } })}
                >
                  Reset link
                </button>
                {link?.userId === u.id && (
                  <div className="full">
                    <OneTimeLink
                      label={`Password reset link for ${u.display_name}.`}
                      url={link.url}
                      expires={link.expires}
                    />
                  </div>
                )}
              </fieldset>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

const ACTIONS: Record<string, string> = {
  'invite.create': 'created an invite',
  'invite.revoke': 'revoked an invite',
  'user.register': 'joined',
  'user.bootstrap_admin': 'set up the first admin account',
  'user.update': 'changed',
  'user.revoke_sessions': 'signed out',
  'reset.create': 'created a reset link for',
  'password.reset': 'reset their password',
  'password.change': 'changed their password',
}

function AuditTrail() {
  const log = useQuery(auditLogOptions({ query: { limit: 30 } }))
  return (
    <details className="panel">
      <summary>Recent activity</summary>
      <ul className="audit">
        {log.data?.map((a) => {
          const self = a.actor === a.target
          if (a.action === 'user.locked') {
            return (
              <li key={a.id}>
                <time dateTime={a.at}>{when(a.at)}</time> {a.target} was locked after 5 failed sign-ins
              </li>
            )
          }
          return (
            <li key={a.id}>
              <time dateTime={a.at}>{when(a.at)}</time> {a.actor ?? 'System'} {ACTIONS[a.action] ?? a.action}
              {!self && a.target && !a.target.startsWith('invite:') && ` ${a.target}`}
              {a.action === 'user.update' &&
                ` (${Object.entries(a.details)
                  .map(([k, v]) => `${k} → ${(v as string[])[1]}`)
                  .join(', ')})`}
            </li>
          )
        })}
      </ul>
    </details>
  )
}
