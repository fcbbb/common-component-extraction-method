# l2_curl_tls — curl TLS backend: Schannel/Win32 -> OpenSSL on Kylin

- **Scenario**: `windows_to_kylin`
- **Level**: `L2`
- **Source**: https://github.com/curl/curl.git @ `7161cb17c01dcff1dc5bf89a18437d9d729f1ecd`
- **License**: curl
- **Target**: kylin-v10-sp3 / gcc-13.3

## Task

The target TLS vtls backend was removed; the Schannel backend and the
generic `vtls` interface stay visible.  Implement `lib/vtls/openssl.c`
against the target TLS backend:
  - the `Curl_ssl` backend vtable and version reporting;
  - certificate and hostname verification, SNI, ALPN, session reuse;
  - blocking and non-blocking handshakes with the curl connect state
    machine, including the "want read/want write" return codes;
  - client certificates, CRL and pinned public key hooks used by the
    curl callers.

## Workspace

`work/` is materialized by `prepare.sh`. The evaluator-only gold and hidden fixtures are not part of `work/`.
