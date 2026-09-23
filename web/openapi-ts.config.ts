import { defineConfig } from '@hey-api/openapi-ts'

// Regenerate with `npm run gen:api` after changing the API (CI fails if src/api is stale).
export default defineConfig({
  input: 'openapi.json',
  output: { path: 'src/api' },
  plugins: [
    '@hey-api/client-fetch',
    { name: '@hey-api/typescript', enums: 'javascript' },
    '@hey-api/sdk',
    '@tanstack/react-query',
  ],
})
