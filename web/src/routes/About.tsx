import { Link } from 'react-router'
import { APP_NAME, PublicPage } from '../components/Page'

const UPDATED = '24 September 2026'

export function Privacy() {
  return (
    <PublicPage title="Privacy" wide>
      <div className="prose">
        <p className="lede">
          {APP_NAME} is the ISC Racing Team&apos;s training site for the Formula Student registration quizzes. It keeps
          what it needs to run the training and nothing else.
        </p>

        <h2>Who looks after your data</h2>
        <p>
          The ISC Racing Team, the Formula Student team of Universidad Pontificia Comillas (ICAI), runs {APP_NAME} for
          its members. Questions and requests about your data go to the team&apos;s admins.
        </p>

        <h2>What we keep</h2>
        <ul>
          <li>
            <strong>Your account:</strong> email, display name, vertical, sub-departments, your position on the team,
            your role on the site, a password hash (never the password itself), when you joined and were last active,
            failed sign-in attempts and any lock, whether you hide from the leaderboard, and the invite you joined with
            (its role, vertical and the admin&apos;s note on who it was for).
          </li>
          <li>
            <strong>Your training:</strong> every answer (typed ones included) and whether it was right, the LP and XP
            it earned, hints you took, mock quiz runs, live quizzes you joined or hosted, your table and whether you
            captained it, answers you sent for your table, proposals you sent to your captain, problems you reported on
            questions, and what your rank and XP run on: your best division this season, right and wrong answers in a
            row, rested XP, and streak freezes held and used.
          </li>
          <li>
            <strong>Signing in:</strong> when each of your sign-ins started and was last used, and any password reset
            link an admin made for you.
          </li>
          <li>
            <strong>An admin log:</strong> changes to accounts (joined, role, position, status or email changed, reset
            links, locks, deletions) and to questions, so admins are accountable for what they do. It refers to people
            by account number.
          </li>
          <li>
            <strong>Web server logs:</strong> the server in front of the site records the IP address and time of each
            request, for security, and deletes them within two weeks.
          </li>
        </ul>

        <h2>What we don&apos;t</h2>
        <p>
          No analytics, trackers, adverts or third-party scripts; even the fonts come from our own server. The only
          cookie keeps you signed in; it is strictly necessary, so there is no cookie banner.
        </p>

        <h2>Why</h2>
        <p>
          To grade your answers, keep your rank and XP, run the daily question, mock and live quizzes, and show the
          leaderboards, and to keep the site secure (sign-in records, locks, the admin log and server logs). The legal
          basis is the team&apos;s legitimate interest in preparing its members for the quizzes that decide whether it
          competes. Nothing about you is decided automatically: ranks and levels mean nothing outside the site.
        </p>

        <h2>Who sees what</h2>
        <ul>
          <li>
            <strong>Every member:</strong> your display name, vertical, rank, LP and account level on the leaderboards
            (overall and by area, this week and this season), unless you hide yourself. Hiding only affects the
            leaderboards.
          </li>
          <li>
            <strong>In a live quiz:</strong> everyone in it sees your name, your table and its captain; your captain
            sees the answers you propose; each table&apos;s answers and score are shown after each question or at the
            end. The host and admins can download a results sheet with each table&apos;s answers and its captain&apos;s
            name.
          </li>
          <li>
            <strong>Reviewers:</strong> the problems you report, with your name.
          </li>
          <li>
            <strong>Admins:</strong> your email, role, position, status, rank and XP (even if you hide from the
            leaderboard), when you joined and were last seen, any sign-in lock, and the admin log.
          </li>
        </ul>
        <p>
          Hetzner Online GmbH runs the server for us, in the EU, and may not use the data for anything else. Nobody else
          sees it; we don&apos;t sell or share data.
        </p>

        <h2>How long</h2>
        <ul>
          <li>Your account and training stay while you&apos;re on the team, or until you delete your account.</li>
          <li>
            When you leave, an admin marks you as alumni. You&apos;re signed out and taken off the boards, and the
            account is deleted a year later unless you come back. Disabled accounts are deleted a year after too. Alumni
            can&apos;t sign in: download your data before you leave, or ask an admin for a copy or to delete it sooner.
          </li>
          <li>
            When an account is deleted, problems it reported stay without its name, so reviewers can still fix the
            question.
          </li>
          <li>The admin log is kept two years. Used or expired invite and reset links go after 30 days.</li>
          <li>
            Backups are kept 14 days, so deleted data leaves them within about two weeks. If a backup is ever restored,
            accounts deleted since it was made are deleted again.
          </li>
        </ul>

        <h2>Your rights</h2>
        <ul>
          <li>
            <strong>See and take everything:</strong> <Link to="/profile#your-data">Profile → Download my data</Link>{' '}
            gives you a JSON file you can keep or take elsewhere.
          </li>
          <li>
            <strong>Correct it:</strong> change your name, vertical and sub-departments in your profile; for anything
            else, such as your email, ask an admin.
          </li>
          <li>
            <strong>Delete it:</strong> <Link to="/profile#your-data">Profile → Delete my account</Link>, at any time
            (if you&apos;re the only admin, hand the role to someone first).
          </li>
          <li>
            <strong>Object or restrict:</strong> you can object to any of this, or ask us to pause using your data while
            a question about it is settled. Ask an admin; we stop unless there is a compelling reason, which we&apos;ll
            explain.
          </li>
          <li>
            <strong>Hide from the leaderboard:</strong> a switch in your profile.
          </li>
        </ul>
        <p>
          We answer requests within a month. If something isn&apos;t right, talk to the team&apos;s admins first; you
          can also complain to the Spanish data protection authority, the AEPD (
          <a href="https://www.aepd.es">aepd.es</a>).
        </p>
        <p className="muted">Last updated {UPDATED}.</p>
      </div>
    </PublicPage>
  )
}

export function About() {
  return (
    <PublicPage title="About" heading={`About ${APP_NAME}`} wide>
      <div className="prose">
        <p className="lede">
          The ISC Racing Team&apos;s practice platform for the Formula Student registration quizzes: every past
          question, a daily question, mock quizzes on the real clock, and live team sessions.
        </p>

        <h2>The questions</h2>
        <p>
          Questions, answers, solutions and images come from <a href="https://fs-quiz.eu">FS-Quiz</a>, by Yannik Ottens,
          under the <a href="https://opendatacommons.org/licenses/odbl/">Open Database License (ODbL)</a>. {APP_NAME}{' '}
          adds topics, reviewers&apos; corrections and hints for the team&apos;s own training; it doesn&apos;t republish
          the database.
        </p>

        <h2>Fair play</h2>
        <p>
          Past answers are public on FS-Quiz. What {APP_NAME} guarantees is that grading and time limits happen on the
          server: nobody gets extra time, answers a timed question twice or sees an answer before answering. Looking
          answers up is your call; it only makes you less ready.
        </p>

        <h2>Behind it</h2>
        <p>
          Built by the team and hosted on its own server. The code is open:{' '}
          <a href="https://github.com/isc-fs/IFS-Tests">github.com/isc-fs/IFS-Tests</a>. Found a bug or a wrong answer?
          Report the question from its page, or tell an admin.
        </p>
        <p>
          <Link to="/privacy">How we handle your data</Link>
        </p>
      </div>
    </PublicPage>
  )
}
