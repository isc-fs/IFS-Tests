import { chromium, type FullConfig } from '@playwright/test'
import { ADMIN, signIn } from './helpers'

/** Fix today's daily questions before any spec runs, as the 00:01 job does on the server. Otherwise the first
 *  visit to the daily page can pick a question another spec is practising at that moment, and practice then
 *  (rightly) refuses to score a question that has just become someone's running daily. */
export default async function globalSetup(config: FullConfig) {
  const browser = await chromium.launch()
  const page = await browser.newPage({ baseURL: config.projects[0].use.baseURL })
  await signIn(page, ADMIN.email, ADMIN.password)
  const status = await page.request.get('/api/daily')
  if (!status.ok()) throw new Error(`GET /api/daily: ${status.status()}`)
  await browser.close()
}
