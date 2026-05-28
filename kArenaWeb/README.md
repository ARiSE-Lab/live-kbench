# kArenaWeb

Next.js dashboard scaffold for kArena.

The server reads `config.json` from this folder at startup and opens the configured SQLite database through a process-local read-only connection. By default `config.json` points at `./kArena.db`.

## Development

```bash
npm install
npm run dev
```

Open `http://localhost:3000`.
