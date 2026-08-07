# Security

Do not commit `.env`, webhook URLs, API keys, exported leads, or SQLite databases.
The default `.gitignore` excludes these files. If a secret was ever committed,
rotate it and remove it from Git history before publishing the repository.

Please report security issues privately to the repository owner instead of
opening a public issue.
