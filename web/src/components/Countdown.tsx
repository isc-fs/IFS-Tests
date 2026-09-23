import { useEffect, useRef, useState } from 'react'

/** Seconds left until `deadline`, measured against the server's clock (the browser's may be off). */
export function useSecondsLeft(deadline: string, serverNow: string) {
  const [offset] = useState(() => new Date(serverNow).getTime() - Date.now())
  const end = new Date(deadline).getTime()
  const left = () => Math.max(0, Math.ceil((end - (Date.now() + offset)) / 1000))
  const [seconds, setSeconds] = useState(left)
  useEffect(() => {
    const id = window.setInterval(() => setSeconds(left()), 250)
    return () => window.clearInterval(id)
  })
  return seconds
}

const mmss = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`

/** A visible clock; screen readers hear it at the one-minute and ten-second marks, not every second. */
export function Countdown({
  deadline,
  serverNow,
  onExpire,
}: {
  deadline: string
  serverNow: string
  onExpire: () => void
}) {
  const seconds = useSecondsLeft(deadline, serverNow)
  const fired = useRef(false)
  useEffect(() => {
    if (seconds === 0 && !fired.current) {
      fired.current = true
      onExpire()
    }
  }, [seconds, onExpire])
  const warning = seconds <= 10 ? 'Ten seconds left.' : seconds <= 60 ? 'One minute left.' : ''
  return (
    <div className={`countdown ${seconds <= 10 ? 'urgent' : ''}`}>
      <span role="timer" aria-label="Time left">
        {mmss(seconds)}
      </span>
      <span className="sr-only" aria-live="assertive">
        {seconds === 0 ? "Time's up." : warning}
      </span>
    </div>
  )
}
