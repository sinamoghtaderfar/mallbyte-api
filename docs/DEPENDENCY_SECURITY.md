# Runtime security maintenance

The runtime remains on Django's supported 5.2 LTS line. The November 2026
remediation updates Django to 5.2.19, DRF to 3.18.3, PyJWT to 2.15.1,
SQLParse to 0.6.0, urllib3 to 2.8.0, Requests to 2.33.1, Pillow to 13.0.0
and Cryptography to 50.0.2. Rebuild web, worker and beat
images together after reviewing the dependency PR; do not update a running
production virtual environment in place.

Primary release references:

- https://docs.djangoproject.com/en/5.2/releases/5.2.19/
- https://github.com/psf/requests/blob/main/HISTORY.md
- https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html
- https://www.django-rest-framework.org/community/release-notes/
- https://pyjwt.readthedocs.io/en/stable/changelog.html
- https://cryptography.io/en/latest/changelog/
- https://urllib3.readthedocs.io/en/stable/changelog.html

`requirements/security.txt` contains audit tooling, separate from runtime
images. The dependency-security workflow resolves and audits production
requirements on changes and weekly. An advisory-source/network failure must
remain visible; it is not a clean audit. Resolve findings or document a
reviewed, narrowly scoped exception rather than suppressing audit failures.

Run upload, authentication, schema and report regressions before promotion.
Package patching alone does not establish production readiness.

Validation for this revision: production-requirements pip-audit reports no known
vulnerabilities; pip check and migration drift checks pass. Four isolated
PostgreSQL groups executed 148 + 178 + 228 + 198 = 752 tests successfully.
The monolithic run exceeded the 55-second command budget, so it was split.
SQLite baseline has the same seven failures and three errors before and after
the first patch upgrades (PostgreSQL-only search, decimal formatting, and cache
reuse); PostgreSQL is the authoritative database for this project. Cross-branch
integration and full release CI still must pass before promotion.
