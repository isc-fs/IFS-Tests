import { screen, within } from '@testing-library/react'
import { expect, test } from 'vitest'
import { RULES_FROM } from '../lib/fairPlay'
import { renderApp, signedOut } from '../test/render'

const flat = (el: Element | null) => (el?.textContent ?? '').replace(/\s+/g, ' ').trim()
const item = (scope: HTMLElement, label: RegExp) => {
  const li = within(scope).getByText(label).closest('li')
  if (!li) throw new Error(`no list item for ${label}`)
  return li
}

async function fairPlay() {
  renderApp('/about', signedOut)
  await screen.findByRole('heading', { level: 1, name: 'About MingoQuiz' })
  return screen.getByRole('region', { name: 'Fair play' })
}

test('the about page dates and states the fair-play rules in English', async () => {
  const fair = await fairPlay()
  expect(within(fair).getByRole('heading', { level: 2, name: 'Fair play' })).toHaveAttribute('id', 'fair-play')
  expect(within(fair).getByText(new RegExp(`Ranked play has rules from ${RULES_FROM.en}`))).toBeInTheDocument()
  expect(
    within(fair).getByText(/every daily question and every question in your first run of a mock quiz each season/),
  ).toBeInTheDocument()
  expect(within(fair).getByText(/^Fine:/)).toBeInTheDocument()
  expect(within(fair).getByText(/the rulebook and handbooks/)).toBeInTheDocument()
  expect(within(fair).getByText(/^Not fine:/)).toBeInTheDocument()
  expect(within(fair).getByText(/any AI that reads the question or suggests an answer or a method/)).toBeInTheDocument()
  expect(within(fair).getByText(/^Don't pass it on:/)).toBeInTheDocument()
  expect(within(fair).getByText(/^Practice:/)).toBeInTheDocument()
  expect(within(fair).getByText(/anything goes/)).toBeInTheDocument()
  expect(within(fair).getByText(/^Live quizzes:/)).toBeInTheDocument()
  expect(within(fair).getByText(/the host's room rules/)).toBeInTheDocument()
  expect(within(fair).getByText(/never an automatic penalty/)).toBeInTheDocument()
  expect(
    within(fair).getByText(new RegExp(`Answers given before ${RULES_FROM.en} are never a reason`)),
  ).toBeInTheDocument()
})

test('the allowed and forbidden lists draw the line where the rule does', async () => {
  const fair = await fairPlay()
  const fine = flat(item(fair, /^Fine:/))
  expect(fine).toMatch(/rulebook and handbooks/)
  expect(fine).toMatch(/calculator or Python/)
  expect(fine).toMatch(/translation tool/)
  expect(fine).toMatch(/DeepL/)
  expect(fine).not.toMatch(/\bAI\b|chatbot|fs-quiz/)

  const notFine = flat(item(fair, /^Not fine:/))
  expect(notFine).toMatch(/fs-quiz\.eu/)
  expect(notFine).toMatch(/help from another person/)
  expect(notFine).toMatch(/chatbots, assistants and browser side panels/)
  expect(notFine).toMatch(/on any device/)
  expect(notFine).toMatch(/Search the rulebook, not the question; a translation tool, not a chatbot/)
  expect(notFine).toMatch(/Ask a TD before you play ranked; until then, don't/)

  const relay = flat(item(fair, /^Don't pass it on:/))
  expect(relay).toMatch(/One account each, played only by you/)
  expect(flat(item(fair, /^Practice:/))).toMatch(/anything goes/)
  expect(flat(item(fair, /^Live quizzes:/))).toMatch(/your table talks and that's it/)
})

test('ranked play is defined once, for everyone, and the worst outcome is stated', async () => {
  const fair = await fairPlay()
  const definition = within(fair).getByText(/every daily question and every question in your first run/)
  expect(flat(definition)).toMatch(/whether or not it moved LP/)
  expect(flat(definition)).toMatch(/Replays are practice/)
  expect(flat(definition)).toMatch(/even if you hide from the boards/)
  expect(flat(definition)).toMatch(/Mingo, Jefe and DT alike/)
  const closing = flat(within(fair).getByText(/never an automatic penalty/))
  expect(closing).toMatch(/two people look at it together/)
  expect(closing).toMatch(/After hearing you, the Technical Directors may give you a warning/)
  expect(closing).toMatch(/take you off the boards for the rest of the season/)
  expect(closing).toMatch(/the most that can follow is being denied attendance at competitions/)
  expect(closing).toMatch(/appeal to the board/)
  expect(closing).toMatch(
    /That is never decided on statistics alone: it needs your own account or evidence beyond the statistical checks, such as a supervised session, as well as hearing you/,
  )
  expect(closing).toMatch(/Statistics only ever start a conversation/)
})

test('the Spanish block states the same ladder, maximum and safeguard', async () => {
  const fair = await fairPlay()
  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const closing = flat(within(es).getByText(/nunca por una penalización automática/))
  expect(closing).toMatch(/Después de escucharte, los Directores Técnicos pueden darte un aviso/)
  expect(closing).toMatch(/dejarte fuera de los rankings el resto de la temporada/)
  expect(closing).toMatch(/lo máximo que puede pasar es quedarte sin ir a las competiciones, con recurso ante la junta/)
  expect(closing).toMatch(
    /Eso nunca se decide solo con estadísticas: hace falta lo que cuentes tú o pruebas que vayan más allá de las comprobaciones estadísticas, como una sesión supervisada, y además escucharte/,
  )
  const summary = flat(within(es).getByText(/^Qué se guarda:/))
  expect(summary).toMatch(/El rango, el nivel y los rankings no seleccionan a nadie/)
  expect(summary).toMatch(/nunca solo con estadísticas, y puede suponer quedarte sin ir a las competiciones/)
  expect(summary).toContain(`nunca para respuestas anteriores al ${RULES_FROM.es}`)
})

test('the rules are repeated in Spanish inside one lang="es" block', async () => {
  const fair = await fairPlay()
  const es = fair.querySelector<HTMLElement>('[lang="es"]')
  expect(es).not.toBeNull()
  expect(fair.querySelectorAll('[lang]')).toHaveLength(1)
  const spanish = es as HTMLElement
  expect(within(spanish).getByRole('heading', { level: 3, name: 'Juego limpio' })).toBeInTheDocument()
  expect(within(spanish).getAllByRole('listitem')).toHaveLength(5)
  expect(within(fair).getAllByRole('listitem')).toHaveLength(10)
  expect(
    within(fair)
      .getAllByRole('listitem')
      .filter((li) => !spanish.contains(li)),
  ).toHaveLength(5)
  expect(within(spanish).getByText(/^Vale:/)).toBeInTheDocument()
  expect(within(spanish).getByText(/el reglamento y los handbooks/)).toBeInTheDocument()
  expect(within(spanish).getByText(/^No vale:/)).toBeInTheDocument()
  expect(within(spanish).getByText(/cualquier IA que lea la pregunta/)).toBeInTheDocument()
  expect(within(spanish).getByText(/^No lo pases:/)).toBeInTheDocument()
  expect(within(spanish).getByText(/vale todo/)).toBeInTheDocument()
  expect(within(spanish).getByText(/nunca por una penalización automática/)).toBeInTheDocument()
  // Once in the opening paragraph and once in the closing one.
  expect(within(spanish).getAllByText(new RegExp(RULES_FROM.es)).length).toBeGreaterThanOrEqual(2)
})

test('the Spanish block summarises what the privacy notice adds and links it', async () => {
  const fair = await fairPlay()
  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const summary = flat(within(es).getByText(/^Qué se guarda:/))
  expect(summary).toMatch(/temporada 1b/)
  expect(summary).toMatch(/Nunca tus teclas, tu pantalla, tu cámara, lo que haya en tu portapapeles/)
  expect(summary).toMatch(/las páginas que visitas ni tus extensiones/)
  expect(summary).toMatch(/tu exportación/)
  expect(summary).toMatch(/un código/)
  expect(summary).toMatch(/90 días después de acabar la temporada/)
  expect(within(es).getByRole('link', { name: 'página de privacidad' })).toHaveAttribute('href', '/privacy')
})

test('the English part of the region carries no Spanish and the Spanish no English rule words', async () => {
  const fair = await fairPlay()
  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const spanish = flat(es)
  expect(spanish).not.toMatch(/\bNot fine\b|Don't pass it on|never an automatic penalty/)
  const english = [...fair.children]
    .filter((c) => c !== es)
    .map(flat)
    .join(' ')
  expect(english).not.toMatch(/Juego limpio|No vale|penalización automática/)
})

test.each(['/about', '/privacy'])('%s does not mention the AI canary yet', async (path) => {
  renderApp(path, signedOut)
  await screen.findByRole('heading', { level: 1 })
  expect(document.body.textContent).not.toMatch(/canary|decoy|AI assistants/i)
})

test('the privacy notice tells players that the Looking something up button announces a look-up, in English', async () => {
  renderApp('/privacy', signedOut)
  const training = (await screen.findByText(/^Your training:/)).closest('li') as HTMLElement
  const text = flat(training)
  expect(text).toContain('Looking something up')
  expect(text).toMatch(
    /look-ups you open from the question itself, such as the rulebook panel, or announce with the Looking something up button/,
  )
  expect(within(training).getByText('Looking something up').tagName).toBe('STRONG')
})

test('and the Spanish summary says the same, naming the button as it is labelled on screen', async () => {
  const fair = await fairPlay()
  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const summary = flat(within(es).getByText(/^Qué se guarda:/))
  expect(summary).toMatch(/o que anuncias con el botón Looking something up/)
  expect(within(es).getByText('Looking something up').tagName).toBe('STRONG')
  const english = [...fair.children]
    .filter((c) => c !== es)
    .map(flat)
    .join(' ')
  expect(english).not.toMatch(/anuncias|botón/)
})

test('the privacy notice names the fair-play purpose and keeps the human decision', async () => {
  renderApp('/privacy', signedOut)
  await screen.findByRole('heading', { level: 1, name: 'Privacy' })
  expect(screen.getByText(/statistically for answers that broke the fair-play rules/)).toBeInTheDocument()
  expect(screen.getByText(/a person decides what follows, never the app/)).toBeInTheDocument()
  const why = flat(screen.getByText(/Nothing about you is decided automatically/))
  expect(why).toMatch(
    /Ranks, levels and the boards select nobody: they don't pick the team, who sits the real quiz or who goes to competitions/,
  )
  expect(why).toMatch(
    /taken by people after hearing you, and never on statistics alone, it can mean not being taken to competitions/,
  )
  expect(why).toMatch(/Anything that follows a fair-play check starts with a conversation/)
  expect(why).not.toMatch(/mean nothing outside the site/)
})

test('the privacy notice announces the season-1b totals and what is never recorded', async () => {
  renderApp('/privacy', signedOut)
  const training = (await screen.findByText(/^Your training:/)).closest('li') as HTMLElement
  const text = flat(training)
  expect(text).toContain(`From ${RULES_FROM.en} (season 1b)`)
  expect(text).toMatch(/ranked answers also record, as totals per answer only/)
  expect(text).toMatch(/seconds away from the question/)
  expect(text).toMatch(/look-ups you open from the question itself, such as the rulebook panel/)
  expect(text).toMatch(/whether a typed answer was pasted or dropped in from outside the page/)
  expect(text).toMatch(/how often you copied or dragged a long piece of the question/)
  expect(text).toMatch(/a count, never what you copied/)
  expect(text).toMatch(/how often you reopened the question/)
  expect(text).toMatch(/Leaving the tab is not an offence/)
  expect(text).toMatch(
    /Never your keystrokes, screen, camera, what is on your clipboard, the pages you visit or your extensions/,
  )
  expect(text).toMatch(/Your own values are in your export/)
  expect(text).toContain(
    `Each total is recorded from the site update that adds it, and never for answers before ${RULES_FROM.en}`,
  )
  // The pre-existing content of the item is still there.
  expect(text).toMatch(/every answer \(typed ones included\)/)
})

test('the privacy notice says who reads the checks, how long the totals last and how to pause them', async () => {
  renderApp('/privacy', signedOut)
  await screen.findByRole('heading', { level: 1, name: 'Privacy' })
  const checks = flat(screen.getByText(/^Fair-play checks:/).closest('li'))
  expect(checks).toMatch(/accounts shown as codes/)
  expect(checks).toMatch(/a Technical Director and a member of ISC's board who doesn't play ranked/)
  expect(checks).toMatch(/neither of them under review in that run/)
  expect(checks).toMatch(/the output is deleted after the run/)
  expect(checks).toMatch(/pseudonyms, not anonymity/)

  expect(screen.getByText(/blanked 90 days after the end of the season/)).toBeInTheDocument()
  expect(screen.getByText(/the answer itself stays/)).toBeInTheDocument()
  expect(screen.getByText(/a decision is a line in the admin log/)).toBeInTheDocument()

  const pause = flat(screen.getByText(/^Object or restrict:/).closest('li'))
  expect(pause).toMatch(/left out of the checks while we decide, within a month/)
  expect(pause).toMatch(/Pausing isn't an exemption from the rules/)
  // The earlier promise is not weakened.
  expect(pause).toMatch(/we stop unless there is a compelling reason/)
})

test('the privacy notice still says what it does not do, and is dated', async () => {
  renderApp('/privacy', signedOut)
  await screen.findByRole('heading', { level: 1, name: 'Privacy' })
  expect(screen.getByText(/No analytics, trackers, adverts or third-party scripts/)).toBeInTheDocument()
  expect(screen.getByText(/^Last updated \d{1,2} \w+ 20\d\d\.$/)).toBeInTheDocument()
})

test('notes are limited to notes on the material, in both languages, and the list is closed', async () => {
  const fair = await fairPlay()
  const fine = flat(item(fair, /^Fine:/))
  expect(fine).toMatch(/your own notes on the material/)
  expect(fine).toMatch(/not a list of bank questions with their answers/)
  expect(fine).toMatch(/notes that hold a question's answer count as looking it up/)
  expect(fine).toMatch(/This list is closed: for anything else, ask a TD first/)

  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const vale = flat(item(es, /^Vale:/))
  expect(vale).toMatch(/tus apuntes sobre la materia/)
  expect(vale).toMatch(/no una lista de preguntas con sus respuestas/)
  expect(vale).toMatch(/unos apuntes con la respuesta cuentan como buscarla/)
  expect(vale).toMatch(/Esta lista es cerrada/)
})

test('looking up any version of the question, or an AI search answer, is not fine', async () => {
  const fair = await fairPlay()
  const notFine = flat(item(fair, /^Not fine:/))
  expect(notFine).toMatch(/the answer or a worked solution to this question or any version of it/)
  expect(notFine).toMatch(/an AI answer a search engine shows you counts as AI/)
  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const noVale = flat(item(es, /^No vale:/))
  expect(noVale).toMatch(/de esta pregunta, o de cualquier versión de ella/)
  expect(noVale).toMatch(/la respuesta de IA que te muestre un buscador cuenta como IA/)
})

test('the English text prevails in both languages and the Spanish defines ranked like the English', async () => {
  const fair = await fairPlay()
  const english = flat(within(fair).getByText(/never an automatic penalty/))
  expect(english).toMatch(/if the two ever differ, the English text applies; ask a TD/)
  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const spanish = flat(within(es).getByText(/nunca por una penalización automática/))
  expect(spanish).toMatch(/difieren, vale el texto en inglés; pregunta a un DT/)
  const ranked = flat(within(es).getByText(/^Ranked es cada pregunta diaria/))
  expect(ranked).toMatch(/de un mock cada temporada/)
  expect(ranked).not.toMatch(/esta temporada/)
})

test('the Spanish summary carries the tab-leaving line and the use of stored data', async () => {
  const fair = await fairPlay()
  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const summary = flat(within(es).getByText(/^Qué se guarda:/))
  expect(summary).toMatch(/Salir de la pestaña no es una falta; son contexto para una revisión, que leen personas/)
  expect(summary).toMatch(/usan las respuestas y los tiempos ya guardados, comparados entre jugadores/)
  expect(summary).toContain(
    `antes del ${RULES_FROM.es} solo se usan en conjunto, para calibrarlas, nunca sobre una persona`,
  )
})

test('the privacy notice says stored answers and times are compared between players, and what that means before the date', async () => {
  renderApp('/privacy', signedOut)
  await screen.findByRole('heading', { level: 1, name: 'Privacy' })
  const why = flat(screen.getByText(/statistically for answers that broke the fair-play rules/))
  expect(why).toMatch(/also read the answers and times already stored, compared between players/)
  expect(why).toContain(
    `answers from before ${RULES_FROM.en} are used only in aggregate, to calibrate the checks, never about a person`,
  )
})

test('the privacy notice names the fair-play totals as the one exception to "no trackers"', async () => {
  renderApp('/privacy', signedOut)
  await screen.findByRole('heading', { level: 1, name: 'Privacy' })
  const text = flat(screen.getByText(/No analytics, trackers, adverts or third-party scripts/))
  expect(text).toMatch(
    /One exception, from season 1b: the fair-play totals on ranked answers \(see Your training\), counted by this site only and kept per answer/,
  )
})

test('the English notice says dropped and dragged, not only pasted and copied, and nothing about the keyboard shortcut', async () => {
  renderApp('/privacy', signedOut)
  const training = (await screen.findByText(/^Your training:/)).closest('li') as HTMLElement
  const text = flat(training)
  expect(text).toMatch(/pasted or dropped in from outside the page/)
  expect(text).toMatch(/copied or dragged a long piece/)
  expect(text).not.toMatch(/Ctrl|Cmd|find bar|search in the page/i)
  expect(text).toMatch(/a count, never what you copied/)
})

test('the Spanish summary says the same about dropping and dragging', async () => {
  const fair = await fairPlay()
  const es = fair.querySelector<HTMLElement>('[lang="es"]') as HTMLElement
  const summary = flat(within(es).getByText(/^Qué se guarda:/))
  expect(summary).toMatch(/pegó/)
  expect(summary).toMatch(/solt/) // dropped
  expect(summary).toMatch(/arrastr/) // dragged
  expect(summary).not.toMatch(/Ctrl|Cmd/)
})
