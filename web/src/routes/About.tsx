import { Link } from 'react-router'
import { APP_NAME, PublicPage } from '../components/Page'
import { RULES_FROM } from '../lib/fairPlay'

const UPDATED = '12 October 2026'

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
          ISC, the association behind the ISC Racing Team, the Formula Student team of Universidad Pontificia Comillas
          (ICAI), runs {APP_NAME} for its members and is responsible for your data. Its address is Calle de Alberto
          Aguilera, 23, Madrid, Spain. For any question or request about your data, write to{' '}
          <a href="mailto:direccion.isc@clubisc.com">direccion.isc@clubisc.com</a>; the team&apos;s admins can help too.
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
            row, rested XP, and streak freezes held and used. From {RULES_FROM.en} (season 1b), ranked answers also
            record, as totals per answer only: seconds away from the question (split between look-ups you open from the
            question itself, such as the rulebook panel, and the rest), whether a typed answer was pasted, how often you
            copied a long piece of the question (a count, never what you copied), and how often you reopened the
            question. Leaving the tab is not an offence; these are context for a check, read together by people. Never
            your keystrokes, screen, camera, what is on your clipboard, the pages you visit or your extensions. Your own
            values are in your export.
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
            <strong>Web server logs:</strong> none. The server in front of {APP_NAME} doesn't record your IP address or
            what you request.
          </li>
        </ul>

        <h2>What we don&apos;t</h2>
        <p>
          No analytics, trackers, adverts or third-party scripts; even the fonts come from our own server. The only
          cookie keeps you signed in; it is strictly necessary, so there is no cookie banner. One exception, from season
          1b: the fair-play totals on ranked answers (see Your training), counted by this site only and kept per answer.
        </p>

        <h2>Why</h2>
        <p>
          To grade your answers, keep your rank and XP, run the daily question, mock and live quizzes, and show the
          leaderboards; to check ranked play (daily questions and your first run of each mock quiz in a season)
          statistically for answers that broke the fair-play rules, where a person decides what follows, never the app;
          and to keep the site secure (sign-in records, locks, the admin log and server logs). The legal basis is the
          team&apos;s legitimate interest in preparing its members for the quizzes that decide whether it competes, and
          in keeping that preparation fair. Nothing about you is decided automatically: ranks and levels mean nothing
          outside the site, the boards don&apos;t pick who sits the real quiz, and anything that follows a fair-play
          check starts with a conversation. The checks also read the answers and times already stored, compared between
          players; answers from before {RULES_FROM.en} are used only in aggregate, to calibrate the checks, never about
          a person.
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
            <strong>Fair-play checks:</strong> run on the server with accounts shown as codes, and read by two people
            together: a Technical Director and a member of ISC&apos;s board who doesn&apos;t play ranked, neither of
            them under review in that run. A code is matched to a name only when both agree there is something to talk
            about, and the output is deleted after the run. The codes are pseudonyms, not anonymity: the people who run
            the server can read the database, and keep to this process.
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
            The fair-play totals on a ranked answer (from season 1b) are blanked 90 days after the end of the season the
            answer was played in; the answer itself stays. A fair-play check keeps nothing unless a decision is taken; a
            decision is a line in the admin log.
          </li>
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
            a question about it is settled. Write to the address above or ask an admin; we stop unless there is a
            compelling reason, which we&apos;ll explain. For the fair-play checks, a pause means your ranked answers are
            stored but left out of the checks while we decide, within a month. Pausing isn&apos;t an exemption from the
            rules.
          </li>
          <li>
            <strong>Hide from the leaderboard:</strong> a switch in your profile.
          </li>
        </ul>
        <p>
          We answer requests within a month. If something isn&apos;t right, write to us or talk to the team&apos;s
          admins first; you can also complain to the Spanish data protection authority, the AEPD (
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

        <section className="prose" aria-labelledby="fair-play">
          <h2 id="fair-play" tabIndex={-1}>
            Fair play
          </h2>
          <p>
            Past answers are public on FS-Quiz. What {APP_NAME} guarantees is that grading and time limits happen on the
            server: nobody gets extra time, answers a timed question twice or sees an answer before answering. What you
            bring to the question is another matter. In Practice mode, use anything. Ranked play has rules from{' '}
            {RULES_FROM.en}, the mid-season update the Technical Directors call season 1b; until then, looking things up
            is your call, as it has been.
          </p>
          <p>
            Ranked play is every daily question and every question in your first run of a mock quiz each season, whether
            or not it moved LP. Replays are practice. The rules apply even if you hide from the boards, and to Mingo,
            Jefe and DT alike.
          </p>
          <ul>
            <li>
              <strong>Fine:</strong> reference material (the rulebook and handbooks, a textbook, your own notes on the
              material: not a list of bank questions with their answers, and notes that hold a question's answer count
              as looking it up), a calculator or Python, and a translation tool (your browser's translate, DeepL) on the
              question text. What you remember from studying is yours. This list is closed: for anything else, ask a TD
              first.
            </li>
            <li>
              <strong>Not fine:</strong> finding the answer or a worked solution to this question or any version of it
              anywhere (fs-quiz.eu, a web search, a shared sheet), help from another person, and any AI that reads the
              question or suggests an answer or a method, on any device: chatbots, assistants and browser side panels,
              AI search answers (an AI answer a search engine shows you counts as AI: scroll past it), photo or
              step-by-step solvers, AI inside your editor or code. Search the rulebook, not the question; a translation
              tool, not a chatbot. Not sure about a tool? Ask a TD before you play ranked; until then, don't.
            </li>
            <li>
              <strong>Don't pass it on:</strong> no ranked question or answer to anyone until the Madrid day is over
              (daily) or they have finished their run (mock), and no shared sheets of them. One account each, played
              only by you.
            </li>
            <li>
              <strong>Practice:</strong> anything goes. Open the rulebook, ask whoever you like, look it up: it's for
              learning.
            </li>
            <li>
              <strong>Live quizzes:</strong> the host's room rules. If the host says nothing, your table talks and
              that's it.
            </li>
          </ul>
          <p>
            Ranked play is checked statistically for answers that broke these rules: passed on, copied, looked up or
            AI-assisted. If something looks off, two people look at it together and anything that follows starts with a
            conversation, never an automatic penalty. The most that can follow is sitting out the boards for the rest of
            the season, decided by the Technical Directors after hearing you, with an appeal to the board. Answers given
            before {RULES_FROM.en} are never a reason for any of it. The same rules follow in Spanish; if the two ever
            differ, the English text applies; ask a TD.
          </p>
          <div lang="es" className="prose">
            <h3>Juego limpio</h3>
            <p>
              Las respuestas de los quizzes pasados son públicas en FS-Quiz. Lo que {APP_NAME} garantiza es que la
              corrección y el tiempo se controlan en el servidor: nadie tiene tiempo extra, responde dos veces a una
              pregunta con reloj ni ve la respuesta antes de contestar. Lo que uses para responder es otra cosa. En el
              modo Práctica, usa lo que quieras. En ranked hay reglas desde el {RULES_FROM.es}, la actualización a mitad
              de temporada que los Directores Técnicos llaman temporada 1b; hasta entonces, buscar es cosa tuya, como
              hasta ahora.
            </p>
            <p>
              Ranked es cada pregunta diaria y cada pregunta de tu primer intento de un mock cada temporada, mueva LP o
              no. Las repeticiones son práctica. Las reglas valen aunque te ocultes de los rankings, y lo mismo para
              Mingo, Jefe o DT.
            </p>
            <ul>
              <li>
                <strong>Vale:</strong> material de consulta (el reglamento y los handbooks, un libro, tus apuntes sobre
                la materia: no una lista de preguntas con sus respuestas; unos apuntes con la respuesta cuentan como
                buscarla), una calculadora o Python, y un traductor (el del navegador, DeepL) sobre el texto de la
                pregunta. Lo que recuerdes de haber estudiado es tuyo. Esta lista es cerrada: para cualquier otra cosa,
                pregunta antes a un DT.
              </li>
              <li>
                <strong>No vale:</strong> encontrar la respuesta o la solución de esta pregunta, o de cualquier versión
                de ella, en ningún sitio (fs-quiz.eu, una búsqueda, una hoja compartida), la ayuda de otra persona, y
                cualquier IA que lea la pregunta o sugiera una respuesta o un método, en cualquier dispositivo:
                chatbots, asistentes y paneles laterales del navegador, respuestas de IA en buscadores (la respuesta de
                IA que te muestre un buscador cuenta como IA: pasa de ella), solucionadores por foto o paso a paso, IA
                dentro de tu editor o tu código. Busca en el reglamento, no la pregunta; un traductor, no un chatbot.
                ¿Dudas con una herramienta? Pregunta a un DT antes de jugar ranked; mientras, no la uses.
              </li>
              <li>
                <strong>No lo pases:</strong> ninguna pregunta ni respuesta de ranked a nadie hasta que acabe el día
                (Madrid) en la diaria, o hasta que la otra persona termine su intento en un mock, y nada de hojas
                compartidas. Una cuenta por persona, y la juegas tú.
              </li>
              <li>
                <strong>Práctica:</strong> vale todo. Abre el reglamento, pregunta a quien quieras, búscalo: es para
                aprender.
              </li>
              <li>
                <strong>Quizzes en directo:</strong> las reglas de la sala las pone quien lo organiza. Si no dice nada,
                tu mesa habla entre sí y punto.
              </li>
            </ul>
            <p>
              Ranked se revisa con estadísticas para detectar respuestas que rompieron estas reglas: chivadas, copiadas,
              buscadas o hechas con IA. Si algo no cuadra, dos personas lo miran juntas y lo que venga después empieza
              por una conversación, nunca por una penalización automática. Lo máximo que puede pasar es quedarte fuera
              de los rankings el resto de la temporada, decidido por los Directores Técnicos después de escucharte, con
              recurso ante la junta. Las respuestas anteriores al {RULES_FROM.es} nunca son motivo de nada de esto. Si
              alguna vez las versiones en inglés y español difieren, vale el texto en inglés; pregunta a un DT.
            </p>
            <p>
              Qué se guarda: desde la temporada 1b, cada respuesta de ranked guarda también, solo como totales por
              respuesta, los segundos fuera de la pregunta (separando las consultas abiertas desde la propia pregunta,
              como el reglamento, del resto), si una respuesta escrita se pegó, cuántas veces copiaste un trozo largo de
              la pregunta y cuántas veces volviste a abrirla. Nunca tus teclas, tu pantalla, tu cámara, lo que haya en
              tu portapapeles, las páginas que visitas ni tus extensiones. Salir de la pestaña no es una falta; son
              contexto para una revisión, que leen personas. Tus valores van en tu exportación, se revisan con tu cuenta
              convertida en un código y se borran 90 días después de acabar la temporada. Las comprobaciones también
              usan las respuestas y los tiempos ya guardados, comparados entre jugadores; antes del {RULES_FROM.es} solo
              se usan en conjunto, para calibrarlas, nunca sobre una persona. Todo, en inglés, en la{' '}
              <Link to="/privacy">página de privacidad</Link>.
            </p>
          </div>
        </section>

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
