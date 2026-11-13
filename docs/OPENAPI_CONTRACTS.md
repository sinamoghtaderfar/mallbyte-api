# OpenAPI contract repair

The initial schema command on the quality branch reported 514 warnings (210
unique) and 192 serializer-inference errors (45 unique). The custom JWT
authenticator was undocumented; APIViews lost response schemas, computed arrays
fell back to strings, and private cookie/MFA flows had incorrect input/output
descriptions. Client generation could therefore silently omit authentication or
send the wrong shape of credentials.

`AccountsConfig.ready()` now registers documentation extensions in
`config/openapi.py`. Domain contracts are separated into finance, commerce and
computed-field modules. Each view extension returns a subclass used only by the
schema generator; routed callbacks, permissions, authentication and domain
handlers are unchanged. Schema-only querysets avoid querying a real user/database
while inferring path types. No schema warnings are disabled or suppressed.

The generated authentication contract includes the actual Bearer JWT scheme,
OTP's ordinary-session/privileged-challenge alternatives, password/challenge/code
MFA inputs, one-time recovery codes and the refresh cookie. Refresh tokens are not
documented as JSON response fields. Registration describes provisional ownership
verification as introduced by the account-security stack.

Finance, analytics, cart, CMS homepage, product import/export, binary downloads,
discount and observability APIViews have explicit success envelopes and actual
input serializers. Computed arrays, numeric counters, seller scopes, relative
private download links and serializer-rendered money types have concrete schema
types. Stable domain choice-set names replace ambiguous `Status<hash>Enum` names.

Verification commands (use isolated test settings):

```sh
python manage.py spectacular --file /tmp/mallbyte-openapi.yaml --validate --fail-on-warn
python manage.py test config.tests.test_openapi_auth config.tests.test_openapi_commerce config.tests.test_openapi_finance
```

The finance regression suite validates 17 actual rendered endpoint responses
against their declared schemas. Schema tests check JWT, MFA/cookie payloads,
typed collections, binary/multipart media, OpenAPI validity and unchanged runtime
callbacks. Two conditional contract tests cover private return downloads, customer
evidence/tracking and explicit inventory restoration once those endpoint PRs are
present; they must run without skips on the combined release tree. Passing schema generation is not an authorization/security test; run
the domain regression suites as well.

The schema branch is based on PR #38. Its descriptions of hardened registration,
private return links and bounded collections target the combined remediation
release. Merge this documentation PR after the runtime remediation stacks; its
metadata describes that hardened release rather than the older parent branch
behavior. No warning filters are installed: `--fail-on-warn` passes with zero
generation warnings or errors.

When merging additional API endpoints or role-dependent response fields,
run schema validation on that complete tree and add their explicit metadata;
zero generator warnings alone do not prove every conditional response branch.
