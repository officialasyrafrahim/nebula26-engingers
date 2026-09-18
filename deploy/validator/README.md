# Official validator drop-in (optional)

The official PS1 validator is **not shipped** with the data pack or this
repository. RAO runs a complete, independent fallback validator when no official
command is configured.

To use an official validator:

1. Put the validator and any files it needs in this directory
   (`deploy/validator/`).
2. Set `RAO_VALIDATOR_COMMAND` in `deploy/.env`, using the container path. This
   directory is mounted read-only at `/opt/validator` in the
   `rail-solver-worker` container, for example:

   ```text
   RAO_VALIDATOR_COMMAND=python /opt/validator/validate.py
   ```

3. Restart the worker: `make down && make up`.

The worker invokes the command as:

```text
<command...> <instance_dir> <submission_dir> <scenario>
```

and reads a PS1 section 2.7 JSON report from stdout. A non-zero exit code or
non-JSON output is reported as a failed official validation; it never falls back
silently and never relabels a fallback report as official.

If this directory contains only this README, RAO uses the fallback oracle with
`authority="fallback"`.
