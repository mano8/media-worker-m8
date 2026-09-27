# docker_compose compose

<!-- env-files:start -->
## Environment files

Copy each template to the name after the arrow (`init.sh` does this where the stack has one), then replace every
`changethis`. Every key is documented in its template; each secret carries a `# Value:` line with its minimum
and maximum length and allowed characters. Real env files are gitignored and never committed.

| Template → file | Read by | Must be set (placeholders) |
| --- | --- | --- |
| `worker.env.example` → `worker.env` | `worker` | `MEDIA_INTERNAL_SERVICE_TOKEN`, `MEDIA_REDIS_PASSWORD`, `S3_ACCESS_KEY`, `S3_SECRET_KEY` |

Generate a value that satisfies every secret rule (48 chars: upper, lower, digit and `-`):

```sh
python -c "import secrets,string; a=string.ascii_letters+string.digits; print('Aa1-'+''.join(secrets.choice(a) for _ in range(44)))"
```

Values must avoid spaces, `$`, `#`, quotes and backslashes: Compose interpolates `$`, dotenv treats `#` as a
comment, and several values are embedded in URLs, JSON or the Redis ACL.
<!-- env-files:end -->
