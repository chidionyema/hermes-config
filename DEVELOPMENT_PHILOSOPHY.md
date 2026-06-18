# Development Philosophy — Organisation & Backup

## Repos (all under github.com/chidionyema)

### Active Projects

| Repo | Language | What |
|------|----------|------|
| `lux` | TypeScript | PDD engine: spec language, verifier, CLI, proof generator, POPDD |
| `signalengine` | Python | Systematic signal engine — trading strategy lab |
| `prospector` | Python | AI-powered idea verification pipeline |
| `popdd-ts` | TypeScript | POPDD receipt chain — npm package |
| `lux-popdd` | Python | POPDD receipt chain — PyPI package |

### Infrastructure

| Repo | Visibility | What |
|------|-----------|------|
| `hermes-config` | Private | Hermes agent skills, memories, config — auto-pushed hourly |
| `cv` | Private | CV and career documents |

## Backup Strategy

```
Local (~/.hermes)  →  GitHub (hermes-config)  ←  Hourly cron
Local (code repos) →  GitHub (per-project)    ←  On commit (manual)
```

- **Skills + memories** = auto-pushed every hour via Hermes cron job
- **Code** = pushed on commit (no auto — intentional, avoids noise)
- **Auth tokens, keys, receipts** = excluded by `.gitignore` in `hermes-config`

## Hermes Config Structure

```
github.com/chidionyema/hermes-config
├── config.yaml         # Hermes configuration (strip secrets)
├── skills/             # All agent skills (21 directories)
│   ├── lux-proof-driven-development/
│   ├── popdd-inline-attestation/
│   └── ...
├── memories/            # Persistent agent memory
│   ├── MEMORY.md
│   └── USER.md
├── hooks/              # Hermes event hooks
└── cron/               # Job configurations (not output)
```

## PDD/POPDD Stack (Current State)

```
Layer           Status
─────────────────────────────────────────────────
Soul Contract  ✅ Encoded in memory + skills
POPDD hot chain ✅ 3 projects, zero-deps, auto-save
PDD enforcement ✅ LUX CLI (create/guard/verify/check)
Language bridge  ❌ Python + .NET need receipt-signing parity
CI gate script   ❌ One shell script to rule them all
```

## Key Decisions So Far

1. **Receipt format is the contract** — not the spec language. JSONL receipts bridge all languages.
2. **LUX is the reference implementation** — new PDD features land here first, then port to Python/.NET as needed.
3. **Don't port `lux spec` to every language** — enforce at CI level, not per-language.
4. **Skills are backed up** — `hermes-config` repo with auto-push cron.

## To Do (Next Session)

- [ ] Build `.NET POPDD` NuGet package (`dotnet-popdd`)
- [ ] Build CI gate script (one shell script, checks receipts per modified function)
- [ ] Define language-agnostic spec JSON schema
- [ ] Install pre-commit hook in Signal Engine + Prospector
