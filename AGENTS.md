# Codemao project maintenance rules

- Work directly in the server repository when the task targets the deployed service.
- Never commit .env, student Excel files, SQLite databases, migration archives, SSH keys, or backup checksums.
- After every application update, run tests, deploy, wait for the app container to become healthy, commit and push the change, then run:

      ./ops/trigger-async-backup.sh post-deploy

- Git post-commit and post-merge hooks also queue a migration backup asynchronously. Do not disable core.hooksPath or the systemd backup timer.
- Before declaring an update complete, confirm the new backup service succeeded:

      systemctl status codemao-migration-backup.service
      ls -1t /opt/codemao-backups/codemao-migration-*.tar.gz | head -n 1

- Migration archives contain student data and secrets. Keep them off GitHub and public storage.
