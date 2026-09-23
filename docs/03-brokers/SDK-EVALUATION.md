# Broker SDK Evaluation — can the official Python SDKs meet the static-IP requirement?

**Status:** 🟢 Evidence-based · **confirms D-056b (raw HTTP)**
**Date:** 2026-09-23
**Method:** SDK packages downloaded from PyPI and read directly, not inferred from documentation.

---

## 1. The question that decides it

ATOM's hardest infrastructure constraint is **per-investor egress** (D-005, D-007): every call
for Person A must leave from Person A's whitelisted IPv4, and every call for Person B from
Person B's — from **one process on one EC2 instance**.

That rules out environment-variable proxies (`HTTPS_PROXY` is process-wide) and rules out any
HTTP client that cannot be given a proxy **per client instance**. So for each broker SDK the
question is narrow and testable:

> Can two clients in the same process route through two different proxies, for **every** call
> the SDK makes?

Note the last clause. A library that proxies most calls but not all is worse than one that
proxies none, because the leak is silent.

---

## 2. Upstox — ✅ per-instance proxy fully supported

`upstox-python-sdk` 2.30.0 is OpenAPI-generated over `urllib3`.

`upstox_client/configuration.py`:
```python
self.proxy = None
```

`upstox_client/rest.py`:
```python
if configuration.proxy:
    self.pool_manager = urllib3.ProxyManager(
        num_pools=pools_size, maxsize=maxsize, cert_reqs=cert_reqs,
        ca_certs=ca_certs, cert_file=configuration.cert_file,
        key_file=configuration.key_file,
        proxy_url=configuration.proxy, **addition_pool_args)
else:
    self.pool_manager = urllib3.PoolManager(...)
```

The proxy belongs to the `Configuration` object, and every call goes through that instance's
pool manager. **Two Configurations with two proxies coexist cleanly in one process.** The
Upstox SDK could satisfy the requirement.

---

## 3. Dhan — ⚠️ partially, and the gap is silent

`dhanhq` 2.2.0 routes trading calls through a per-instance `requests.Session`:

`dhanhq/dhan_http.py`:
```python
def __init__(self, client_id, access_token, disable_ssl=False, pool=None):
    ...
    self.session = requests.Session()
    if pool:
        reqadapter = requests.adapters.HTTPAdapter(**pool)
        self.session.mount("https://", reqadapter)
```

There is **no proxy parameter**, but `self.session.proxies` can be set after construction, so
trading calls are fixable.

**The problem is elsewhere.** Six calls bypass the session entirely, using module-level
`requests`:

```
dhanhq/auth.py:37     response = requests.post(url, params=params, headers=headers)
dhanhq/auth.py:75     response = requests.get(url, params=params, headers=headers)
dhanhq/auth.py:108    response = requests.post(url, params=params)
dhanhq/auth.py:139    response = requests.get(url, headers=headers)
dhanhq/auth.py:168    response = requests.get(url, headers=headers)
dhanhq/_security.py:113  response = requests.get(csv_url)
```

**Every one of these is in the authentication flow.** A proxy set on `session.proxies` does not
apply to them, so the token exchange would egress from the instance's default route while the
order calls egress from the account's whitelisted IP.

> 🔴 **This is the failure mode the design must avoid.** It is silent: orders succeed, so
> nothing looks broken, while authentication traffic for Person A leaves from the wrong address.
> Whether a broker treats that as a violation is their call to make, not ours to discover in
> production.

Fixing it means monkey-patching `requests` at module level — which is process-global and
therefore reintroduces exactly the problem we are avoiding — or forking the SDK.

---

## 4. Zerodha — ✅ the cleanest implementation of the five

`kiteconnect` 5.2.2 takes `proxies` as a constructor argument and passes it explicitly on
**every** request:

```python
self.proxies = proxies if proxies else {}
self.reqsession = requests.Session()
...
r = self.reqsession.request(method, url, ..., proxies=self.proxies)
```

Nothing bypasses it. If any SDK were to be used, this is the one that could be.

---

## 5. Groww — ❌ per-instance proxy is impossible

`growwapi` 1.5.0 uses **no session at all**. Every HTTP call is module-level `requests`:

```
growwapi/groww/client.py:179    requests.get(self.INSTRUMENT_CSV_URL)
growwapi/groww/client.py:1405   requests.get(...)
growwapi/groww/client.py:1440   requests.post(...)
growwapi/groww/client.py:1560   requests.post(url, headers=headers, json=data, timeout=15)
```

`grep -c 'requests.Session' → 0`. There is no per-instance object to attach a proxy to. The only
lever is the process-wide `HTTPS_PROXY` environment variable, which cannot differ per account —
exactly what the design rules out.

---

## 6. Shoonya — ❌ impossible, twice over

`NorenRestApiPy` 0.0.22:

- **26 bare `requests.post` calls. Zero sessions.** Same impossibility as Groww, at greater scale.
- **No GTT or alert methods exist in the SDK** (`grep 'def .*gtt\|def .*alert' → nothing`),
  confirming the capability-matrix finding: Shoonya's GTT is REST-only. ATOM's sell logic is
  GTT-based (D-063), so the SDK cannot express the core operation regardless of proxy behaviour.

---

## 7. Conclusion — three of five SDKs cannot meet the requirement

| Broker | Sessions | Bare `requests` calls | Per-instance proxy | Verdict |
|---|---|---|---|---|
| **Zerodha** | ✅ 1 | 0 | ✅ `proxies=` on every request | SDK would work |
| **Upstox** | n/a (urllib3) | 0 | ✅ `configuration.proxy` | SDK would work |
| **Dhan** | ✅ 1 | **6, all in auth** | ⚠️ trading yes, **auth leaks** | Silent leak |
| **Groww** | ❌ 0 | **5** | ❌ impossible | Cannot comply |
| **Shoonya** | ❌ 0 | **26** | ❌ impossible | Cannot comply, **and no GTT** |

**Raw HTTP for all five**, as D-056b decided. Three independent reasons, now demonstrated
rather than asserted:

1. **Uniform proxy control.** One HTTP layer where the proxy is an explicit per-request
   parameter — no library gets to decide which calls honour it.
2. **No silent leaks.** A single client means a single place to assert that every outbound call
   carried the right source address. That assertion is testable, and should be a test.
3. **Capability, not preference.** Shoonya's SDK simply cannot do what the strategy requires.

### What the SDKs are still worth

They remain the **best available specification** of each broker's API: exact endpoint paths,
payload shapes, enum values and error formats, read from working code rather than prose. The
per-broker documents should cite them, and the adapters should be validated against their
request/response shapes.

*Practical note: PyPI is reachable from restricted environments where broker sites are not, so
reading an SDK is often the fastest route to an accurate endpoint list.*

---

## 6. Requirement this creates

**Every broker adapter must take an explicit proxy per call, and there must be a test proving
no code path can reach a broker without one.** The natural shape:

```python
class BrokerAdapter:
    def __init__(self, credentials, proxy_url: str):   # proxy is mandatory, not optional
        ...
```

A missing proxy should raise, never fall back to the default route. (Q-222)

| ID | Item |
|---|---|
| Q-222 | Confirm: a missing proxy raises rather than defaulting — no silent fallback to the instance's own IP |
| ~~Q-223~~ | ✅ Verified — Zerodha passes, Groww and Shoonya cannot comply at all |
