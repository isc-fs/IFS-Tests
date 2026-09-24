import { Link } from 'react-router'
import { APP_NAME, PublicPage } from '../components/Page'

const UPDATED = '24 September 2026'

export function Privacy() {
  return (
    <PublicPage title="Privacy">
      <div className="prose">
        <p className="lede">
          {APP_NAME} is the ISC Racing Team&apos;s training site for the Formula Student registration quizzes. It keeps
          what it needs to run the training and nothing else. Last updated {UPDATED}.
        </p>

        <h2>Who looks after your data</h2>
        <p>
          The ISC Racing Team, the Formula Student team of Universidad Pontificia Comillas (ICAI), runs {APP_NAME} for
          its members. Questions about your data go to the team&apos;s admins.
        </p>

        <h2>What we keep</h2>
        <ul>
          <li>
            <strong>Your account:</strong> email, display name, vertical, sub-departments, your position on the team,
            your role on the site and a password hash (never the password itself).
          </li>
          <li>
            <strong>Your training:</strong> every answer and whether it was right, XP, streaks, mock quiz runs, live
            quizzes you joined or hosted, proposals you sent to your captain, and problems you reported on questions.
          </li>
          <li>
            <strong>Signing in:</strong> when each of your sign-ins started and was last used.
          </li>
          <li>
            <strong>An admin log:</strong> changes to accounts (joined, role or status changed, reset links), so admins
            are accountable for what they do.
          </li>
        </ul>

        <h2>What we don&apos;t</h2>
        <p>
          No analytics, trackers, adverts or third-party scripts. The only cookie keeps you signed in; it is strictly
          necessary, so there is no cookie banner.
        </p>

        <h2>Why</h2>
        <p>
          To grade your answers, keep your XP, run the daily question, mock and live quizzes, and show the leaderboards:
          the team&apos;s legitimate interest in preparing its members for the quizzes that decide whether it competes.
        </p>

        <h2>Who sees what</h2>
        <ul>
          <li>
            <strong>Every member:</strong> your display name, vertical, rank and XP on the leaderboard (unless you hide
            yourself), and your name at your table in a live quiz.
          </li>
          <li>
            <strong>Admins:</strong> your email, status and when you were last seen.
          </li>
          <li>
            <strong>Reviewers:</strong> the problems you report, with your name.
          </li>
        </ul>
        <p>Nobody else. We don&apos;t sell or share data.</p>

        <h2>Where, and for how long</h2>
        <ul>
          <li>On the team&apos;s own server at Hetzner, in the EU.</li>
          <li>Your account and training stay while you&apos;re on the team, or until you delete your account.</li>
          <li>
            When you leave, an admin marks you as alumni at the start of the season. You&apos;re signed out and taken
            off the boards, and the account is deleted a year later.
          </li>
          <li>The admin log is kept two years. Used or expired invite and reset links go after 30 days.</li>
          <li>Backups are kept 14 days, so deleted data leaves them within two weeks.</li>
        </ul>

        <h2>Your rights</h2>
        <ul>
          <li>
            <strong>See and download everything:</strong>{' '}
            <Link to="/profile#your-data">Profile → Download my data</Link>.
          </li>
          <li>
            <strong>Correct it:</strong> change your name, vertical and sub-departments in your profile; ask an admin
            for anything else.
          </li>
          <li>
            <strong>Delete it:</strong> <Link to="/profile#your-data">Profile → Delete my account</Link>, at any time.
          </li>
          <li>
            <strong>Hide from the leaderboard:</strong> a switch in your profile.
          </li>
        </ul>
        <p>
          If something isn&apos;t right, talk to the team&apos;s admins first. You can also complain to the Spanish data
          protection authority, the AEPD (<a href="https://www.aepd.es">aepd.es</a>).
        </p>
      </div>
    </PublicPage>
  )
}

export function About() {
  return (
    <PublicPage title="About" heading={`About ${APP_NAME}`}>
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
          server: nobody gets extra time, answers a timed question twice or sees an answer before answering. Whether you
          look it up is up to you, and only trains you worse.
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
